"""peerdex CLI: `index` (ingest a PDF), `ask` (one query), `suite` (canned QA)."""

import asyncio
import json
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from peerdex.shared.logging import configure_logging
from peerdex.shared.schema import ReportType

app = typer.Typer(help="peerdex - peer-doc agentic RAG", no_args_is_help=True)
console = Console()
REPORT_TYPES = [t.value for t in ReportType]


@app.callback()
def _root() -> None:
    configure_logging()


def _validate_type(t: str) -> ReportType:
    try:
        return ReportType(t)
    except ValueError:
        raise typer.BadParameter(f"--type must be one of {REPORT_TYPES}")


@app.command()
def index(
    pdf: Path = typer.Argument(..., exists=True, readable=True),
    company: str = typer.Option(..., "--company", "-c"),
    year: int = typer.Option(..., "--year", "-y"),
    report_type: str = typer.Option(..., "--type", "-t"),
    extractor: str = typer.Option("docling", "--extractor", "-e",
                                  help="PDF extractor backend (docling, ...)"),
) -> None:
    """Extract -> chunk -> embed+store the given PDF."""
    rt = _validate_type(report_type)
    from peerdex.index import index_doc
    result = asyncio.run(index_doc(str(pdf), company=company, year=year,
                                   report_type=rt, extractor=extractor))
    console.print(Panel.fit(json.dumps(result, indent=2), title="index"))


@app.command()
def ask(
    q: str = typer.Argument(...),
    company: str = typer.Option(..., "--company", "-c"),
    year: int = typer.Option(..., "--year", "-y"),
    report_type: str = typer.Option(None, "--type", "-t",
                                     help=f"Filter to report type ({REPORT_TYPES}). Omit to search all."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="final passages after rerank"),
    no_synth: bool = typer.Option(False, "--no-synth", help="show retrieval only"),
) -> None:
    """Hybrid retrieval (dense + BM25 RRF + HyDE + LLM rerank) → cited answer."""
    rt = _validate_type(report_type) if report_type else None
    asyncio.run(_run_one(q, company=company, year=year, report_type=rt,
                         top_k=top_k, no_synth=no_synth))


async def _run_one(
    q: str,
    *,
    company: str,
    year: int,
    report_type: ReportType | None = None,
    top_k: int,
    no_synth: bool,
) -> None:
    """Run a single question through retrieve+synth and pretty-print.

    Extracted so `suite` can iterate without re-implementing the table/
    panel rendering. Pure side-effect (writes to console).
    """
    from peerdex.retrieve import retrieve as do_retrieve
    from peerdex.synthesize import synthesize as do_synth

    result = await do_retrieve(q, company=company, year=year, report_type=report_type)

    # Trim to requested top_k for display (retrieval already capped by config).
    nodes = result.nodes[:top_k]

    # ---- retrieval table ----
    if not nodes:
        console.print(
            Panel.fit(
                f"[red]REFUSED[/red] — {result.reason or 'no passages survived rerank'}",
                title="ask",
            )
        )
        return

    t = Table(title=f"retrieved (kept {len(nodes)} of {len(result.nodes)})")
    for col in ("score", "company", "year", "page", "heading", "kind", "preview"):
        t.add_column(col)
    for h in nodes:
        m = h.metadata or {}
        kind = "table" if m.get("is_table") else ("figure" if m.get("is_figure") else "prose")
        head = (m.get("heading_path") or "root")
        preview = (h.text or "").replace("\n", " ")[:80]
        t.add_row(
            f"{h.score:.3f}" if h.score is not None else "-",
            str(m.get("company", "")),
            str(m.get("year", "")),
            str(m.get("page_no", "")),
            head[:60],
            kind,
            preview,
        )
    console.print(t)

    if no_synth:
        return

    # ---- synthesis ----
    answer = await do_synth(q, nodes, report_type=result.report_type)
    if answer.refused:
        console.print(
            Panel.fit(f"[red]REFUSED[/red] — {answer.reason}", title="answer")
        )
        return
    console.print(Panel(answer.answer, title="answer"))

    ct = Table(title="citations")
    for col in ("#", "company", "year", "page", "heading", "quote"):
        ct.add_column(col)
    for c in answer.citations:
        ct.add_row(
            f"[{c.n}]",
            c.company, str(c.year), str(c.page),
            (c.heading or "")[:60],
            (c.quote or "")[:100],
        )
    console.print(ct)


def _suites_path() -> Path:
    """Resolve config/suites.yaml relative to the project root (where config.yaml lives)."""
    from peerdex.shared.settings import CONFIG_PATH
    return CONFIG_PATH.parent / "suites.yaml"


@app.command()
def suite(
    name: str = typer.Argument(..., help="suite key in config/suites.yaml"),
    company: str = typer.Option(..., "--company", "-c"),
    year: int = typer.Option(..., "--year", "-y"),
    report_type: str = typer.Option(None, "--type", "-t",
                                     help=f"Filter to report type ({REPORT_TYPES}). Omit to search all."),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    no_synth: bool = typer.Option(False, "--no-synth"),
) -> None:
    """Run every question in a named suite end-to-end.

    Suites live in config/suites.yaml. Each suite declares a
    `questions:` list. Questions are looped through `_run_one`,
    separated by a rule. Designed for `make suite NAME` smoke tests
    and for the future deepeval harness to iterate.
    """
    rt = _validate_type(report_type) if report_type else None
    p = _suites_path()
    if not p.exists():
        raise typer.BadParameter(f"{p} not found (run from repo root).")
    cfg = yaml.safe_load(p.read_text()) or {}
    suites = cfg.get("suites") or {}
    if name not in suites:
        raise typer.BadParameter(
            f"unknown suite '{name}'. available: {sorted(suites)}"
        )
    block = suites[name]
    qs = block.get("questions") or []
    if not qs:
        raise typer.BadParameter(f"suite '{name}' has no questions.")

    console.print(Panel.fit(
        f"suite=[b]{name}[/b]  company=[b]{company}[/b]  year=[b]{year}[/b]  n={len(qs)}",
        title="run",
    ))

    async def _run_all() -> None:
        for i, entry in enumerate(qs, 1):
            q = entry["q"] if isinstance(entry, dict) else entry
            console.print(Rule(f"[{i}/{len(qs)}] {q}"))
            await _run_one(q, company=company, year=year, report_type=rt,
                           top_k=top_k, no_synth=no_synth)

    asyncio.run(_run_all())


if __name__ == "__main__":
    app()
