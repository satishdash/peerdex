"""Lexical retrieval over the peerdex index.

One step: LanceDB full-text search over the chunk text, narrowed by a SQL
predicate on stored metadata, best ``final_top_k`` rows returned. The question
is used verbatim, so every returned passage traces back to one chunk on one
page.

The database does the work. LanceDB keeps an inverted index (tantivy) beside
the rows, so there is nothing to build in memory, nothing to cache, and no
second copy of the corpus to keep in step.

This is deliberately the smallest thing that works. The intelligence lives in
``peerdex.agent``, which plans, reformulates the query from what came back, and
retries. Components are added back here one at a time, each with a measured
score, rather than stacked up front.

Removed, with the number that justified it:

  * dense (embedding) search and reciprocal-rank fusion. Lexical search alone
    scored the same as dense+lexical fusion on the metric suite and dense alone
    scored worse. Metric questions name the row label they want, which is what
    lexical search is good at; a conversational question would be the case for
    bringing dense back.
  * an in-memory BM25 index over the docstore, which had to be rebuilt and
    re-stemmed per process and scored 10/28 against this path's 11/28.
  * HyDE and multi-query expansion, two LLM calls per question that also made
    the pipeline non-deterministic (12 then 13 on identical input).
  * ``AutoMergingRetriever``, which looped forever on one query and replaced
    precise row groups with whole tables.
  * the LLM reranker, worth +4 and the obvious first thing to add back.

Filtering: ``company`` is always on; arbitrary attribute filters are optional,
each key admitting one or more values (AND across keys, OR within a key).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode

from peerdex.index import attribute_predicate, table
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import AttributeFilter, Scalars
from peerdex.shared.resilience import light_decorator
from peerdex.shared.settings import get_settings

log = get_logger("retrieve")


@dataclass
class RetrievalResult:
    nodes: list[NodeWithScore]
    refused: bool
    reason: str = ""


def _as_node(row: Mapping[str, Any]) -> NodeWithScore:
    """One LanceDB row as a scored node, keeping the id so a passage stays traceable."""
    return NodeWithScore(
        node=TextNode(
            id_=str(row["id"]),
            text=str(row["text"]),
            metadata=dict(row.get("metadata") or {}),
        ),
        score=float(row.get("_score") or 0.0),
    )


class LexicalRetriever:
    """LanceDB full-text search over one filtered slice of the corpus."""

    def __init__(
        self,
        *,
        company: str,
        attributes: Mapping[str, Scalars] | None = None,
    ) -> None:
        self._cfg = get_settings().retrieval
        self._filter: AttributeFilter = AttributeFilter(company, attributes)
        self._predicate: str = attribute_predicate(self._filter.pairs)

    @light_decorator()
    async def retrieve(self, query: str) -> RetrievalResult:
        """Full-text search the filtered slice, best ``final_top_k`` passages."""
        search = table().search(query, query_type="fts")
        if self._predicate:
            search = search.where(self._predicate)
        rows = search.limit(self._cfg.final_top_k).to_list()

        nodes = [_as_node(row) for row in rows]
        log.info(f"[retrieve] fts hits={len(nodes)} where={self._predicate}")
        return RetrievalResult(
            nodes=nodes,
            refused=not nodes,
            reason="" if nodes else "no_full_text_matches",
        )


async def retrieve(
    query: str,
    *,
    company: str,
    filters: Mapping[str, Scalars] | None = None,
) -> RetrievalResult:
    """Module-level helper: one-shot lexical retrieval with optional attribute filters."""
    return await LexicalRetriever(company=company, attributes=filters).retrieve(query)
