"""Index layer: extract -> chunk -> persisted LlamaIndex VectorStoreIndex."""

from peerdex.index._index import (
    attribute_predicate,
    doc_predicate,
    index_dir,
    index_doc,
    load_index,
    table,
)
from peerdex.index._parse_cache import parse_cached

__all__ = [
    "attribute_predicate",
    "doc_predicate",
    "index_dir",
    "index_doc",
    "load_index",
    "parse_cached",
    "table",
]
