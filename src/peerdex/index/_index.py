"""Index layer: ExtractedDoc -> persisted LlamaIndex VectorStoreIndex.

Storage is LanceDB (vector rows) plus a persisted docstore/index_store.
doc_id is content-addressed, so re-indexing a file first deletes its prior
LanceDB rows and replaces them cleanly.
"""

import asyncio
import math
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.storage.index_store import SimpleIndexStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore

import lancedb
from peerdex.chunk import HierarchicalChunker
from peerdex.index._parse_cache import parse_cached
from peerdex.parse import ExtractedDoc, Extractor, get_extractor
from peerdex.shared.ids import doc_id as make_doc_id
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import (
    CompositeAttributeSource,
    DocumentMetadata,
    ExplicitAttributeSource,
    Scalar,
    SidecarAttributeSource,
    SidecarYearSource,
)
from peerdex.shared.settings import get_settings

log = get_logger("index")

_SAFE_KEY: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _persist_dir() -> str:
    s = get_settings()
    p = Path(s.storage.cache_uri) / "llama-index"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


@lru_cache(maxsize=1)
def embed_model() -> OpenAIEmbedding:
    s = get_settings()
    return OpenAIEmbedding(model=s.embed.model, embed_batch_size=s.embed.batch_size)


def vector_store() -> LanceDBVectorStore:
    s = get_settings()
    log.info(f"opening lancedb at {s.storage.lancedb_uri} table={s.storage.table_name}")
    db = lancedb.connect(s.storage.lancedb_uri)
    mode = "append" if s.storage.table_name in db.table_names() else "create"
    return LanceDBVectorStore(
        uri=s.storage.lancedb_uri,
        table_name=s.storage.table_name,
        mode=mode,
    )


def storage_context() -> StorageContext:
    persist = _persist_dir()
    has_state = (Path(persist) / "docstore.json").exists()
    if has_state:
        return StorageContext.from_defaults(
            vector_store=vector_store(),
            docstore=SimpleDocumentStore.from_persist_dir(persist),
            index_store=SimpleIndexStore.from_persist_dir(persist),
            persist_dir=persist,
        )
    return StorageContext.from_defaults(
        vector_store=vector_store(),
        docstore=SimpleDocumentStore(),
        index_store=SimpleIndexStore(),
        persist_dir=persist,
    )


def table() -> Any:
    """The LanceDB table itself, for full-text search and row predicates."""
    s = get_settings()
    db = lancedb.connect(s.storage.lancedb_uri)
    return db.open_table(s.storage.table_name)


def ensure_fts_index() -> None:
    """Build the full-text index over the chunk text unless the table already has one.

    LanceDB keeps this inverted index (tantivy) beside the rows, so lexical search no
    longer needs the whole docstore loaded and re-stemmed in memory per process.
    """
    tbl = table()
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


def ensure_vector_index() -> None:
    """Build the approximate-nearest-neighbour index unless the table already has one.

    Without it every dense query scans every row. That is milliseconds on a few
    thousand rows and seconds on a few million, so the index is what makes dense
    retrieval possible at production size rather than merely faster.

    The type comes from ``index.vector_type``. Changing that setting is enough:
    an index of a different type is replaced, so switching costs a rebuild and
    never a re-embedding or a data migration.
    """
    tbl = table()
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


def _delete_existing_doc(doc_id: str) -> None:
    """Remove any prior rows for this doc_id from LanceDB so re-index is clean."""
    s = get_settings()
    try:
        db = lancedb.connect(s.storage.lancedb_uri)
        if s.storage.table_name in db.table_names():
            tbl = db.open_table(s.storage.table_name)
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
    """Compose the document metadata (sidecar first, explicit wins)."""
    source = CompositeAttributeSource(
        [SidecarAttributeSource(), ExplicitAttributeSource(dict(attributes or {}))]
    )
    return DocumentMetadata(
        company=company,
        year=int(year),
        source_uri=str(pdf_abs),
        extractor=extractor_name,
        attributes=source.load(pdf_abs),
    )


