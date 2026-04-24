"""Hybrid retrieval over a persisted peerdex index.

Stages (all driven by per-report-type prompts in ``peerdex.shared.prompts``):

  1. Multi-query expand (RRF fusion):
        - ``QueryFusionRetriever`` generates ``num_queries`` paraphrases biased
          toward the report's expansion vocabulary, then runs each through
          BOTH dense (LanceDB) and BM25 (LlamaIndex docstore) retrievers and
          fuses with reciprocal-rank fusion.

  2. HyDE expansion (optional, on by default):
        - ``HyDEQueryTransform`` writes a hypothetical answer constrained by
          the report's ``domain_brief``; the embedding of that hypothesis is
          used as an additional query vector. Improves recall on
          terminology-mismatch questions ("how many people work at X" →
          "Total ... Employees ... year-end") without touching BM25.

  3. LLM rerank + threshold:
        - ``LLMRerank`` scores each candidate against the query using a
          report-type-specific ``rerank_criteria`` prompt, returns top-N.
          Scores below ``min_rerank_score`` are dropped → final list may be
          empty (caller should refuse rather than synthesise garbage).

Everything is wrapped in ``light_decorator()`` (Retry + Timeout) so transient
OpenAI failures don't break a query. No circuit breaker — user-facing.
"""

from dataclasses import dataclass
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.postprocessor.llm_rerank import LLMRerank
from llama_index.core.prompts import PromptTemplate
from llama_index.core.retrievers import QueryFusionRetriever, VectorIndexRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.vector_stores.types import (
    MetadataFilter,
    MetadataFilters,
)
from llama_index.retrievers.bm25 import BM25Retriever

from peerdex.index._index import embed_model, storage_context, vector_store
from peerdex.retrieve._router import boost as route_boost, match as route_match, merge_unique
from peerdex.shared.llm_llama import CachedLIOpenAI
from peerdex.shared.logging import get_logger
from peerdex.shared.prompts import ReportPrompts, prompts_for
from peerdex.shared.resilience import light_decorator
from peerdex.shared.schema import ReportType
from peerdex.shared.settings import get_settings

log = get_logger("retrieve")


# ---------- prompt templates (parameterised by ReportPrompts) ----------

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


# ---------- public surface ----------

@dataclass
class RetrievalResult:
    nodes: list[NodeWithScore]
    expanded_queries: list[str]
    report_type: ReportType | None
    refused: bool
    reason: str = ""


