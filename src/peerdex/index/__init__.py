"""Index layer: extract -> chunk -> persisted LlamaIndex VectorStoreIndex."""

from peerdex.index._index import index_doc, load_index

__all__ = ["index_doc", "load_index"]
