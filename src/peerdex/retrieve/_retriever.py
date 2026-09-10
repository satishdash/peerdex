"""Retrieval over the peerdex index: one search, no reasoning.

One step, one database call: LanceDB search over the child chunks, narrowed by a
SQL predicate on stored metadata, best ``final_top_k`` rows returned. Every
returned passage traces back to one chunk on one page.

Two modes, chosen by ``retrieval.query_type``:

  * ``fts`` — full-text search over the chunk text via LanceDB's inverted index
    (tantivy). The question is used verbatim and no API call is made.
  * ``vector`` — dense search over the stored embeddings. Costs one embedding of
    the question. Measured 19/28 against full text's 17/28 on the metric suite,
    over three runs with zero spread, missing nothing full text found.

The database does the work either way: an index sits beside the rows, so there
is nothing to build in memory and no second copy of the corpus to keep in step.

This is deliberately the smallest thing that works. The intelligence lives in
``peerdex.agent``, which plans, reformulates the query from what came back, and
retries. Components are added back here one at a time, each with a measured
score, rather than stacked up front.

Still out, with the number that justified it:

  * reciprocal-rank fusion of the two modes. A naive fusion scored 17/28 against
    dense alone at 19/28, because averaging in the weaker ranking pushes good
    dense hits out of the window. LanceDB's own hybrid search with a reranker is
    the version worth trying.
  * an in-memory BM25 index over the docstore, rebuilt and re-stemmed per
    process, which scored 10/28 against this path's 11/28 at the time.
  * HyDE and multi-query expansion, two LLM calls per question that also made
    the pipeline non-deterministic (16, then 12, then 13 on identical input).
  * ``AutoMergingRetriever``, which looped forever on one query and replaced
    precise row groups with whole tables.
  * the LLM reranker, historically worth +4 on the lexical path.

Filtering: ``company`` is always on; arbitrary attribute filters are optional,
each key admitting one or more values (AND across keys, OR within a key).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from llama_index.core.schema import NodeWithScore, TextNode

from peerdex.index import attribute_predicate, table
from peerdex.index._index import embed_model
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import AttributeFilter, Scalars
from peerdex.shared.resilience import light_decorator
from peerdex.shared.settings import get_settings, resolve_domain

log = get_logger("retrieve")


@dataclass
class RetrievalResult:
    nodes: list[NodeWithScore]
    refused: bool
    reason: str = ""


_NO_MATCH: Final[Mapping[str, str]] = {
    "fts": "no_full_text_matches",
    "vector": "no_vector_matches",
}


def _relevance(row: Mapping[str, Any]) -> float:
    """Higher is better, whichever search produced the row.

    Full-text search returns ``_score`` where larger is better; vector search
    returns ``_distance`` where smaller is better. Reading only ``_score`` would
    silently score every dense hit zero and leave citations in arbitrary order.
    """
    if row.get("_score") is not None:
        return float(row["_score"])
    return 1.0 / (1.0 + float(row.get("_distance") or 0.0))


def _as_node(row: Mapping[str, Any]) -> NodeWithScore:
    """One LanceDB row as a scored node, keeping the id so a passage stays traceable."""
    return NodeWithScore(
        node=TextNode(
            id_=str(row["id"]),
            text=str(row["text"]),
            metadata=dict(row.get("metadata") or {}),
        ),
        score=_relevance(row),
    )


class PassageRetriever:
    """LanceDB search over one filtered slice of the corpus, full-text or dense.

    The mode is configuration, not a code path choice: ``retrieval.query_type``
    selects it and a caller may override per instance. Full-text costs no API
    call; dense costs one embedding of the question.
    """

    def __init__(
        self,
        *,
        company: str,
        domain: str,
        attributes: Mapping[str, Scalars] | None = None,
        query_type: str | None = None,
    ) -> None:
        cfg = get_settings().retrieval
        self._domain: str = resolve_domain(domain)
        self._top_k: int = cfg.final_top_k
        self._query_type: str = query_type or cfg.query_type
        self._refine_factor: int = cfg.vector_refine_factor
        self._filter: AttributeFilter = AttributeFilter(company, attributes)
        self._predicate: str = attribute_predicate(self._filter.pairs)

    @light_decorator()
    async def retrieve(self, query: str) -> RetrievalResult:
        """Search the filtered slice, best ``final_top_k`` passages."""
        search = table(self._domain).search(await self._target(query), query_type=self._query_type)
        if self._predicate:
            search = search.where(self._predicate)
        if self._query_type == "vector":
            search = search.refine_factor(self._refine_factor)
        rows = search.limit(self._top_k).to_list()

        nodes = [_as_node(row) for row in rows]
        log.info(f"[retrieve] {self._query_type} hits={len(nodes)} where={self._predicate}")
        return RetrievalResult(
            nodes=nodes,
            refused=not nodes,
            reason="" if nodes else _NO_MATCH.get(self._query_type, "no_matches"),
        )

    async def _target(self, query: str) -> Any:
        """The question as the chosen mode wants it: text, or an embedding of it."""
        if self._query_type == "fts":
            return query
        return await embed_model().aget_query_embedding(query)


async def retrieve(
    query: str,
    *,
    company: str,
    domain: str,
    filters: Mapping[str, Scalars] | None = None,
) -> RetrievalResult:
    """Module-level helper: one-shot retrieval with optional attribute filters."""
    return await PassageRetriever(company=company, domain=domain, attributes=filters).retrieve(
        query
    )
