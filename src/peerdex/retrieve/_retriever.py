"""Hybrid retrieval over a persisted peerdex index.

Stages, all driven by the prompts in ``peerdex.shared.prompts``:

  1. Multi-query expand + RRF fusion: ``QueryFusionRetriever`` paraphrases the
     question, runs dense (LanceDB) and BM25 (docstore) retrievers, and fuses
     with reciprocal-rank fusion.
  2. HyDE expansion (optional, on by default): a hypothetical answer is
     embedded as an additional query vector.
  3. LLM rerank + threshold: candidates scoring below ``min_rerank_score``
     are dropped, so the final list may be empty and the caller refuses.

Filtering: ``company`` is always on; arbitrary attribute equality filters are
optional. Both the dense ``MetadataFilters`` and the BM25 node predicate are
derived from the same ``AttributeFilter`` so they can never diverge.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.postprocessor.llm_rerank import LLMRerank
from llama_index.core.prompts import PromptTemplate
from llama_index.core.retrievers import (
    AutoMergingRetriever,
    QueryFusionRetriever,
    VectorIndexRetriever,
)
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.vector_stores.types import (
    MetadataFilter,
    MetadataFilters,
)
from llama_index.retrievers.bm25 import BM25Retriever

from peerdex.index._index import embed_model, storage_context, vector_store
from peerdex.shared.llm_llama import CachedLIOpenAI
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import AttributeFilter, Scalar
from peerdex.shared.prompts import PROMPTS
from peerdex.shared.resilience import light_decorator
from peerdex.shared.settings import get_settings

log = get_logger("retrieve")

_HYDE_TMPL = PromptTemplate(
    "You are drafting a hypothetical passage that would appear in a {label} "
    "and would directly answer the user question. Use the document's own "
    "phrasing wherever possible.\n\n"
    "{domain_brief}\n\n"
    "Question: {{context_str}}\n\n"
    "Hypothetical passage:\n"
)

_RERANK_TMPL = PromptTemplate(
    "You are scoring passages from a {label} for relevance to a question.\n\n"
    "{rerank_criteria}\n\n"
    "Score each passage 1-10:\n"
    "  10 = passage states the requested figure (label + number + unit).\n"
    "   7 = passage contains a related breakdown or subtotal.\n"
    "   4 = passage discusses the topic without the number.\n"
    "   1 = passage is about a different topic entirely.\n\n"
    "A passage about a DIFFERENT financial metric (debt, options, capital) "
    "scores 1 even if it mentions the question's keyword incidentally.\n\n"
    "Markdown tables: first column is the row label. Read row labels to "
    "decide if the table contains the requested metric.\n\n"
    "Do not include any documents that are not relevant to the question.\n"
    "Example format:\n"
    "Document 1:\n<summary of document 1>\n\n"
    "Document 2:\n<summary of document 2>\n\n"
    "...\n\nDocument 10:\n<summary of document 10>\n\n"
    "Question: <question>\nAnswer:\nDoc: 9, Relevance: 7\n"
    "Doc: 3, Relevance: 4\nDoc: 7, Relevance: 3\n\n"
    "Let's try this now:\n\n{context_str}\n\nQuestion: {query_str}\nAnswer:\n"
)


@dataclass
class RetrievalResult:
    nodes: list[NodeWithScore]
    expanded_queries: list[str]
    refused: bool
    reason: str = ""


class HybridRetriever:
    """Compose dense+BM25 RRF, HyDE, and LLM rerank over one filtered node set."""

    def __init__(
        self,
        *,
        company: str,
        attributes: Mapping[str, Scalar] | None = None,
        use_hyde: bool = True,
        min_rerank_score: float = 4.0,
    ) -> None:
        self.use_hyde = use_hyde
        self.min_rerank_score = min_rerank_score
        self._cfg = get_settings().retrieval
        self._filter: AttributeFilter = AttributeFilter(company, attributes)
        self._filters: MetadataFilters = self.dense_filters(self._filter)

        self._storage: StorageContext = storage_context()
        self._index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store(),
            storage_context=self._storage,
            embed_model=embed_model(),
        )

        s = get_settings()
        _kw = {"temperature": 0.0, "additional_kwargs": {"seed": 7}}
        self._fusion_llm = CachedLIOpenAI(
            model=s.llm.fusion_model or s.llm.model,
            **_kw,
        )
        self._hyde_llm = CachedLIOpenAI(
            model=s.llm.hyde_model or s.llm.model,
            **_kw,
        )
        self._reranker_llm = CachedLIOpenAI(
            model=s.llm.reranker_model or s.llm.model,
            **_kw,
        )

    @staticmethod
    def dense_filters(attribute_filter: AttributeFilter) -> MetadataFilters:
        """Project the shared predicate onto LanceDB metadata filters."""
        return MetadataFilters(
            filters=[
                MetadataFilter(key=key, value=value)
                for key, value in attribute_filter.pairs.items()
            ]
        )

    def _dense(self) -> VectorIndexRetriever:
        return VectorIndexRetriever(
            index=self._index,
            similarity_top_k=self._cfg.top_k_dense,
            embed_model=embed_model(),
            filters=self._filters,
        )

    def _bm25(self) -> BM25Retriever:
        """BM25 over docstore nodes passing the same predicate the dense path filters on."""
        nodes = [
            n for n in self._storage.docstore.docs.values() if self._filter.matches(n.metadata)
        ]
        if not nodes:
            raise RuntimeError(
                f"BM25 source is empty for filter={self._filter.pairs!r}. "
                "Did you run `rag index` for this company?"
            )
        return BM25Retriever.from_defaults(
            nodes=nodes,
            similarity_top_k=self._cfg.top_k_bm25,
        )

    def _fusion(self) -> QueryFusionRetriever:
        fusion_prompt = (
            f"You are generating search queries to retrieve passages from a "
            f"{PROMPTS.label}.\n"
            f"{PROMPTS.domain_brief}\n\n"
            f"Document vocabulary: {PROMPTS.expansion_vocab}\n\n"
            "Generate {num_queries} queries (one per line, no numbering) for "
            "the user question below. Each query MUST be different:\n"
            "  1. Use the document's exact table/section labels from the "
            "vocabulary above (for lexical search).\n"
            "  2. Use a semantic synonym or plain-language rephrasing "
            "(for embedding search).\n"
            "  3+. Mix vocabulary terms with the question's intent "
            "in different combinations.\n\n"
            "Keep queries short (under 15 words). Do NOT repeat the original "
            "question.\n\n"
            "User question: {query}\n\nQueries:\n"
        )
        return QueryFusionRetriever(
            retrievers=[self._dense(), self._bm25()],
            llm=self._fusion_llm,
            similarity_top_k=max(self._cfg.top_k_dense, self._cfg.top_k_bm25),
            num_queries=4,
            mode="reciprocal_rerank",
            use_async=True,
            verbose=False,
            query_gen_prompt=fusion_prompt,
        )

    def _reranker(self) -> LLMRerank:
        rerank_prompt = _RERANK_TMPL.partial_format(
            label=PROMPTS.label,
            rerank_criteria=PROMPTS.rerank_criteria,
        )
        return LLMRerank(
            llm=self._reranker_llm,
            choice_select_prompt=rerank_prompt,
            choice_batch_size=5,
            top_n=self._cfg.rerank_top_k,
        )

    @light_decorator()
    async def retrieve(self, query: str) -> RetrievalResult:
        """Dense+BM25 RRF, HyDE, and LLM rerank. Direct LanceDB path."""
        bundle = QueryBundle(query_str=query)
        return await self._retrieve_open(query, bundle)

    @staticmethod
    def _normalize(nodes: list[NodeWithScore]) -> list[NodeWithScore]:
        """Min-max normalise scores to [0, 1] in-place so BM25 raw scores do not
        dwarf dense cosine similarities."""
        if not nodes:
            return nodes
        scores = [n.score or 0.0 for n in nodes]
        lo, hi = min(scores), max(scores)
        span = hi - lo if hi > lo else 1.0
        for n in nodes:
            n.score = ((n.score or 0.0) - lo) / span
        return nodes

    async def _hyde_expand(self, bundle: QueryBundle) -> QueryBundle:
        """Async HyDE: generate a hypothetical passage, embed alongside original."""
        prompt = _HYDE_TMPL.partial_format(
            label=PROMPTS.label,
            domain_brief=PROMPTS.domain_brief,
        )
        from llama_index.core.base.llms.types import ChatMessage

        messages = [
            ChatMessage(role="user", content=prompt.format(context_str=bundle.query_str)),
        ]
        response = await self._hyde_llm.achat(messages)
        hypothesis = response.message.content or ""
        return QueryBundle(
            query_str=bundle.query_str,
            custom_embedding_strs=[bundle.query_str, hypothesis],
        )

    async def _retrieve_open(self, query: str, bundle: QueryBundle) -> RetrievalResult:
        log.info("[retrieve] fusion + HyDE")
        if self.use_hyde:
            bundle = await self._hyde_expand(bundle)

        fusion = self._fusion()
        auto_merging = AutoMergingRetriever(
            fusion,
            storage_context=self._storage,
            verbose=False,
            simple_ratio_thresh=0.5,
        )
        candidates = await auto_merging.aretrieve(bundle)
        log.info(f"[retrieve] fusion candidates={len(candidates)}")
        if not candidates:
            return RetrievalResult(
                nodes=[],
                expanded_queries=list(bundle.custom_embedding_strs or []),
                refused=True,
                reason="no_candidates_from_fusion",
            )

        reranker = self._reranker()
        reranked = await reranker.apostprocess_nodes(candidates, query_bundle=bundle)
        kept = [n for n in reranked if (n.score or 0.0) >= self.min_rerank_score]
        kept = kept[: self._cfg.final_top_k]
        log.info(f"[retrieve] reranked={len(reranked)} kept(>={self.min_rerank_score})={len(kept)}")

        return RetrievalResult(
            nodes=kept,
            expanded_queries=list(bundle.custom_embedding_strs or []),
            refused=not kept,
            reason="" if kept else "all_candidates_below_threshold",
        )


async def retrieve(
    query: str,
    *,
    company: str,
    filters: Mapping[str, Scalar] | None = None,
) -> RetrievalResult:
    """Module-level helper: one-shot hybrid retrieval with optional attribute filters."""
    return await HybridRetriever(company=company, attributes=filters).retrieve(query)
