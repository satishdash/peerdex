"""peerdex CLI: `index` ingests a PDF, `ask` answers one question against a domain."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from shared.key_value_parser import KeyValueParser
from shared.logging import Logging
from shared.metadata import Scalar, Scalars
from shared.scalar_set_value_parser import ScalarSetValueParser
from shared.scalar_value_parser import ScalarValueParser
from shared.value_parser import ValueParser

if TYPE_CHECKING:
    from ask import Answer

app = typer.Typer(help="peerdex - peer-doc agentic RAG", no_args_is_help=True)
console = Console()


@app.callback()
def _root() -> None:
    Logging.configure()


def _parse_kv[T](pairs: list[str] | None, values: ValueParser[T]) -> dict[str, T]:
    """Parse repeatable KEY=VALUE options.

    Args:
        pairs: The raw options, or None when none were given.
        values: Types the value side of each pair.

    Returns:
        The parsed pairs.

    Raises:
        BadParameter: If a pair is malformed or a key is repeated.
    """
    try:
        return KeyValueParser(values).parse(pairs or [])
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def index(
    pdf: Annotated[Path, typer.Argument(exists=True, readable=True)],
    company: Annotated[str, typer.Option("--company", "-c")],
    domain: Annotated[
        str, typer.Option("--domain", "-d", help="document domain; one table and prompt set each")
    ],
    year: Annotated[int, typer.Option("--year", "-y", help="reporting year")],
    extractor: Annotated[
        str, typer.Option("--extractor", "-e", help="PDF extractor backend (docling, ...)")
    ],
    meta: Annotated[
        list[str] | None,
        typer.Option("--meta", "-m", help="KEY=VALUE attribute, repeatable"),
    ] = None,
) -> None:
    """Extract -> chunk -> embed+store one PDF, or every PDF in a directory.

    Raises:
        BadParameter: If an attribute is malformed, or the directory holds no PDF.
    """
    from index import Ingest

    attributes: dict[str, Scalar] = _parse_kv(meta, ScalarValueParser())
    ingest = Ingest.directory if pdf.is_dir() else Ingest.document
    try:
        result = asyncio.run(
            ingest(
                pdf,
                company=company,
                domain=domain,
                year=year,
                extractor=extractor,
                attributes=attributes,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(Panel.fit(json.dumps(result, indent=2), title="index"))


@app.command()
def ask(
    question: Annotated[str, typer.Argument()],
    company: Annotated[str, typer.Option("--company", "-c")],
    domain: Annotated[
        str, typer.Option("--domain", "-d", help="document domain; one table and prompt set each")
    ],
    kind: Annotated[
        str, typer.Option("--kind", "-k", help="quantitative returns a value, qualitative prose")
    ] = "quantitative",
    filters: Annotated[
        list[str] | None,
        typer.Option("--filter", "-f", help="KEY=VALUE filter, repeatable; KEY=a,b matches either"),
    ] = None,
) -> None:
    """Route -> find -> read -> resolve. Two attempts at most, no agent, no loop.

    Raises:
        BadParameter: If a filter is malformed, or the kind is not one the router knows.
    """
    from ask import AnswerKind, AskPipeline, Question

    try:
        asked = AnswerKind(kind)
    except ValueError as exc:
        raise typer.BadParameter(f"kind must be one of {[k.value for k in AnswerKind]}") from exc

    admitted: dict[str, Scalars] = _parse_kv(filters, ScalarSetValueParser())
    answer = asyncio.run(
        AskPipeline.ask(
            Question(text=question, kind=asked, company=company, domain=domain, filters=admitted)
        )
    )
    console.print(Panel.fit(_rendered(answer), title=f"{answer.kind.value} ({answer.attempts})"))
    if answer.citations:
        console.print(_cited(answer))


def _rendered(answer: Answer) -> str:
    """One answer as the terminal shows it.

    Args:
        answer: What the pipeline returned.

    Returns:
        The value alone, the prose, or the refusal and its reason.
    """
    if answer.refused:
        return f"[red]REFUSED[/red] - {answer.reason}"
    return answer.text or f"{answer.value} {answer.unit}".strip()


def _cited(answer: Answer) -> Table:
    """The chunks the answer traces back to.

    Args:
        answer: What the pipeline returned.

    Returns:
        A table of one row per citation.
    """
    table = Table(title="citations")
    for column in ("chunk", "company", "year", "page", "heading"):
        table.add_column(column)
    for cited in answer.citations:
        table.add_row(
            cited.chunk_id,
            cited.company,
            str(cited.year),
            str(cited.page_no),
            cited.heading_path[:60],
        )
    return table
