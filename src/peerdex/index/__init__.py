"""Index layer: extract -> chunk -> persisted LlamaIndex VectorStoreIndex."""

from peerdex.index._index import (
    attribute_predicate,
    doc_predicate,
    ensure_fts_index,
    ensure_vector_index,
    index_doc,
    load_index,
    table,
)
from peerdex.index._parse_cache import parse_cached

__all__ = [
    "attribute_predicate",
    "doc_predicate",
    "ensure_fts_index",
    "ensure_vector_index",
    "index_doc",
    "load_index",
    "parse_cached",
    "table",
]
