"""Index layer: extract -> chunk -> persisted LlamaIndex VectorStoreIndex."""

from peerdex.index._index import (
    attribute_predicate,
    doc_predicate,
    index_dir,
    index_doc,
    table,
)
from peerdex.index._parents import ParentStore
from peerdex.index._parse_cache import parse_cached

__all__ = [
    "ParentStore",
    "attribute_predicate",
    "doc_predicate",
    "index_dir",
    "index_doc",
    "parse_cached",
    "table",
]
