"""Escalation when nothing came back: a lexical rewrite, then one more search."""

import re
from collections.abc import Sequence
from typing import ClassVar

from ask.passage import Passage


class Rewriter:
    """Broadens a query lexically, so the second search is not the first one repeated.

    Lexical, not a model: the flow allows one LLM call, or two on escalation, and both
    of those belong to Read. Qualifiers that narrow a search are dropped and the terms
    that name the metric are kept.
    """

    _STOP: ClassVar[frozenset[str]] = frozenset(
        {
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "by",
            "did",
            "do",
            "does",
            "for",
            "from",
            "had",
            "has",
            "have",
            "how",
            "in",
            "is",
            "it",
            "its",
            "much",
            "of",
            "on",
            "or",
            "our",
            "own",
            "s",
            "that",
            "the",
            "their",
            "then",
            "there",
            "these",
            "this",
            "those",
            "to",
            "total",
            "was",
            "were",
            "what",
            "when",
            "which",
            "who",
            "whose",
            "why",
            "with",
            "year",
            "years",
        }
    )
    _WORD: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
    _KEEP: ClassVar[int] = 8

    @classmethod
    def rewrite(cls, question: str, passages: Sequence[Passage]) -> str:
        """A broader query than the one that returned nothing.

        Args:
            question: The question whose search came back empty.
            passages: Whatever came back, which is nothing on this branch.

        Returns:
            The rewritten query.
        """
        terms: list[str] = cls._terms(question)
        return " ".join(terms + cls._borrowed(passages, terms))

    @classmethod
    def _terms(cls, question: str) -> list[str]:
        """The question's own terms, with the words that narrow a search dropped.

        Args:
            question: The question being broadened.

        Returns:
            The surviving terms, in order and without repeats.
        """
        words: list[str] = cls._WORD.findall(question.lower())
        kept: dict[str, None] = {w: None for w in words if w not in cls._STOP}
        return list(kept)[: cls._KEEP]

    @classmethod
    def _borrowed(cls, passages: Sequence[Passage], terms: Sequence[str]) -> list[str]:
        """Wording taken from what came back, when anything came back.

        Args:
            passages: Whatever the search returned.
            terms: The terms already kept from the question.

        Returns:
            The borrowed terms, none of them already present.
        """
        if not passages:
            return []
        words: list[str] = cls._WORD.findall(passages[0].text.lower())
        fresh: dict[str, None] = {w: None for w in words if w not in cls._STOP and w not in terms}
        return list(fresh)[: cls._KEEP]