def _resolved_year(pdf_abs: Path, year: int | None) -> int:
    """The explicit year, else the one the document's sidecar states.

    Explicit input wins, the same rule attributes follow. Neither is an error rather
    than a default: a wrong year silently corrupts every year-filtered answer for
    that document, which is worse than refusing to ingest it.
    """
    if year is not None:
        return int(year)
    stated: int | None = SidecarYearSource().load(pdf_abs)
    if stated is None:
        raise ValueError(f"no year given and no sidecar year for {pdf_abs.name}")
    return stated


async def index_doc(
    pdf_path: str | Path,
    *,
    company: str,
    year: int | None = None,
    extractor: str | None = None,
    attributes: Mapping[str, Scalar] | None = None,
) -> dict[str, Any]:
    """Extract -> chunk -> embed+store. Idempotent per source file and extractor."""
    pdf_abs: str = str(_resolve(pdf_path))
    year = _resolved_year(Path(pdf_abs), year)

    extractor_inst: Extractor = get_extractor(extractor)
    ed: ExtractedDoc = await parse_cached(pdf_abs, extractor_inst)

    extractor_name: str = str(ed.source_meta["extractor_name"])
    doc_meta = _document_metadata(Path(pdf_abs), company, year, extractor_name, attributes)
    did = make_doc_id(company, pdf_abs, extractor_name)

    log.info(
        f"[index] doc_id={did} company={doc_meta.company} year={doc_meta.year} "
        f"extractor={doc_meta.extractor} attributes={doc_meta.attributes} source={pdf_abs}"
    )

    parent_nodes, child_nodes = await HierarchicalChunker().chunk(
        ed,
        doc_id=did,
        metadata=doc_meta,
    )

    _delete_existing_doc(did)
    storage = storage_context()
    embed = embed_model()

    VectorStoreIndex(
        nodes=child_nodes,
        storage_context=storage,
        embed_model=embed,
        show_progress=True,
    )
    storage.docstore.add_documents(parent_nodes + child_nodes, allow_update=True)
    storage.persist(persist_dir=_persist_dir())
    ensure_fts_index()
    ensure_vector_index()

    log.info(f"[index] persisted {len(child_nodes)} nodes (doc_id={did})")
    return {
        "doc_id": did,
        "nodes": len(child_nodes),
        "tables": sum(1 for n in child_nodes if n.metadata.get("is_table")),
        "figures": sum(1 for n in child_nodes if n.metadata.get("is_figure")),
        "extractor": ed.source_meta.get("extractor_name"),
        "attributes": doc_meta.attributes,
    }


def _pdfs_in(dir_path: str | Path) -> tuple[Path, list[Path]]:
    """The resolved directory and the PDFs directly inside it, sorted."""
    directory: Path = Path(dir_path).expanduser().resolve()
    return directory, sorted(p for p in directory.glob("*.pdf") if p.is_file())


async def index_dir(
    dir_path: str | Path,
    *,
    company: str,
    year: int | None = None,
    extractor: str | None = None,
    attributes: Mapping[str, Scalar] | None = None,
) -> list[dict[str, Any]]:
    """Index every PDF in a directory, each with the year its own sidecar states.

    Sorted so a run is reproducible and a partial one is resumable by eye. Sequential
    for now: document-level concurrency is its own piece of work, with its own
    measurement, because the largest document dominates the wall clock.
    """
    directory: Path
    pdfs: list[Path]
    directory, pdfs = await asyncio.to_thread(_pdfs_in, dir_path)
    if not pdfs:
        raise ValueError(f"no PDFs in {directory}")

    log.info(f"[index] ingesting {len(pdfs)} documents from {directory}")
    results: list[dict[str, Any]] = []
    for pdf in pdfs:
        results.append(
            await index_doc(
                pdf,
                company=company,
                year=_resolved_year(pdf, year),
                extractor=extractor,
                attributes=attributes,
            )
        )
    return results


def load_index() -> VectorStoreIndex:
    """Re-open the persisted index for queries."""
    storage = storage_context()
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store(),
        storage_context=storage,
        embed_model=embed_model(),
    )
