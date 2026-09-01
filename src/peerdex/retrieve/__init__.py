"""Hybrid retrieval pipeline: dense + BM25 (RRF) → HyDE expansion → LLM rerank."""

from peerdex.retrieve._retriever import HybridRetriever, RetrievalResult, retrieve

__all__ = ["HybridRetriever", "RetrievalResult", "retrieve"]
