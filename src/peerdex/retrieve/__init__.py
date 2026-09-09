"""Lexical retrieval: BM25 over the filtered docstore. The agent adds the reasoning."""

from peerdex.retrieve._retriever import LexicalRetriever, RetrievalResult, retrieve

__all__ = ["LexicalRetriever", "RetrievalResult", "retrieve"]
