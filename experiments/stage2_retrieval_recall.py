"""Stage 2 — retrieval recall@k: does any retrieved node carry the oracle value?

Each miss is attributed using stage 0/1 output: ``not_extractable`` (never in the
corpus, an extractor problem) versus ``not_retrieved`` (present, retrieval failed
to surface it). Page hit-rate uses the pages stage 0 recorded. Costs OpenAI calls
(query expansion, HyDE, rerank) and needs an index built with the same extractor.

Usage:
    uv run python experiments/stage2_retrieval_recall.py --company acme --year 2025 \
        --extractor liteparse --stage0 results/funnel/stage0_liteparse.json \
        [--stage1 results/funnel/stage1_liteparse.json] [--out-dir results/funnel]
"""

import argparse
import asyncio
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from funnel_common import load_oracle, stage_payload, summary_table, write_json
from rich.console import Console

from peerdex.funnel import (
    OracleValue,
    RetrievalOutcome,
    RetrievalRecall,
    RetrievedPassage,
    StageDocument,
)
from peerdex.retrieve import PassageRetriever
from peerdex.shared.settings import get_settings


class Stage2Runner:
    """Retrieve each oracle question and attribute every miss to its stage."""

    def __init__(
        self,
        company: str,
        year: int,
        extractor: str,
        stage_docs: Sequence[StageDocument],
        out_dir: Path,
    ) -> None:
        self._company: str = company
        self._year: int = year
        self._extractor: str = extractor
        self._stage_docs: list[StageDocument] = list(stage_docs)
        self._out_dir: Path = out_dir

    async def run(self) -> dict[str, Any]:
        """Classify all oracle questions and write stage2_<extractor>.json."""
        oracle: list[OracleValue] = load_oracle(self._company, self._year)
        retriever = PassageRetriever(
            company=self._company,
            attributes={"year": self._year, "extractor": self._extractor},
        )
        outcomes: list[RetrievalOutcome] = [await self._outcome(retriever, v) for v in oracle]
        summary: dict[str, Any] = {
            **RetrievalRecall.summary(outcomes),
            "k": get_settings().retrieval.final_top_k,
        }
        write_json(
            self._out_dir / f"stage2_{self._extractor}.json",
            stage_payload(
                stage=2,
                extractor=self._extractor,
                company=self._company,
                year=self._year,
                summary=summary,
                questions=[asdict(outcome) for outcome in outcomes],
            ),
        )
        return summary

    async def _outcome(self, retriever: PassageRetriever, value: OracleValue) -> RetrievalOutcome:
        result = await retriever.retrieve(value.question)
        passages: list[RetrievedPassage] = [
            RetrievedPassage(
                text=node.node.get_content(),
                page_no=int(node.node.metadata.get("page_no", 0) or 0),
            )
            for node in result.nodes
        ]
        return RetrievalRecall().classify(
            value,
            passages,
            extractable=self._extractable(value.question),
            expected_pages=self._pages(value.question),
        )

    def _extractable(self, question: str) -> bool:
        return any(question in doc.reachable_questions() for doc in self._stage_docs)

    def _pages(self, question: str) -> list[int]:
        return sorted({page for doc in self._stage_docs for page in doc.pages_for(question)})


def _load_stage(path: Path | None) -> list[StageDocument]:
    return [] if path is None else [StageDocument(json.loads(path.read_text()))]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 2: retrieval recall with attribution.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--extractor", required=True)
    parser.add_argument("--stage0", required=True, type=Path)
    parser.add_argument("--stage1", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("results/funnel"))
    return parser.parse_args()


def main() -> None:
    """Run stage 2 for one extractor and print the attributed summary."""
    args: argparse.Namespace = _parse_args()
    runner = Stage2Runner(
        args.company,
        args.year,
        args.extractor,
        [*_load_stage(args.stage0), *_load_stage(args.stage1)],
        args.out_dir,
    )
    summary: dict[str, Any] = asyncio.run(runner.run())
    Console().print(
        summary_table(
            f"stage 2 — retrieval recall ({args.extractor})",
            ["hit", "not_retrieved", "not_extractable", "page hit-rate", "of"],
            [
                [
                    str(summary["hit"]),
                    str(summary["not_retrieved"]),
                    str(summary["not_extractable"]),
                    f"{summary['page_hit_rate']:.2f}",
                    str(summary["population"]),
                ]
            ],
        )
    )


if __name__ == "__main__":
    main()
