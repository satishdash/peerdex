"""Dense tables must chunk into row groups that each stay answerable on their own."""

import pytest
import tiktoken
from llama_index.core.schema import TextNode

from chunk import HierarchicalChunker
from parse import ExtractedDoc, PageInfo, TableBlock
from shared.document_metadata import DocumentMetadata
from shared.settings import get_settings

_ENC = tiktoken.get_encoding("cl100k_base")

YEARS: list[str] = ["2015", "2023", "2024", "2025"]
METRICS: list[str] = [f"Scope 1 - site {n} energy consumption" for n in range(40)]
WIDE: int = 2000


def _doc(headers: list[str], rows: list[list[str]]) -> ExtractedDoc:
    return ExtractedDoc(
        blocks=[
            TableBlock(
                kind="table",
                headers=headers,
                rows=rows,
                caption="GHG emissions",
                page_no=4,
                heading_path=["Climate"],
            )
        ],
        pages=[PageInfo(page_no=4, width=612.0, height=792.0)],
        source_meta={},
    )


async def _nodes(
    headers: list[str], rows: list[list[str]]
) -> tuple[list[TextNode], list[TextNode]]:
    meta = DocumentMetadata(
        company="acme", year=2025, source_uri="/docs/a.pdf", extractor="docling"
    )
    return await HierarchicalChunker().chunk(_doc(headers, rows), doc_id="d1", metadata=meta)


async def _children(headers: list[str], rows: list[list[str]]) -> list[TextNode]:
    _, children = await _nodes(headers, rows)
    return children


async def test_given_table_over_budget_when_chunked_then_row_groups_fit_and_repeat_header() -> None:
    """One vector per giant table averages every metric; row groups keep each metric findable."""
    rows = [[m, "1", "2", "3", "4"] for m in METRICS]
    budget: int = get_settings().chunker.child_chunk_tokens

    children = await _children(["metric", *YEARS], rows)

    assert len(children) > 1
    assert all(len(_ENC.encode(c.text)) <= budget for c in children)
    assert all("| metric | 2015 | 2023 | 2024 | 2025 |" in c.text for c in children)
    assert sum(c.text.count("Scope 1 - site ") for c in children) == len(METRICS)


async def test_given_positional_headers_when_chunked_then_first_row_carries_the_columns() -> None:
    """Docling emits 0..n headers, so the real column names live in the first row."""
    rows = [["metric", *YEARS], *[[m, "1", "2", "3", "4"] for m in METRICS]]

    children = await _children(["0", "1", "2", "3", "4"], rows)

    assert len(children) > 1
    assert all("| metric | 2015 | 2023 | 2024 | 2025 |" in c.text for c in children)


async def test_given_small_table_when_chunked_then_one_child_only() -> None:
    """A table already inside the budget must not be split."""
    children = await _children(["metric", *YEARS], [["Scope 1 - Total", "1", "2", "3", "62587"]])

    assert len(children) == 1
    assert "62587" in children[0].text


@pytest.mark.parametrize(
    ("headers", "lead", "table"),
    [
        (["metric", "2025", *[""] * WIDE], [], "| metric | 2025 |\n| --- | --- |\n"),
        (
            [str(n) for n in range(WIDE + 2)],
            [["metric", "2025"]],
            "| 0 | 1 |\n| --- | --- |\n| metric | 2025 |\n",
        ),
    ],
    ids=["named", "positional"],
)
async def test_given_trailing_empty_columns_when_chunked_then_only_filled_columns_render(
    headers: list[str], lead: list[list[str]], table: str
) -> None:
    """A sheet whose used range spans every column must not pad each chunk with empty cells."""
    rows = [*lead, ["Scope 1 - Total", "62587", *[""] * WIDE], ["Scope 2", "1200"]]
    body: str = "| Scope 1 - Total | 62587 |\n| Scope 2 | 1200 |"

    parents, children = await _nodes(headers, rows)

    assert len(parents) == 1
    assert f"{table}{body}" in parents[0].text
    assert "|   |" not in parents[0].text
    assert len(children) == 1
    assert body in children[0].text
    assert "|   |" not in children[0].text
    assert len(_ENC.encode(children[0].text)) <= get_settings().chunker.child_chunk_tokens


async def test_given_cells_merged_across_the_row_when_chunked_then_each_text_renders_once() -> None:
    """A merged cell repeats its text in every column it spans; one copy says it all."""
    note: str = "1 Totals may not add up due to rounding."
    rows = [[note] * (WIDE + 1), ["2 Restated.", *[""] * WIDE]]
    table: str = f"| {note} |\n| --- |\n| {note} |\n| 2 Restated. |"

    parents, children = await _nodes([note, *[""] * WIDE], rows)

    assert len(parents) == 1
    assert table in parents[0].text
    assert parents[0].text.count(note) == 2
    assert len(children) == 1
    assert table in children[0].text
    assert len(_ENC.encode(children[0].text)) <= get_settings().chunker.child_chunk_tokens
