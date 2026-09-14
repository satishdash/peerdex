"""Find: one database call does filter, search, rerank and top k."""

from collections.abc import Mapping
from typing import Any, ClassVar

from ask.find.reranker_factory import RerankerFactory
from ask.passage import Passage
from ask.question import Question
from index import Embeddings, Predicates, Tables
from shared.attribute_filter import AttributeFilter
from shared.settings import get_settings


class Finder:
    """Searches one filtered slice of a domain and returns the best passages.

    The filter is a SQL predicate on stored metadata, so it narrows before ranking
    rather than discarding after. Mode and reranker are settings, and reranking costs
    no API call because it is local or arithmetic.
    """

    _HIGHER_IS_BETTER: ClassVar[tuple[str, ...]] = ("_relevance_score", "_score")

    @classmethod
    async def find(cls, question: Question) -> list[Passage]:
        """The best passages for this question, in one database call.

        Args:
            question: The question, carrying the company and any attribute filters.

        Returns:
            The passages, best first, at most ``retrieval.final_top_k`` of them.
        """
        cfg = get_settings().retrieval
        builder: Any = await cls._searched(question, cfg.query_type)
        builder = builder.where(cls._predicate(question))
        engine: Any = RerankerFactory.for_name(cfg.reranker).engine()
        if engine is not None:
            builder = builder.rerank(engine)
        return [cls._passage(row) for row in builder.limit(cfg.final_top_k).to_list()]

    @classmethod
    async def _searched(cls, question: Question, mode: str) -> Any:
        """The query builder for this mode, before filtering and ranking.

        Full text uses the question verbatim and costs no embedding. Hybrid ranks
        twice, so it is given the vector and the text explicitly.

        Args:
            question: The question being asked.
            mode: The configured search mode.

        Returns:
            The query builder.
        """
        table: Any = Tables.open(question.domain)
        if mode == "fts":
            return table.search(question.text, query_type="fts")
        if mode == "hybrid":
            vector: list[float] = await cls._vector(question.text)
            return table.search(query_type="hybrid").vector(vector).text(question.text)
        return table.search(await cls._vector(question.text))

    @staticmethod
    async def _vector(text: str) -> list[float]:
        """The question as an embedding, which costs one API call.

        Args:
            text: The question.

        Returns:
            The query embedding.
        """
        return await Embeddings.model().aget_query_embedding(text)

    @staticmethod
    def _predicate(question: Question) -> str:
        """The SQL predicate narrowing the search, with company always on.

        Args:
            question: The question, carrying the company and any attribute filters.

        Returns:
            The predicate.
        """
        return Predicates.attributes(AttributeFilter(question.company, question.filters).pairs)

    @classmethod
    def _passage(cls, row: Mapping[str, Any]) -> Passage:
        """One returned row as a passage.

        Args:
            row: The row as the database returned it.

        Returns:
            The passage, its score normalised so higher is better.
        """
        return Passage(
            id=str(row["id"]),
            text=str(row["text"]),
            score=cls._score(row),
            parent_id=str(row.get("parent_id") or ""),
            metadata=dict(row.get("metadata") or {}),
        )

    @classmethod
    def _score(cls, row: Mapping[str, Any]) -> float:
        """One row's relevance, whichever mode produced it.

        Args:
            row: The row as the database returned it.

        Returns:
            The relevance, higher being better.
        """
        for key in cls._HIGHER_IS_BETTER:
            if row.get(key) is not None:
                return float(row[key])
        return cls._from_distance(row)

    @staticmethod
    def _from_distance(row: Mapping[str, Any]) -> float:
        """A dense hit's distance as a relevance, since smaller distance is better.

        Args:
            row: The row as the database returned it.

        Returns:
            The relevance, or zero when the row carries no score at all.
        """
        distance: Any = row.get("_distance")
        if distance is None:
            return 0.0
        return 1.0 / (1.0 + float(distance))
