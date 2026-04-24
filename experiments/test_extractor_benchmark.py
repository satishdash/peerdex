"""Benchmark any combination of extractors on any PDF.

Usage:
    # All registered extractors on a PDF:
    uv run python experiments/test_extractor_benchmark.py ~/Documents/suncor_2025.pdf

    # Specific extractors only:
    uv run python experiments/test_extractor_benchmark.py ~/Documents/suncor_2025.pdf --extractors docling liteparse

    # Skip docling warm-cache advantage (force fresh):
    uv run python experiments/test_extractor_benchmark.py ~/Documents/suncor_2025.pdf --cold

Forces fresh docling extraction when --cold is passed (clears LRU converter cache).
Prints a comparison table with block counts, table counts, and wall-clock time.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table


console = Console()


def _run_extractor(name: str, pdf_path: Path) -> dict:
    """Run a single extractor, return stats + wall time."""
    from peerdex.parse import get_extractor

    ext = get_extractor(name)
    t0 = time.perf_counter()
    doc = ext.extract(pdf_path)
    elapsed = time.perf_counter() - t0

    return {
        "name": name,
        "version": ext.version,
        "elapsed_s": elapsed,
        "pages": len(doc.pages),
        "blocks": len(doc.blocks),
        "headings": sum(1 for b in doc.blocks if b.kind == "heading"),
        "paragraphs": sum(1 for b in doc.blocks if b.kind == "paragraph"),
        "tables": sum(1 for b in doc.blocks if b.kind == "table"),
        "lists": sum(1 for b in doc.blocks if b.kind == "list"),
        "pictures": sum(1 for b in doc.blocks if b.kind == "picture"),
    }


def _clear_docling_cache() -> None:
    """Force docling converter re-init (no warm LRU cache)."""
    from peerdex.parse._docling import _converter
    _converter.cache_clear()


def _fmt_time(s: float) -> str:
    if s >= 60:
        return f"{int(s // 60)}m {int(s % 60):02d}s"
    return f"{s:.1f}s"


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PDF extractors")
    parser.add_argument("pdf", type=Path, help="Path to a PDF file")
    parser.add_argument(
        "--extractors", nargs="+", default=None,
        help="Extractor names to benchmark (default: all registered)",
    )
    parser.add_argument(
        "--cold", action="store_true",
        help="Clear docling LRU cache before running (force fresh)",
    )
    args = parser.parse_args()

    pdf: Path = args.pdf.expanduser().resolve()
    if not pdf.exists():
        console.print(f"[red]PDF not found: {pdf}[/red]")
        raise SystemExit(1)

    from peerdex.parse import available_extractors
    names: list[str] = args.extractors or available_extractors()

    console.rule(f"[bold]Extractor Benchmark ({len(names)} extractors)")
    console.print(f"PDF: {pdf}  ({pdf.stat().st_size / 1_048_576:.1f} MB)\n")

    results: list[dict] = []
    for name in names:
        if args.cold and name == "docling":
            _clear_docling_cache()
        console.print(f"[cyan]Running {name}...[/cyan]")
        try:
            r = _run_extractor(name, pdf)
            console.print(f"  done in {_fmt_time(r['elapsed_s'])}\n")
            results.append(r)
        except Exception as e:
            console.print(f"  [red]FAILED: {e}[/red]\n")
            results.append({"name": name, "error": str(e)})

    # ── Results table ──
    ok = [r for r in results if "error" not in r]
    if not ok:
        console.print("[red]All extractors failed.[/red]")
        raise SystemExit(1)

    t = Table(title=f"Extraction Benchmark — {pdf.name}")
    t.add_column("Metric", style="bold")
    for r in ok:
        t.add_column(f"{r['name']} v{r['version']}", justify="right")

    metrics = [
        ("Wall time", "elapsed_s", "t"),
        ("Pages", "pages", "d"),
        ("Total blocks", "blocks", "d"),
        ("Headings", "headings", "d"),
        ("Paragraphs", "paragraphs", "d"),
        ("Tables", "tables", "d"),
        ("Lists", "lists", "d"),
        ("Pictures", "pictures", "d"),
    ]

    for label, key, fmt in metrics:
        row = [label]
        for r in ok:
            v = r[key]
            row.append(_fmt_time(v) if fmt == "t" else str(v))
        t.add_row(*row)

    console.print(t)

    # ── Speed comparison vs slowest ──
    if len(ok) > 1:
        slowest = max(ok, key=lambda r: r["elapsed_s"])
        for r in ok:
            if r is slowest:
                continue
            speedup = slowest["elapsed_s"] / r["elapsed_s"] if r["elapsed_s"] > 0 else 0
            console.print(
                f"  {r['name']}: [bold green]{speedup:.1f}x faster[/bold green] "
                f"than {slowest['name']} "
                f"({_fmt_time(r['elapsed_s'])} vs {_fmt_time(slowest['elapsed_s'])})"
            )


if __name__ == "__main__":
    main()
