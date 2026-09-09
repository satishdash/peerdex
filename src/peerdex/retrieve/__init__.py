"""Retrieval: one filtered LanceDB search, full-text or dense. The agent reasons."""

from peerdex.retrieve._retriever import PassageRetriever, RetrievalResult, retrieve

__all__ = ["PassageRetriever", "RetrievalResult", "retrieve"]
