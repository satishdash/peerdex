"""Index layer: extract -> chunk -> persisted LlamaIndex VectorStoreIndex."""

from peerdex.index._index import (
    attribute_predicate,
    doc_predicate,
    ensure_fts_index,
    index_doc,
    load_index,
    table,
)

__all__ = [
    "attribute_predicate",
    "doc_predicate",
    "ensure_fts_index",
    "index_doc",
    "load_index",
    "table",
]
