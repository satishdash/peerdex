"""Ingesting a directory, where each document states its own reporting year.

A corpus arrives as a directory of PDFs with a sidecar each, and the year differs
per document. Requiring it on the command line makes such a corpus un-ingestable
in one command, and passing one year for all of them would mislabel most.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from peerdex.index._index import _resolved_year, index_dir

def _document(directory: Path, stem: str, year: int | None = None) -> Path:
    """A PDF in ``directory``, with a sidecar when ``year`` is given."""
    pdf: Path = directory / f"{stem}.pdf"
    pdf.write_bytes(b"%PDF")
    if year is not None:
        payload: dict[str, dict[str, Any]] = {f"Acme PLC/{stem}.pdf": {"year": year}}
        (directory / f"{stem}.meta.json").write_text(json.dumps(payload))
    return pdf


def test_given_an_explicit_year_when_resolving_then_it_wins_over_the_sidecar(
    tmp_path: Path,
) -> None:
    """Explicit input beats a file on disk, the same rule attributes already follow."""
    pdf: Path = _document(tmp_path, "a", year=2023)

    assert _resolved_year(pdf, 2025) == 2025


def test_given_no_explicit_year_when_resolving_then_the_sidecar_supplies_it(
    tmp_path: Path,
) -> None:
    """This is what lets one command ingest a directory spanning several years."""
    pdf: Path = _document(tmp_path, "a", year=2023)

    assert _resolved_year(pdf, None) == 2023


def test_given_neither_year_when_resolving_then_it_fails_naming_the_document(
    tmp_path: Path,
) -> None:
    """Mislabelling a document's year silently corrupts every year-filtered answer."""
    pdf: Path = _document(tmp_path, "a")

    with pytest.raises(ValueError, match=r"a\.pdf"):
        _resolved_year(pdf, None)


async def test_given_a_directory_when_indexing_then_every_pdf_is_indexed_in_order(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """Sorted order so a run is reproducible and a partial run is resumable by eye."""
    for stem in ("c", "a", "b"):
        _document(tmp_path, stem, year=2023)
    one: Any = mocker.patch(
        "peerdex.index._index.index_doc", mocker.AsyncMock(return_value={"doc_id": "x"})
    )

    results: list[dict[str, Any]] = await index_dir(tmp_path, company="acme")

    assert [call.args[0].name for call in one.call_args_list] == ["a.pdf", "b.pdf", "c.pdf"]
    assert len(results) == 3


async def test_given_a_directory_of_mixed_files_when_indexing_then_only_pdfs_are_indexed(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """The sidecars sit beside the PDFs, so a naive glob would try to parse them."""
    _document(tmp_path, "a", year=2023)
    (tmp_path / "notes.txt").write_text("x")
    one: Any = mocker.patch(
        "peerdex.index._index.index_doc", mocker.AsyncMock(return_value={"doc_id": "x"})
    )

    await index_dir(tmp_path, company="acme")

    assert [call.args[0].name for call in one.call_args_list] == ["a.pdf"]


async def test_given_a_directory_when_indexing_then_each_documents_own_year_is_used(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """One corpus spans several reporting years; a single year for all would mislabel."""
    _document(tmp_path, "a", year=2023)
    _document(tmp_path, "b", year=2025)
    one: Any = mocker.patch(
        "peerdex.index._index.index_doc", mocker.AsyncMock(return_value={"doc_id": "x"})
    )

    await index_dir(tmp_path, company="acme")

    assert [call.kwargs["year"] for call in one.call_args_list] == [2023, 2025]


async def test_given_an_empty_directory_when_indexing_then_it_fails_rather_than_succeeding(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """A silent no-op reads as a successful ingest and is how an empty index ships."""
    mocker.patch("peerdex.index._index.index_doc", mocker.AsyncMock())

    with pytest.raises(ValueError, match="no PDFs"):
        await index_dir(tmp_path, company="acme")
