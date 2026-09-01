"""Funnel report: per extractor, extractable -> +vlm -> retrieved -> answered with drops.

Loads every stage{0..3}_<extractor>.json in a directory and prints one table.

Usage:
    uv run python experiments/funnel_report.py --dir results/funnel
"""

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from peerdex.funnel import FunnelRow, StageDocument

_STAGE_LABELS: tuple[str, ...] = ("extractable", "+vlm", "retrieved", "answered")


class FunnelReport:
    """Reads stage documents from one directory and renders the funnel table."""

    def __init__(self, directory: Path) -> None:
        self._directory: Path = directory

    def rows(self) -> list[FunnelRow]:
        """One row per extractor, stages missing from disk rendered as None."""
        by_extractor: dict[str, dict[int, StageDocument]] = defaultdict(dict)
        for document in self._documents():
            by_extractor[document.extractor][document.stage] = document
        return [
            FunnelRow.build(name, *(self._summary(stages.get(i)) for i in range(4)))
            for name, stages in sorted(by_extractor.items())
        ]

    def population(self) -> int | None:
        """The scoreable population from any stage 0 document."""
        return next(
            (d.summary_value("population") for d in self._documents() if d.stage == 0), None
        )

    def render(self, console: Console) -> None:
        """Print the funnel table; a drop is shown next to each stage after the first."""
        table: Table = Table(title=f"evaluation funnel (population {self.population()})")
        table.add_column("extractor")
        for label in _STAGE_LABELS:
            table.add_column(label, justify="right")
            table.add_column("drop", justify="right", style="dim")
        for row in self.rows():
            table.add_row(row.extractor, *self._cells(row))
        console.print(table)

    def _documents(self) -> list[StageDocument]:
        return [
            StageDocument(json.loads(path.read_text()))
            for path in sorted(self._directory.glob("stage*_*.json"))
        ]

    @staticmethod
    def _summary(document: StageDocument | None) -> Mapping[str, Any] | None:
        return None if document is None else document.summary

    @staticmethod
    def _cells(row: FunnelRow) -> list[str]:
        cells: list[str] = []
        for value, drop in zip(row.stages, row.drops, strict=True):
            cells.append("—" if value is None else str(value))
            cells.append("" if drop is None else f"{drop:+d}")
        return cells


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print the evaluation funnel table.")
    parser.add_argument("--dir", type=Path, default=Path("results/funnel"))
    return parser.parse_args()


def main() -> None:
    """Render the funnel table for every extractor found in the results directory."""
    args: argparse.Namespace = _parse_args()
    FunnelReport(args.dir).render(Console())


if __name__ == "__main__":
    main()
