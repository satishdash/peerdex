"""Answer-accuracy scorer: runs the agent over default and scores every answer.

Usage:
    uv run python experiments/score_suite.py --company acme --year 2025 \
        --extractor liteparse [--limit N] [--out scores.json]

Quantitative questions go through ``peerdex.agent`` with the suite's ``kind``
and their ``AgentAnswer.value`` is scored by ``peerdex.scoring``; qualitative
questions are emitted as unscored records carrying the answer text.
``extra`` records (oracle empty, answer present) are candidate improvements over
the oracle, never errors.
"""

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from conftest import EvalCase, load_qa_cases
from rich.console import Console
from rich.table import Table

from peerdex.agent import AgentAnswer, QuestionKind
from peerdex.agent import answer as agent_answer
from peerdex.scoring import AnswerScorer, Comparison

SUITE_NAME: str = "default"
_CATEGORIES: tuple[str, ...] = (
    "match",
    "scale_mismatch",
    "mismatch",
    "missed",
    "abstained",
    "extra",
    "unscored",
)


@dataclass(frozen=True)
class QuestionRecord:
    """One scored (or unscored qualitative) question with everything a human needs."""

    question: str
    kind: str
    expected: str
    answer: str
    unit: str
    category: str
    expected_number: float | None
    actual_number: float | None
    scale: float | None


class SuiteScorer:
    """Runs the agent per suite question and scores the answers."""

    def __init__(
        self,
        company: str,
        year: int,
        extractor: str,
        scorer: AnswerScorer,
        limit: int | None = None,
    ) -> None:
        self._company: str = company
        self._year: int = year
        self._extractor: str = extractor
        self._scorer: AnswerScorer = scorer
        self._limit: int | None = limit

    async def run(self) -> list[QuestionRecord]:
        """Score every suite question through the agent."""
        return [await self._record(case) for case in self._cases()]

    def _cases(self) -> list[EvalCase]:
        cases: list[EvalCase] = [
            case
            for case in load_qa_cases(company=self._company, year=self._year)
            if case.suite == SUITE_NAME
        ]
        return cases if self._limit is None else cases[: self._limit]

    async def _record(self, case: EvalCase) -> QuestionRecord:
        kind: QuestionKind = "qualitative" if case.kind == "qualitative" else "quantitative"
        result: AgentAnswer = await agent_answer(
            case.q,
            company=self._company,
            filters={"year": self._year, "extractor": self._extractor},
            kind=kind,
        )
        expected: str = case.expected_answer or ""
        if kind == "qualitative":
            return QuestionRecord(
                case.q, kind, expected, result.text, "", "unscored", None, None, None
            )
        comparison: Comparison = self._scorer.score(expected, result.value, result.unit)
        return QuestionRecord(
            case.q,
            kind,
            expected,
            result.value,
            result.unit,
            comparison.category,
            comparison.expected_number,
            comparison.actual_number,
            comparison.scale,
        )


class ScoreReport:
    """Aggregates question records into a summary, JSON payload and console table."""

    def __init__(self, records: list[QuestionRecord]) -> None:
        self._records: list[QuestionRecord] = records

    def summary(self) -> dict[str, int]:
        counts: Counter[str] = Counter(record.category for record in self._records)
        return {
            "population": len(self._records),
            **{category: counts[category] for category in _CATEGORIES},
        }

    def to_json(self, *, company: str, year: int, extractor: str) -> dict[str, Any]:
        """Stage 3 payload in the same shape as the other funnel stages."""
        return {
            "stage": 3,
            "extractor": extractor,
            "company": company,
            "year": year,
            "summary": self.summary(),
            "questions": [asdict(record) for record in self._records],
        }

    def render(self, console: Console) -> None:
        table: Table = Table(title=f"answer accuracy ({SUITE_NAME})")
        table.add_column("category")
        table.add_column("count", justify="right")
        for category, count in self.summary().items():
            table.add_row(category, str(count))
        console.print(table)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score suite answers against ground truth.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--extractor", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """Run the scorer end to end and write the stage 3 JSON report."""
    args: argparse.Namespace = _parse_args()
    suite_scorer = SuiteScorer(args.company, args.year, args.extractor, AnswerScorer(), args.limit)
    records: list[QuestionRecord] = asyncio.run(suite_scorer.run())
    report = ScoreReport(records)
    payload: dict[str, Any] = report.to_json(
        company=args.company, year=args.year, extractor=args.extractor
    )
    out: Path = args.out or Path("results/funnel") / f"stage3_{args.extractor}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    console = Console()
    report.render(console)
    console.print(f"wrote {out}")


if __name__ == "__main__":
    main()
