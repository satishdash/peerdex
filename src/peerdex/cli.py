"""peerdex CLI: `index` (ingest a PDF), `ask` (one query), `suite` (canned QA)."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from peerdex.shared.logging import configure_logging
from peerdex.shared.metadata import (
    KeyValueParser,
    Scalar,
    ScalarSetValueParser,
    ScalarValueParser,
    ValueParser,
)

app = typer.Typer(help="peerdex - peer-doc agentic RAG", no_args_is_help=True)
console = Console()


@app.callback()
def _root() -> None:
    configure_logging()


def _parse_kv[T](pairs: list[str] | None, values: ValueParser[T]) -> dict[str, T]:
    try:
        return KeyValueParser(values).parse(pairs or [])
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def index(
    pdf: Annotated[Path, typer.Argument(exists=True, readable=True)],
    company: Annotated[str, typer.Option("--company", "-c")],
    year: Annotated[int, typer.Option("--year", "-y")],
    extractor: Annotated[
        str, typer.Option("--extractor", "-e", help="PDF extractor backend (docling, ...)")
    ] = "docling",
    meta: Annotated[
        list[str] | None,
        typer.Option("--meta", "-m", help="KEY=VALUE attribute, repeatable"),
    ] = None,
) -> None:
    """Extract -> chunk -> embed+store the given PDF."""
    from peerdex.index import index_doc

    attributes: dict[str, Scalar] = _parse_kv(meta, ScalarValueParser())
    try:
        result = asyncio.run(
            index_doc(
                str(pdf), company=company, year=year, extractor=extractor, attributes=attributes
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(Panel.fit(json.dumps(result, indent=2), title="index"))


@app.command()
def ask(
    q: Annotated[str, typer.Argument()],
    company: Annotated[str, typer.Option("--company", "-c")],
    filters: Annotated[
        list[str] | None,
        typer.Option(
            "--filter",
            "-f",
            help="KEY=VALUE filter, repeatable; KEY=a,b matches either value, \\, escapes a comma",
        ),
    ] = None,
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="citations to display")] = 5,
) -> None:
    """Agentic answer: plan -> retrieve -> answer -> reflect/retry -> emit."""
    asyncio.run(
        _run_one(
            q, company=company, filters=_parse_kv(filters, ScalarSetValueParser()), top_k=top_k
        )
    )


async def _run_one(
    q: str,
    *,
    company: str,
    filters: dict[str, tuple[Scalar, ...]],
    top_k: int,
) -> None:
    """Run one question through the agent and pretty-print the result."""
    from peerdex.agent import answer as agent_answer

    result = await agent_answer(q, company=company, filters=filters)

    at = Table(title="attempts")
    for col in ("#", "query", "passages"):
        at.add_column(col)
    for i, attempt in enumerate(result.attempts, 1):
        at.add_row(str(i), attempt.query[:80], str(attempt.passages))
    console.print(at)

    if result.refused:
        console.print(Panel.fit(f"[red]REFUSED[/red] — {result.reason}", title="answer"))
        return

    body = result.text if result.kind == "qualitative" else f"{result.value} {result.unit}".strip()
    console.print(Panel(body, title=f"answer ({result.kind})"))

    ct = Table(title="citations")
    for col in ("#", "company", "year", "page", "heading", "quote"):
        ct.add_column(col)
    for c in result.citations[:top_k]:
        ct.add_row(
            f"[{c.n}]",
            c.company,
            str(c.year),
            str(c.page),
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
    name: Annotated[str, typer.Argument(help="suite key in config/suites.yaml")],
    company: Annotated[str, typer.Option("--company", "-c")],
    filters: Annotated[
        list[str] | None,
        typer.Option(
            "--filter",
            "-f",
            help="KEY=VALUE filter, repeatable; KEY=a,b matches either value, \\, escapes a comma",
        ),
    ] = None,
    top_k: Annotated[int, typer.Option("--top-k", "-k")] = 5,
) -> None:
    """Run every question in a named suite through the agent."""
    p = _suites_path()
    if not p.exists():
        raise typer.BadParameter(f"{p} not found (run from repo root).")
    cfg = yaml.safe_load(p.read_text()) or {}
    suites = cfg.get("suites") or {}
    if name not in suites:
        raise typer.BadParameter(f"unknown suite '{name}'. available: {sorted(suites)}")
    block = suites[name]
    qs = block.get("questions") or []
    if not qs:
        raise typer.BadParameter(f"suite '{name}' has no questions.")

    parsed_filters: dict[str, tuple[Scalar, ...]] = _parse_kv(filters, ScalarSetValueParser())
    console.print(
        Panel.fit(
            f"suite=[b]{name}[/b]  company=[b]{company}[/b]  "
            f"filters=[b]{parsed_filters}[/b]  n={len(qs)}",
            title="run",
        )
    )

    async def _run_all() -> None:
        for i, entry in enumerate(qs, 1):
            q = entry["q"] if isinstance(entry, dict) else entry
            console.print(Rule(f"[{i}/{len(qs)}] {q}"))
            await _run_one(q, company=company, filters=parsed_filters, top_k=top_k)

    asyncio.run(_run_all())


if __name__ == "__main__":
    app()
