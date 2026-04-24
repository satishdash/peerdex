"""Index layer: ExtractedDoc -> persisted LlamaIndex VectorStoreIndex.

Storage:
  - LanceDB at settings.storage.lancedb_uri (table = settings.storage.table_name)
  - Persisted docstore + index_store at settings.storage.cache_uri/llama-index/

Public API:
  - index_doc(pdf_path, company, year, report_type)  -> dict (idempotent)
  - load_index() -> VectorStoreIndex (re-opens existing index)

Idempotency: re-indexing the same (company, year, report_type) deletes the
prior LanceDB rows for that doc_id before inserting -- so re-running with
an updated PDF or a prompt_version bump replaces cleanly without dupes.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import lancedb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.storage.index_store import SimpleIndexStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.lancedb import LanceDBVectorStore

from peerdex.chunk import Chunker
from peerdex.parse import get_extractor
from peerdex.shared.ids import doc_id as make_doc_id
from peerdex.shared.logging import get_logger
from peerdex.shared.schema import ReportType
from peerdex.shared.settings import get_settings

log = get_logger("index")


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


def _delete_existing_doc(doc_id: str) -> None:
    """Remove any prior rows for this doc_id from LanceDB so re-index is clean."""
    s = get_settings()
    try:
        db = lancedb.connect(s.storage.lancedb_uri)
        if s.storage.table_name in db.table_names():
            tbl = db.open_table(s.storage.table_name)
            tbl.delete(f"metadata.doc_id = '{doc_id}'")
            log.info(f"[index] cleared prior rows for doc_id={doc_id}")
    except Exception as e:
        log.debug(f"[index] delete prior rows skipped: {e}")


async def index_doc(
    pdf_path: str | Path,
    *,
    company: str,
    year: int,
    report_type: ReportType | str,
    extractor: str | None = None,
) -> dict[str, Any]:
    """Extract -> chunk -> embed+store. Idempotent per (company, year, type)."""
    rt = ReportType(str(report_type))
    did = make_doc_id(company, year, rt)
    pdf_abs = str(Path(pdf_path).resolve())

    log.info(f"[index] doc_id={did} company={company} year={year} type={rt.value}")

    # 1) Extract (sync — CPU-bound Docling work, no benefit from async)
    ed = get_extractor(extractor).extract(pdf_abs)

    # 2) Chunk (async — VLM calls for pictures are IO-bound)
    nodes = await Chunker().chunk(
        ed,
        doc_id=did,
        company=company,
        year=int(year),
        report_type=rt,
        source_uri=pdf_abs,
    )

    # 3) Wipe prior + insert
    _delete_existing_doc(did)
    storage = storage_context()
    embed = embed_model()

    # VectorStoreIndex with insert_batch_size kept implicit (LI default).
    idx = VectorStoreIndex(
        nodes=nodes,
        storage_context=storage,
        embed_model=embed,
        show_progress=True,
    )
    # LanceDBVectorStore.stores_text=True, so VectorStoreIndex skips the
    # docstore. We still need the nodes there for downstream BM25
    # (BM25Retriever.from_defaults(nodes=docstore.values())) and for any
    # future reranker that wants raw text without re-querying Lance.
    storage.docstore.add_documents(nodes, allow_update=True)
    storage.persist(persist_dir=_persist_dir())

    log.info(f"[index] persisted {len(nodes)} nodes (doc_id={did})")
    return {
        "doc_id": did,
        "nodes": len(nodes),
        "tables": sum(1 for n in nodes if n.metadata.get("is_table")),
        "figures": sum(1 for n in nodes if n.metadata.get("is_figure")),
        "extractor": ed.source_meta.get("extractor_name"),
    }


def load_index() -> VectorStoreIndex:
    """Re-open the persisted index for queries."""
    storage = storage_context()
    return VectorStoreIndex.from_vector_store(
        vector_store=vector_store(),
        storage_context=storage,
        embed_model=embed_model(),
    )
