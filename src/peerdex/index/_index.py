"""Index layer: ExtractedDoc -> persisted LlamaIndex VectorStoreIndex.

Storage is LanceDB (vector rows) plus a persisted docstore/index_store.
doc_id is content-addressed, so re-indexing a file first deletes its prior
LanceDB rows and replaces them cleanly.
"""

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


async def index_doc(
    pdf_path: str | Path,
    *,
    company: str,
    year: int,
    extractor: str | None = None,
    attributes: Mapping[str, Scalar] | None = None,
) -> dict[str, Any]:
    """Extract -> chunk -> embed+store. Idempotent per source file and extractor."""
    pdf_abs: str = str(_resolve(pdf_path))

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

    log.info(f"[index] persisted {len(child_nodes)} nodes (doc_id={did})")
    return {
        "doc_id": did,
        "nodes": len(child_nodes),
        "tables": sum(1 for n in child_nodes if n.metadata.get("is_table")),
        "figures": sum(1 for n in child_nodes if n.metadata.get("is_figure")),
        "extractor": ed.source_meta.get("extractor_name"),
        "attributes": doc_meta.attributes,
    }


def load_index() -> VectorStoreIndex:
    """Re-open the persisted index for queries."""
    storage = storage_context()
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store(),
        storage_context=storage,
        embed_model=embed_model(),
    )
