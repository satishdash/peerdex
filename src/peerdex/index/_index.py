"""Index layer: ExtractedDoc -> persisted LlamaIndex VectorStoreIndex.

Storage is LanceDB: child rows in the domain's table, parents in its parent table.
doc_id is content-addressed, so re-indexing a file first deletes its prior
LanceDB rows and replaces them cleanly.
"""

import asyncio
import math
import re
import traceback
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore

import lancedb
from peerdex.chunk import HierarchicalChunker
from peerdex.index._parents import ParentStore
from peerdex.index._parse_cache import parse_cached
from peerdex.parse import ExtractedDoc, Extractor, get_extractor
from peerdex.shared.ids import doc_id as make_doc_id
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import DocumentMetadata, Scalar
from peerdex.shared.settings import get_settings, resolve_domain
from peerdex.vlm import dlq_put

_PARSE_FAILURE: Final[str] = "parse"
log = get_logger("index")

_SAFE_KEY: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@lru_cache(maxsize=1)
def embed_model() -> OpenAIEmbedding:
    s = get_settings()
    return OpenAIEmbedding(model=s.embed.model, embed_batch_size=s.embed.batch_size)


def vector_store(domain: str) -> LanceDBVectorStore:
    s = get_settings()
    log.info(f"opening lancedb at {s.storage.lancedb_uri} table={domain}")
    db = lancedb.connect(s.storage.lancedb_uri)
    mode = "append" if domain in db.table_names() else "create"
    return LanceDBVectorStore(uri=s.storage.lancedb_uri, table_name=domain, mode=mode)


def storage_context(domain: str) -> StorageContext:
    """Somewhere to put the child rows, and nothing that is written to disk.

    The docstore LlamaIndex creates here is never persisted or read back: the rows it
    would hold are already in the table, and parents go to ``ParentStore``. Persisting
    it meant loading and rewriting one JSON file per ingest, 33MB at 9,160 rows, so the
    cost of adding a document grew with the corpus instead of with the document.
    """
    return StorageContext.from_defaults(vector_store=vector_store(domain))


def table(domain: str) -> Any:
    """This domain's LanceDB table, for full-text search and row predicates.

    A domain owns its table, so the domain name *is* the table name.
    """
    s = get_settings()
    db = lancedb.connect(s.storage.lancedb_uri)
    return db.open_table(resolve_domain(domain))


def _ensure_fts_index(domain: str) -> None:
    """Build the full-text index over the chunk text unless the table already has one.

    LanceDB keeps this inverted index (tantivy) beside the rows, so lexical search no
    longer needs the whole docstore loaded and re-stemmed in memory per process.
    """
    tbl = table(domain)
    if any(getattr(i, "index_type", "") == "FTS" for i in tbl.list_indices()):
        return
    tbl.create_fts_index("text", replace=True)
    log.info("[index] built FTS index over text")


_QUANTISED: Final[frozenset[str]] = frozenset(
    {"IVF_SQ", "IVF_PQ", "IVF_RQ", "IVF_HNSW_SQ", "IVF_HNSW_PQ"}
)


