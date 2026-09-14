"""Benchmark extractors across one or many PDFs.

Usage:
    uv run python experiments/test_extractor_benchmark.py ~/Documents/reports
    uv run python experiments/test_extractor_benchmark.py a.pdf b.pdf --extractors liteparse
    uv run python experiments/test_extractor_benchmark.py ~/Documents/reports --out bench.json

Results are appended to the JSON file after every document so a long run
survives an interrupt. Failures are recorded, never fatal.
"""

import argparse
import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table

from parse import ExtractedDoc, Extractor

console = Console()

_BLOCK_KINDS: tuple[str, ...] = ("heading", "paragraph", "table", "list", "picture")


@dataclass
class DocumentRun:
    """One extractor's outcome on one document."""

    extractor: str
    version: str
    document: str
    size_mb: float
    elapsed_s: float = 0.0
    pages: int = 0
    blocks: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    table_cells: int = 0
    text_chars: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


class BenchmarkRunner:
    """Runs each extractor over each document and accumulates the runs."""

    def __init__(self, extractors: list[str], out_path: Path) -> None:
        self._extractors: list[str] = extractors
        self._out_path: Path = out_path
        self._runs: list[DocumentRun] = []

    def run(self, documents: list[Path]) -> list[DocumentRun]:
        """Benchmark every extractor on every document, persisting as it goes."""
        for document in documents:
            for name in self._extractors:
                self._runs.append(self._one(name, document))
                self._persist()
        return self._runs

    def _one(self, name: str, document: Path) -> DocumentRun:
        from parse import ExtractorRegistry

        size_mb: float = document.stat().st_size / 1_048_576
        console.print(f"[cyan]{name}[/cyan] -> {document.name} ({size_mb:.1f} MB)")
        try:
            extractor = ExtractorRegistry.create(name)
        except Exception as exc:
            return DocumentRun(name, "?", document.name, size_mb, error=repr(exc))

        started: float = time.perf_counter()
        try:
            doc: ExtractedDoc = _extract(extractor, document)
        except Exception as exc:
            elapsed: float = time.perf_counter() - started
            console.print(f"  [red]FAILED after {_fmt_time(elapsed)}: {exc}[/red]")
            return DocumentRun(
                name, extractor.version, document.name, size_mb, elapsed, error=repr(exc)
            )

        run: DocumentRun = _summarise(name, extractor.version, document.name, size_mb, doc)
        run.elapsed_s = time.perf_counter() - started
        console.print(
            f"  {_fmt_time(run.elapsed_s)}  pages={run.pages} blocks={run.blocks} "
            f"tables={run.counts['table']} pictures={run.counts['picture']}"
        )
        return run

    def _persist(self) -> None:
        self._out_path.write_text(json.dumps([asdict(r) for r in self._runs], indent=2))


def _extract(extractor: Extractor, document: Path) -> ExtractedDoc:
    """The same entry point production uses, so a benchmark stays comparable."""
    return asyncio.run(extractor.extract_async(document))


def _summarise(
    name: str, version: str, document: str, size_mb: float, doc: ExtractedDoc
) -> DocumentRun:
    counts: dict[str, int] = dict.fromkeys(_BLOCK_KINDS, 0)
    table_cells: int = 0
    text_chars: int = 0
    for block in doc.blocks:
        counts[block.kind] = counts.get(block.kind, 0) + 1
        text_chars += len(getattr(block, "text", "") or "")
        table_cells += sum(len(row) for row in getattr(block, "rows", []) or [])
    return DocumentRun(
        extractor=name,
        version=version,
        document=document,
        size_mb=size_mb,
        pages=len(doc.pages),
        blocks=len(doc.blocks),
        counts=counts,
        table_cells=table_cells,
        text_chars=text_chars,
    )


def _fmt_time(seconds: float) -> str:
    if seconds >= 60:
        return f"{int(seconds // 60)}m {int(seconds % 60):02d}s"
    return f"{seconds:.1f}s"


def _documents(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        resolved: Path = path.expanduser().resolve()
        found.extend(sorted(resolved.glob("*.pdf")) if resolved.is_dir() else [resolved])
    missing: list[Path] = [p for p in found if not p.exists()]
    if missing:
        raise SystemExit(f"not found: {', '.join(str(p) for p in missing)}")
    return found


_ROWS: tuple[tuple[str, Callable[[list[DocumentRun]], str]], ...] = (
    ("Documents parsed", lambda rs: str(sum(1 for r in rs if r.ok))),
    ("Failures", lambda rs: str(sum(1 for r in rs if not r.ok))),
    ("Wall time", lambda rs: _fmt_time(sum(r.elapsed_s for r in rs))),
    ("Pages", lambda rs: str(sum(r.pages for r in rs))),
    ("Blocks", lambda rs: str(sum(r.blocks for r in rs))),
    ("Headings", lambda rs: str(sum(r.counts.get("heading", 0) for r in rs))),
    ("Paragraphs", lambda rs: str(sum(r.counts.get("paragraph", 0) for r in rs))),
    ("Tables", lambda rs: str(sum(r.counts.get("table", 0) for r in rs))),
    ("Table cells", lambda rs: str(sum(r.table_cells for r in rs))),
    ("Lists", lambda rs: str(sum(r.counts.get("list", 0) for r in rs))),
    ("Pictures", lambda rs: str(sum(r.counts.get("picture", 0) for r in rs))),
    ("Text chars", lambda rs: str(sum(r.text_chars for r in rs))),
)


def _render(runs: list[DocumentRun], extractors: list[str]) -> None:
    table = Table(title="Extraction benchmark (totals across all documents)")
    table.add_column("Metric", style="bold")
    for name in extractors:
        table.add_column(name, justify="right")

    by_extractor: dict[str, list[DocumentRun]] = {
        name: [r for r in runs if r.extractor == name] for name in extractors
    }
    for label, measure in _ROWS:
        table.add_row(label, *[measure(by_extractor[name]) for name in extractors])
    console.print(table)

    for run in (r for r in runs if not r.ok):
        console.print(f"[red]{run.extractor} / {run.document}: {run.error[:160]}[/red]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PDF extractors")
    parser.add_argument("paths", nargs="+", type=Path, help="PDF files or directories")
    parser.add_argument("--extractors", nargs="+", default=None, help="default: all registered")
    parser.add_argument("--out", type=Path, default=Path("bench_extractors.json"))
    args = parser.parse_args()

    from parse import ExtractorRegistry

    extractors: list[str] = args.extractors or ExtractorRegistry.available()
    documents: list[Path] = _documents(args.paths)

    console.rule(f"[bold]{len(extractors)} extractors x {len(documents)} documents")
    runs: list[DocumentRun] = BenchmarkRunner(extractors, args.out).run(documents)
    _render(runs, extractors)
    console.print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
