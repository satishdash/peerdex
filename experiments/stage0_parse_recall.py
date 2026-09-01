"""Stage 0 — parse recall: is each oracle value anywhere in the extracted text or tables?

Free: no API calls. This is the ceiling on every downstream stage; a value absent
here can never be retrieved or answered. Hits record page, block kind and heading
path, which stage 2 uses as page ground truth.

Usage:
    uv run python experiments/stage0_parse_recall.py --company globex --year 2025 \
        [--pdf-dir /abs/dir] [--pdf /abs/file.pdf ...] [--extractors liteparse docling] \
        [--out-dir results/funnel]
"""

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from funnel_common import (
    CorpusBuilder,
    load_oracle,
    pdf_paths,
    stage_payload,
    summary_table,
    write_json,
)
from rich.console import Console

from peerdex.funnel import BlockProjector, OracleValue, ParseRecall, QuestionRecall
from peerdex.parse import available_extractors


class Stage0Runner:
    """Extract each PDF with each extractor and measure oracle-value recall."""

    def __init__(
        self,
        company: str,
        year: int,
        extractors: Sequence[str],
        pdfs: Sequence[Path],
        out_dir: Path,
    ) -> None:
        self._company: str = company
        self._year: int = year
        self._extractors: list[str] = list(extractors)
        self._pdfs: list[Path] = list(pdfs)
        self._out_dir: Path = out_dir

    async def run(self) -> list[list[str]]:
        """One summary row per extractor; each stage0_<extractor>.json is written as it goes."""
        oracle: list[OracleValue] = load_oracle(self._company, self._year)
        return [await self._run_extractor(name, oracle) for name in self._extractors]

    async def _run_extractor(self, name: str, oracle: Sequence[OracleValue]) -> list[str]:
        corpus = await CorpusBuilder().build(name, self._pdfs)
        results: list[QuestionRecall] = ParseRecall().evaluate(
            oracle, corpus.text_blocks(BlockProjector())
        )
        summary: dict[str, int] = ParseRecall.summary(results)
        write_json(
            self._out_dir / f"stage0_{name}.json",
            stage_payload(
                stage=0,
                extractor=name,
                company=self._company,
                year=self._year,
                summary=summary,
                questions=[asdict(result) for result in results],
                sources=corpus.sources,
                errors=corpus.errors,
            ),
        )
        errors: str = "; ".join(corpus.errors.values())[:80]
        return [
            name,
            str(summary["exact"]),
            str(summary["scale"]),
            str(summary["miss"]),
            str(summary["population"]),
            errors,
        ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 0: parse recall per extractor.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--pdf-dir", type=Path, default=None)
    parser.add_argument("--pdf", type=Path, nargs="*", default=[])
    parser.add_argument("--extractors", nargs="*", default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("results/funnel"))
    return parser.parse_args()


def main() -> None:
    """Run stage 0 and print the per-extractor recall table."""
    args: argparse.Namespace = _parse_args()
    pdfs: list[Path] = pdf_paths(args.pdf_dir, args.pdf)
    if not pdfs:
        raise SystemExit("no PDFs: pass --pdf-dir and/or --pdf with absolute paths")
    runner = Stage0Runner(
        args.company,
        args.year,
        args.extractors or available_extractors(),
        pdfs,
        args.out_dir,
    )
    rows: list[list[str]] = asyncio.run(runner.run())
    console = Console()
    console.print(f"sources: {[p.name for p in pdfs]}")
    console.print(
        summary_table(
            "stage 0 — parse recall",
            ["extractor", "exact", "scale", "miss", "of", "errors"],
            rows,
        )
    )


if __name__ == "__main__":
    main()
