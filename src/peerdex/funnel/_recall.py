"""Funnel stage cores: parse recall (stages 0/1) and retrieval recall with miss attribution."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from peerdex.funnel._corpus import SearchableBlock
from peerdex.scoring import AnswerScorer, Comparison, NumericParser

type HitKind = Literal["exact", "scale"]
type RecallStatus = Literal["exact", "scale", "miss"]
type RetrievalStatus = Literal["hit", "not_extractable", "not_retrieved"]

_HIT_KIND: dict[str, HitKind] = {"match": "exact", "scale_mismatch": "scale"}


@dataclass(frozen=True)
class OracleValue:
    """One ground-truth value: the question and the oracle's value string."""

    question: str
    expected: str


@dataclass(frozen=True)
class ValueHit:
    """Where an oracle value was found and how exactly."""

    hit_kind: HitKind
    number: float
    scale: float | None
    source: str
    page_no: int
    block_kind: str
    heading_path: str


@dataclass(frozen=True)
class QuestionRecall:
    """Stage 0/1 verdict for one question with every location that carried the value."""

    question: str
    expected: str
    status: RecallStatus
    hits: list[ValueHit]


@dataclass(frozen=True)
class RetrievedPassage:
    """One retrieved node's text and page."""

    text: str
    page_no: int


@dataclass(frozen=True)
class RetrievalOutcome:
    """Stage 2 verdict for one question, with the miss attributed to its stage."""

    question: str
    expected: str
    status: RetrievalStatus
    page_hit: bool
    retrieved_pages: list[int]
    expected_pages: list[int]


class ValueMatcher:
    """Finds an oracle value among all numeric tokens of a text; exact beats scaled."""

    def __init__(
        self, scorer: AnswerScorer | None = None, parser: NumericParser | None = None
    ) -> None:
        self._scorer: AnswerScorer = scorer or AnswerScorer()
        self._parser: NumericParser = parser or NumericParser()

    def match(self, expected: float, text: str) -> Comparison | None:
        """Best comparison over every number in the text, or None when the value is absent."""
        comparisons: list[Comparison] = [
            self._scorer.categorise(expected, number) for number in self._parser.parse_all(text)
        ]
        exact: Comparison | None = next((c for c in comparisons if c.category == "match"), None)
        scaled: Comparison | None = next(
            (c for c in comparisons if c.category == "scale_mismatch"), None
        )
        return exact if exact is not None else scaled


class ParseRecall:
    """Stage 0/1 core: is each oracle value present anywhere in the searchable blocks?"""

    def __init__(self, matcher: ValueMatcher | None = None) -> None:
        self._matcher: ValueMatcher = matcher or ValueMatcher()
        self._parser: NumericParser = NumericParser()

    def evaluate(
        self, oracle: Sequence[OracleValue], blocks: Sequence[SearchableBlock]
    ) -> list[QuestionRecall]:
        """One recall verdict per oracle value, in oracle order."""
        return [self._recall(value, blocks) for value in oracle]

    @staticmethod
    def summary(results: Sequence[QuestionRecall]) -> dict[str, int]:
        """Population, exact, scale, miss and reachable (exact + scale) counts."""
        counts: Counter[str] = Counter(result.status for result in results)
        return {
            "population": len(results),
            "exact": counts["exact"],
            "scale": counts["scale"],
            "miss": counts["miss"],
            "reachable": counts["exact"] + counts["scale"],
        }

    @staticmethod
    def vlm_only(text_only: Sequence[QuestionRecall], full: Sequence[QuestionRecall]) -> list[str]:
        """Questions reachable only once picture descriptions are searchable."""
        missed: set[str] = {result.question for result in text_only if result.status == "miss"}
        return [r.question for r in full if r.status != "miss" and r.question in missed]

    def _recall(self, value: OracleValue, blocks: Sequence[SearchableBlock]) -> QuestionRecall:
        expected: float | None = self._parser.parse(value.expected)
        hits: list[ValueHit] = [] if expected is None else self._hits(expected, blocks)
        return QuestionRecall(value.question, value.expected, self._status(hits), hits)

    def _hits(self, expected: float, blocks: Sequence[SearchableBlock]) -> list[ValueHit]:
        hits: list[ValueHit] = []
        for block in blocks:
            comparison: Comparison | None = self._matcher.match(expected, block.text)
            if comparison is not None:
                hits.append(self._hit(block, comparison))
        return hits

    @staticmethod
    def _hit(block: SearchableBlock, comparison: Comparison) -> ValueHit:
        return ValueHit(
            hit_kind=_HIT_KIND[comparison.category],
            number=comparison.actual_number or 0.0,
            scale=comparison.scale,
            source=block.source,
            page_no=block.page_no,
            block_kind=block.kind,
            heading_path=block.heading_path,
        )

    @staticmethod
    def _status(hits: Sequence[ValueHit]) -> RecallStatus:
        kinds: set[str] = {hit.hit_kind for hit in hits}
        if "exact" in kinds:
            return "exact"
        return "scale" if "scale" in kinds else "miss"


class RetrievalRecall:
    """Stage 2 core: did retrieval surface the value, and if not, which stage lost it?"""

    def __init__(self, matcher: ValueMatcher | None = None) -> None:
        self._matcher: ValueMatcher = matcher or ValueMatcher()
        self._parser: NumericParser = NumericParser()

    def classify(
        self,
        oracle: OracleValue,
        passages: Sequence[RetrievedPassage],
        extractable: bool,
        expected_pages: Sequence[int],
    ) -> RetrievalOutcome:
        """hit when a passage carries the value; otherwise attribute the miss."""
        expected: float | None = self._parser.parse(oracle.expected)
        found: bool = expected is not None and any(
            self._matcher.match(expected, passage.text) is not None for passage in passages
        )
        retrieved_pages: list[int] = sorted({passage.page_no for passage in passages})
        return RetrievalOutcome(
            question=oracle.question,
            expected=oracle.expected,
            status=self._status(found, extractable),
            page_hit=bool(set(retrieved_pages) & set(expected_pages)),
            retrieved_pages=retrieved_pages,
            expected_pages=list(expected_pages),
        )

    @staticmethod
    def summary(outcomes: Sequence[RetrievalOutcome]) -> dict[str, float | int]:
        """Status counts plus page hit-rate over questions that have recorded pages."""
        counts: Counter[str] = Counter(outcome.status for outcome in outcomes)
        judged: list[RetrievalOutcome] = [o for o in outcomes if o.expected_pages]
        rate: float = sum(o.page_hit for o in judged) / len(judged) if judged else 0.0
        return {
            "population": len(outcomes),
            "hit": counts["hit"],
            "not_retrieved": counts["not_retrieved"],
            "not_extractable": counts["not_extractable"],
            "page_hit_rate": rate,
        }

    @staticmethod
    def _status(found: bool, extractable: bool) -> RetrievalStatus:
        if found:
            return "hit"
        return "not_retrieved" if extractable else "not_extractable"