class HybridRetriever:
    """Compose dense+BM25 RRF, HyDE, and LLM rerank for one report type."""

    def __init__(
        self,
        *,
        company: str,
        year: int,
        report_type: ReportType | None = None,
        use_hyde: bool = True,
        min_rerank_score: float = 4.0,
    ) -> None:
        self.company = company
        self.year = year
        self.report_type = report_type
        self.use_hyde = use_hyde
        self.min_rerank_score = min_rerank_score
        self.prompts: ReportPrompts = prompts_for(report_type)
        self._cfg = get_settings().retrieval

        # Metadata filters: always scoped to company+year.
        # If report_type is given, narrow further; otherwise search all types.
        filters = [
            MetadataFilter(key="company", value=company.strip().lower()),
            MetadataFilter(key="year", value=year),
        ]
        if report_type is not None:
            filters.append(MetadataFilter(key="report_type", value=str(report_type)))
        self._filters = MetadataFilters(filters=filters)

        # LlamaIndex StorageContext bundles vector_store + docstore (BM25
        # source). _storage_context() reuses the on-disk SimpleDocumentStore
        # persisted at index time, so BM25 sees identical nodes to dense.
        self._storage: StorageContext = storage_context()
        self._index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store(),
            storage_context=self._storage,
            embed_model=embed_model(),
        )

        s = get_settings()
        # seed + temperature=0 makes fusion paraphrases and LLM-rerank
        # tie-breaks reproducible across runs (OpenAI honors `seed` as
        # best-effort determinism).
        self._llm = CachedLIOpenAI(
            model=s.llm.retriever_model or s.llm.model,
            temperature=0.0,
            additional_kwargs={"seed": 7},
        )

    # ----- retriever assembly -----

    def _dense(self) -> VectorIndexRetriever:
        return VectorIndexRetriever(
            index=self._index,
            similarity_top_k=self._cfg.top_k_dense,
            embed_model=embed_model(),
            filters=self._filters,
        )

    def _bm25(self) -> BM25Retriever:
        # Pull every node out of the persisted docstore. Cheap: a few
        # thousand nodes; tantivy / rank_bm25 builds the index in-memory.
        # Filter to current company+year (+ optional report_type) since
        # BM25Retriever has no metadata filter support.
        company_lower = self.company.strip().lower()
        rt_str = str(self.report_type) if self.report_type is not None else None
        nodes = [
            n for n in self._storage.docstore.docs.values()
            if (n.metadata.get("company") or "").strip().lower() == company_lower
            and n.metadata.get("year") == self.year
            and (rt_str is None or n.metadata.get("report_type") == rt_str)
        ]
        if not nodes:
            raise RuntimeError(
                f"BM25 source is empty for company={self.company!r} year={self.year}. "
                "Did you run `rag index` for this company/year?"
            )
        return BM25Retriever.from_defaults(
            nodes=nodes,
            similarity_top_k=self._cfg.top_k_bm25,
        )

    def _fusion(self) -> QueryFusionRetriever:
        # QueryFusionRetriever only substitutes {num_queries} and {query};
        # we pre-render report-type bits and leave those two as placeholders.
        fusion_prompt = (
            f"You are generating search queries to retrieve passages from a "
            f"{self.prompts.label}.\n"
            f"{self.prompts.domain_brief}\n\n"
            f"Document vocabulary: {self.prompts.expansion_vocab}\n\n"
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
            llm=self._llm,
            similarity_top_k=max(self._cfg.top_k_dense, self._cfg.top_k_bm25),
            num_queries=4,
            mode="reciprocal_rerank",
            use_async=True,
            verbose=False,
            query_gen_prompt=fusion_prompt,
        )

    def _reranker(self) -> LLMRerank:
        rerank_prompt = _RERANK_TMPL.partial_format(
            label=self.prompts.label,
            rerank_criteria=self.prompts.rerank_criteria,
        )
        return LLMRerank(
            llm=self._llm,
            choice_select_prompt=rerank_prompt,
            choice_batch_size=5,
            top_n=self._cfg.rerank_top_k,
        )

    # ----- public call -----

    @light_decorator()
    async def retrieve(self, query: str) -> RetrievalResult:
        """Two-path retrieval:

        - **Router-hit (deterministic fast path)**: skip fusion-paraphrase
          LLM and HyDE entirely. Run dense + BM25 directly on
          ``query`` and on ``query + canonical_keywords``, merge unique
          by node_id, apply additive boosts, take top-N by boost score.
        - **Router-miss (LLM-aided path)**: QueryFusionRetriever
          paraphrases + HyDE + LLMRerank.
        """
        bundle = QueryBundle(query_str=query)
        hit = await route_match(query)

        if hit is not None:
            return await self._retrieve_router_hit(query, bundle, hit)
        return await self._retrieve_open(query, bundle)

    # ----- router-hit fast path (no fusion-paraphrase LLM, no HyDE, no reranker) -----

    async def _retrieve_router_hit(self, query: str, bundle: QueryBundle, hit) -> RetrievalResult:
        log.info(f"[retrieve] router-hit={hit.route.name} (deterministic path)")
        dense = self._dense()
        bm25 = self._bm25()

        primary = dense.retrieve(bundle) + bm25.retrieve(bundle)
        aug_bundle = QueryBundle(query_str=hit.augmented_query)
        extra = dense.retrieve(aug_bundle) + bm25.retrieve(aug_bundle)
        candidates = merge_unique(primary, extra)

        candidates, _signals = route_boost(candidates, hit.route)
        candidates.sort(key=lambda n: n.score or 0.0, reverse=True)
        kept = candidates[: self._cfg.final_top_k]
        kept = [n for n in kept if (n.score or 0.0) >= self.min_rerank_score]
        log.info(f"[retrieve] router-hit kept={len(kept)}")
        return RetrievalResult(
            nodes=kept,
            expanded_queries=[hit.augmented_query],
            report_type=hit.report_type,
            refused=not kept,
            reason="" if kept else "router_hit_but_all_below_threshold",
        )

    # ----- router-miss path (fusion + HyDE) -----

    async def _hyde_expand(self, bundle: QueryBundle) -> QueryBundle:
        """Async HyDE: generate a hypothetical passage, embed alongside original."""
        prompt = _HYDE_TMPL.partial_format(
            label=self.prompts.label,
            domain_brief=self.prompts.domain_brief,
        )
        from llama_index.core.base.llms.types import ChatMessage
        messages = [
            ChatMessage(role="user", content=prompt.format(context_str=bundle.query_str)),
        ]
        response = await self._llm.achat(messages)
        hypothesis = response.message.content or ""
        # Return a new bundle that includes both the original query and the
        # hypothesis as additional embedding strings.
        return QueryBundle(
            query_str=bundle.query_str,
            custom_embedding_strs=[bundle.query_str, hypothesis],
        )

    async def _retrieve_open(self, query: str, bundle: QueryBundle) -> RetrievalResult:
        log.info("[retrieve] router-miss (fusion + HyDE)")
        if self.use_hyde:
            bundle = await self._hyde_expand(bundle)

        fusion = self._fusion()
        candidates = await fusion.aretrieve(bundle)
        log.info(f"[retrieve] fusion candidates={len(candidates)}")
        if not candidates:
            return RetrievalResult(
                nodes=[], expanded_queries=list(bundle.custom_embedding_strs or []),
                report_type=None, refused=True,
                reason="no_candidates_from_fusion",
            )

        reranker = self._reranker()
        reranked = await reranker.apostprocess_nodes(candidates, query_bundle=bundle)
        kept = [n for n in reranked if (n.score or 0.0) >= self.min_rerank_score]
        kept = kept[: self._cfg.final_top_k]
        log.info(
            f"[retrieve] reranked={len(reranked)} kept(>={self.min_rerank_score})={len(kept)}"
        )

        return RetrievalResult(
            nodes=kept,
            expanded_queries=list(bundle.custom_embedding_strs or []),
            report_type=None,
            refused=not kept,
            reason="" if kept else "all_candidates_below_threshold",
        )


# ---------- module-level helper used by CLI ----------


async def retrieve(
    query: str,
    *,
    company: str,
    year: int,
    report_type: ReportType | None = None,
) -> RetrievalResult:
    retriever = HybridRetriever(
        company=company, year=year, report_type=report_type,
    )
    return await retriever.retrieve(query)
