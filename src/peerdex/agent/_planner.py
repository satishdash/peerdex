"""The agent's two pure steps: planning a question, and rewriting one that failed.

Neither calls an LLM. Both read only the question and the passages already
retrieved, so both are driven directly by tests.
"""

import re
from collections.abc import Sequence

from llama_index.core.schema import NodeWithScore

from peerdex.agent._model import Plan, QuestionKind
from peerdex.quantity import ArithmeticQuestion

_PERIOD: re.Pattern[str] = re.compile(r"\b(?:19|20)\d{2}\b")
_SCOPE: re.Pattern[str] = re.compile(r"\b(market-based|location-based)\b", re.IGNORECASE)
_TRAILING_UNIT: re.Pattern[str] = re.compile(r"\(([^()\s][^()]{0,14})\)\s*$")


class QuestionPlanner:
    """Plan step: resolve the kind (caller wins) and extract qualifiers, no LLM call."""

    _QUALITATIVE_MARKERS: tuple[str, ...] = (
        "describe",
        "explain",
        "why ",
        "how does",
        "how is",
        "policy",
        "approach",
        "strategy",
        "governance",
        "process",
    )

    def __init__(self, arithmetic: ArithmeticQuestion | None = None) -> None:
        self._arithmetic: ArithmeticQuestion = arithmetic or ArithmeticQuestion()

    def plan(self, question: str, kind: QuestionKind | None = None, period: str = "") -> Plan:
        """Resolve kind and qualifiers; a caller-supplied kind or period fills the gaps.

        A period spelled out in the question is more specific than the one the
        corpus is filtered to, so it wins.
        """
        resolved: QuestionKind = kind if kind is not None else self._classify(question)
        return Plan(
            kind=resolved,
            period=self._first(_PERIOD, question) or period,
            scope=self._first(_SCOPE, question).lower(),
            unit=self._trailing_unit(question),
            derivation=self._arithmetic.read(question),
        )

    def _classify(self, question: str) -> QuestionKind:
        lowered: str = question.lower()
        qualitative: bool = any(marker in lowered for marker in self._QUALITATIVE_MARKERS)
        return "qualitative" if qualitative else "quantitative"

    @staticmethod
    def _first(pattern: re.Pattern[str], question: str) -> str:
        match: re.Match[str] | None = pattern.search(question)
        return match[0] if match else ""

    @staticmethod
    def _trailing_unit(question: str) -> str:
        match: re.Match[str] | None = _TRAILING_UNIT.search(question.strip())
        return match[1] if match else ""


class QueryReformulator:
    """Reflect step: rewrite a failed query with headings and table row labels seen so far."""

    def __init__(self, max_terms: int = 8) -> None:
        self._max_terms: int = max_terms

    def reformulate(self, question: str, nodes: Sequence[NodeWithScore]) -> str:
        """The question enriched with passage vocabulary; unchanged when there is none."""
        vocabulary: list[str] = self._vocabulary(nodes)[: self._max_terms]
        return question if not vocabulary else f"{question} {' '.join(vocabulary)}"

    def _vocabulary(self, nodes: Sequence[NodeWithScore]) -> list[str]:
        terms: dict[str, None] = {}
        for node in nodes:
            for term in [*self._headings(node), *self._row_labels(node)]:
                terms.setdefault(term, None)
        return list(terms)

    @staticmethod
    def _headings(node: NodeWithScore) -> list[str]:
        heading_path: str = str(node.node.metadata.get("heading_path") or "")
        return [part.strip() for part in heading_path.split(" > ") if part.strip()]

    @staticmethod
    def _row_labels(node: NodeWithScore) -> list[str]:
        lines: list[str] = node.node.get_content().splitlines()
        raw: list[str] = [line.split("|")[1].strip() for line in lines if line.startswith("|")]
        return [label for label in raw if label.strip("- ")]
