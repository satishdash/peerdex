"""Shared IO-edge helpers for the evaluation funnel runners. No scoring logic lives here."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from conftest import load_qa_cases
from rich.table import Table

from peerdex.funnel import BlockProjector, OracleValue, SearchableBlock
from peerdex.parse import ExtractedDoc, PictureBlock, get_extractor

SUITE_NAME: str = "default"


def load_oracle(company: str, year: int) -> list[OracleValue]:
    """The scoreable population: quantitative default questions with a value."""
    return [
        OracleValue(case.q, case.expected_answer or "")
        for case in load_qa_cases(company=company, year=year, require_answer=True)
        if case.suite == SUITE_NAME and case.kind == "quantitative"
    ]


def pdf_paths(pdf_dir: Path | None, pdfs: Sequence[Path]) -> list[Path]:
    """Explicit PDFs plus every *.pdf in the directory, resolved and de-duplicated."""
    listed: list[Path] = sorted(pdf_dir.glob("*.pdf")) if pdf_dir is not None else []
    unique: dict[Path, None] = {path.resolve(): None for path in [*pdfs, *listed]}
    return list(unique)


@dataclass
class ExtractedCorpus:
    """One extractor's output over the PDFs, keeping per-source failures."""

    extractor: str
    docs: dict[str, ExtractedDoc] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def sources(self) -> list[str]:
        return sorted({*self.docs, *self.errors})

    def text_blocks(self, projector: BlockProjector) -> list[SearchableBlock]:
        """Every text-bearing block across all sources."""
        return [
            block
            for source, doc in self.docs.items()
            for block in projector.project(source, doc.blocks)
        ]

    def pictures(self) -> list[tuple[str, PictureBlock]]:
        """Every PictureBlock with its source, in document order."""
        return [
            (source, block)
            for source, doc in self.docs.items()
            for block in doc.blocks
            if isinstance(block, PictureBlock)
        ]


class CorpusBuilder:
    """Runs one extractor over the PDFs, tolerating per-file failures."""

    async def build(self, extractor: str, pdfs: Sequence[Path]) -> ExtractedCorpus:
        """Extract every PDF; failures are recorded per source instead of aborting."""
        corpus: ExtractedCorpus = ExtractedCorpus(extractor=extractor)
        for pdf in pdfs:
            await self._add(corpus, extractor, pdf)
        return corpus

    async def _add(self, corpus: ExtractedCorpus, extractor: str, pdf: Path) -> None:
        try:
            corpus.docs[pdf.name] = await self._extract(extractor, pdf)
        except Exception as exc:
            corpus.errors[pdf.name] = f"{type(exc).__name__}: {exc}"

    @staticmethod
    async def _extract(extractor: str, pdf: Path) -> ExtractedDoc:
        return await get_extractor(extractor).extract_async(pdf)


def stage_payload(
    *,
    stage: int,
    extractor: str,
    company: str,
    year: int,
    summary: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    """The JSON shape every funnel stage writes, so one reader can load all four."""
    return {
        "stage": stage,
        "extractor": extractor,
        "company": company,
        "year": year,
        "summary": dict(summary),
        "questions": list(questions),
        **extra,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write pretty JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def summary_table(title: str, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> Table:
    """A rich table from column names and string rows."""
    table: Table = Table(title=title)
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    return table