def _vector_index_shape(rows: int, dim: int) -> tuple[int, int]:
    """Partitions and sub-vectors for the vector index, derived from the table's size.

    Partitions sit near the square root of the row count, the usual balance between
    how many centroids must be compared and how much of the table each one holds.
    Sub-vectors must divide the embedding dimension; 16 dimensions each keeps the
    quantisation error low enough to matter little at this scale. They are passed
    only to the types that quantise - see ``_QUANTISED``.

    Deriving both from the data is the point: a hardcoded pair tuned on one corpus
    would be wrong for the next one.
    """
    partitions: int = max(1, min(4096, int(math.sqrt(rows))))
    return partitions, max(1, dim // 16)


def _vector_dim(tbl: Any) -> int:
    """Width of the embedding column, read from the table rather than assumed."""
    field: Any = tbl.schema.field("vector")
    return int(field.type.list_size)


def _vector_index(tbl: Any) -> Any | None:
    """The existing index over the vector column, or None.

    Selected by column rather than by type name, so the full-text index over
    ``text`` is never mistaken for it.
    """
    for index in tbl.list_indices():
        if "vector" in [str(column) for column in getattr(index, "columns", [])]:
            return index
    return None


def _same_type(reported: str, configured: str) -> bool:
    """Whether LanceDB's own spelling of an index type is the configured one.

    LanceDB reports ``IvfPq`` where the setting says ``IVF_PQ``. Comparing the two
    verbatim is always false, which silently rebuilt the index on every ingest.
    """
    return reported.replace("_", "").lower() == configured.replace("_", "").lower()


def _ensure_vector_index(domain: str) -> None:
    """Build the approximate-nearest-neighbour index unless the table already has one.

    Without it every dense query scans every row. That is milliseconds on a few
    thousand rows and seconds on a few million, so the index is what makes dense
    retrieval possible at production size rather than merely faster.

    The type comes from ``index.vector_type``. Changing that setting is enough:
    an index of a different type is replaced, so switching costs a rebuild and
    never a re-embedding or a data migration.
    """
    tbl = table(domain)
    index_type: str = get_settings().index.vector_type
    existing: Any | None = _vector_index(tbl)
    if existing is not None and _same_type(str(existing.index_type), index_type):
        return
    rows: int = tbl.count_rows()
    partitions: int
    sub_vectors: int
    partitions, sub_vectors = _vector_index_shape(rows, _vector_dim(tbl))
    quantised: dict[str, int] = {"num_sub_vectors": sub_vectors} if index_type in _QUANTISED else {}
    tbl.create_index(
        metric="cosine",
        num_partitions=partitions,
        vector_column_name="vector",
        index_type=index_type,
        replace=True,
        **quantised,
    )
    log.info(
        f"[index] built {index_type} over vector rows={rows} "
        f"partitions={partitions} sub_vectors={sub_vectors}"
    )


def _unindexed_rows(tbl: Any) -> int:
    """The most rows any existing index does not yet cover."""
    return max(
        (int(getattr(index, "num_unindexed_rows", 0) or 0) for index in tbl.list_indices()),
        default=0,
    )


def _refresh_indices(domain: str) -> None:
    """Fold newly ingested rows into the indexes that already exist.

    Embedding a document stores its vector; it does not put that row inside the
    full-text or vector index. Both indexes are built once and skipped afterwards,
    so without this every document after the first sits outside them. LanceDB
    answers such rows by scanning, which keeps results correct while the cost grows
    back to exactly what the index was built to avoid.

    Incremental by design: ``optimize`` folds the new rows in, where rebuilding from
    scratch costs minutes at production size and is what this replaced.
    """
    tbl = table(domain)
    pending: int = _unindexed_rows(tbl)
    if not pending:
        return
    tbl.optimize()
    log.info(f"[index] folded {pending} new rows into the existing indexes")


def _literal(value: Scalar) -> str:
    """One filter value as a SQL literal, quoting and escaping strings."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def attribute_predicate(pairs: Mapping[str, tuple[Scalar, ...]]) -> str:
    """SQL predicate over stored metadata: AND across keys, OR within a key.

    Attribute keys can arrive from a sidecar file, so anything that is not a plain
    identifier is refused rather than interpolated into the query.
    """
    clauses: list[str] = []
    for key, values in pairs.items():
        if not _SAFE_KEY.match(key):
            raise ValueError(f"unsafe attribute key: {key!r}")
        rendered = ", ".join(_literal(v) for v in values)
        if len(values) == 1:
            clauses.append(f"metadata.{key} = {rendered}")
        else:
            clauses.append(f"metadata.{key} IN ({rendered})")
    return " AND ".join(clauses)


def doc_predicate(doc_id: str) -> str:
    """LanceDB predicate matching every row of one indexed document.

    LlamaIndex reserves ``doc_id`` in stored metadata and overwrites it with the node's
    ``ref_doc_id``, so the document hash is matched under the key the chunker owns.
    """
    return f"metadata.source_doc_id = '{doc_id}'"


def _delete_existing_doc(doc_id: str, domain: str) -> None:
    """Remove any prior rows for this doc_id from LanceDB so re-index is clean."""
    s = get_settings()
    try:
        db = lancedb.connect(s.storage.lancedb_uri)
        if domain in db.table_names():
            tbl = db.open_table(domain)
            tbl.delete(doc_predicate(doc_id))
            log.info(f"[index] cleared prior rows for doc_id={doc_id}")
    except Exception as e:
        log.debug(f"[index] delete prior rows skipped: {e}")


def _resolve(pdf_path: str | Path) -> Path:
    return Path(pdf_path).resolve()


def _document_metadata(
    pdf_abs: Path,
    company: str,
    year: int,
    extractor_name: str,
    attributes: Mapping[str, Scalar] | None,
) -> DocumentMetadata:
    """Compose the document metadata. Attributes come from the caller, nowhere else."""
    return DocumentMetadata(
        company=company,
        year=int(year),
        source_uri=str(pdf_abs),
        extractor=extractor_name,
        attributes=dict(attributes or {}),
    )


def _index_table(domain: str) -> None:
    """Make every stored row searchable, building what is missing and folding in the rest.

    This is part of ingesting a document, not a step a caller can forget: embedding a
    chunk stores its vector, it does not put that row inside an index. A row outside
    the index is still answered, by scanning, which is the cost the index exists to
    remove.
    """
    _ensure_fts_index(domain)
    _ensure_vector_index(domain)
    _refresh_indices(domain)


async def _ingest_one(
    pdf_path: str | Path,
    *,
    company: str,
    domain: str,
    year: int,
    extractor: str | None,
    attributes: Mapping[str, Scalar] | None,
) -> dict[str, Any]:
    """Extract -> chunk -> embed+store one document, leaving the indexes to the caller.

    Private because an ingest that stops here leaves rows outside the indexes. The
    two public entry points both finish the job; a directory does it once at the end
    rather than per document, because optimising compacts the whole table.
    """
    pdf_abs: str = str(_resolve(pdf_path))

    extractor_inst: Extractor = get_extractor(extractor)
    ed: ExtractedDoc = await parse_cached(pdf_abs, extractor_inst)

    extractor_name: str = str(ed.source_meta["extractor_name"])
    doc_meta = _document_metadata(Path(pdf_abs), company, year, extractor_name, attributes)
    did = make_doc_id(company, pdf_abs, extractor_name)

    log.info(
        f"[index] doc_id={did} domain={domain} company={doc_meta.company} "
        f"extractor={doc_meta.extractor} attributes={doc_meta.attributes} source={pdf_abs}"
    )

    parent_nodes, child_nodes = await HierarchicalChunker().chunk(
        ed,
        doc_id=did,
        metadata=doc_meta,
    )

    _delete_existing_doc(did, domain)
    storage = storage_context(domain)
    embed = embed_model()

    VectorStoreIndex(
        nodes=child_nodes,
        storage_context=storage,
        embed_model=embed,
        show_progress=True,
    )
    parents: int = ParentStore(domain).put(did, parent_nodes)

    log.info(f"[index] persisted {len(child_nodes)} nodes, {parents} parents (doc_id={did})")
    return {
        "doc_id": did,
        "nodes": len(child_nodes),
        "tables": sum(1 for n in child_nodes if n.metadata.get("is_table")),
        "figures": sum(1 for n in child_nodes if n.metadata.get("is_figure")),
        "extractor": ed.source_meta.get("extractor_name"),
        "attributes": doc_meta.attributes,
    }


def _failure_record(
    pdf_path: str | Path, company: str, extractor: str | None, exc: Exception
) -> dict[str, Any]:
    """Keep an unreadable document's traceback, and describe the skip to the caller.

    The traceback goes to the dead-letter queue rather than only to the terminal,
    because an upstream crash is reported as a bug and cannot be recovered from
    scrollback once a sixteen-document run has scrolled past it.
    """
    resolved: str = str(_resolve(pdf_path))
    instance: Extractor = get_extractor(extractor)
    did: str = make_doc_id(company, resolved, instance.name)
    detail: str = f"{type(exc).__name__}: {exc}"
    dlq_put(
        did,
        _PARSE_FAILURE,
        {
            "source": resolved,
            "extractor": instance.name,
            "extractor_version": instance.version,
            "error": detail,
            "traceback": "".join(traceback.format_exception(exc)),
        },
    )
    log.error(f"[index] skipped {resolved}: {detail}")
    return {"doc_id": did, "source": resolved, "failed": True, "error": detail}


async def _ingest_or_record(
    pdf_path: str | Path,
    *,
    company: str,
    domain: str,
    year: int,
    extractor: str | None,
    attributes: Mapping[str, Scalar] | None,
) -> dict[str, Any]:
    """One document ingested, or a failure record when its extractor cannot read it.

    A corpus is a set of documents, and one of them being unreadable must not cost
    the others. Any exception counts: an extractor is third-party code and the ways
    it can fail are not ours to enumerate.
    """
    try:
        return await _ingest_one(
            pdf_path,
            company=company,
            domain=domain,
            year=year,
            extractor=extractor,
            attributes=attributes,
        )
    except Exception as exc:
        return _failure_record(pdf_path, company, extractor, exc)


def _stored_anything(results: list[dict[str, Any]]) -> bool:
    """Whether any document reached the table, since indexing an absent one would fail."""
    return any(not result.get("failed") for result in results)


async def index_doc(
    pdf_path: str | Path,
    *,
    company: str,
    domain: str,
    year: int,
    extractor: str | None = None,
    attributes: Mapping[str, Scalar] | None = None,
) -> dict[str, Any]:
    """Extract -> chunk -> embed+store -> searchable. Idempotent per file and extractor.

    Returns with the document's rows inside both indexes. Indexing is not a separate
    call, because one that can be forgotten will be.
    """
    resolved: str = resolve_domain(domain)
    result: dict[str, Any] = await _ingest_or_record(
        pdf_path,
        company=company,
        domain=resolved,
        year=year,
        extractor=extractor,
        attributes=attributes,
    )
    if _stored_anything([result]):
        await asyncio.to_thread(_index_table, resolved)
    return result


def _pdfs_in(dir_path: str | Path) -> tuple[Path, list[Path]]:
    """The resolved directory and the PDFs directly inside it, sorted."""
    directory: Path = Path(dir_path).expanduser().resolve()
    return directory, sorted(p for p in directory.glob("*.pdf") if p.is_file())


async def index_dir(
    dir_path: str | Path,
    *,
    company: str,
    domain: str,
    year: int,
    extractor: str | None = None,
    attributes: Mapping[str, Scalar] | None = None,
) -> list[dict[str, Any]]:
    """Index every PDF in a directory, all under the one year given.

    Returns with every document searchable. Sorted so a run is reproducible and a
    partial one is resumable by eye. Sequential for now: document-level concurrency
    is its own piece of work, with its own measurement, because the largest document
    dominates the wall clock.

    The indexes are brought up to date once at the end rather than per document,
    because doing so compacts the whole table.
    """
    resolved: str = resolve_domain(domain)
    directory: Path
    pdfs: list[Path]
    directory, pdfs = await asyncio.to_thread(_pdfs_in, dir_path)
    if not pdfs:
        raise ValueError(f"no PDFs in {directory}")

    log.info(f"[index] ingesting {len(pdfs)} documents from {directory}")
    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        results.append(
            await _ingest_or_record(
                pdf,
                company=company,
                domain=resolved,
                year=year,
                extractor=extractor,
                attributes=attributes,
            )
        )
    if _stored_anything(results):
        await asyncio.to_thread(_index_table, resolved)
    return results
