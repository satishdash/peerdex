"""Ingest fans out over a directory and always leaves the rows searchable."""

from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from index import Ingest
from shared.settings import resolve_domain


def _stub(mocker: MockerFixture) -> tuple[Any, Any]:
    """The per-document work and the index step, both stubbed out.

    ``_index_table`` must be stubbed or these tests reach the real LanceDB.
    """
    one: Any = mocker.patch(
        "index.ingest.Ingest._one", mocker.AsyncMock(return_value={"doc_id": "x"})
    )
    return one, mocker.patch("index.ingest.TableIndexes.build")


def _pdfs(directory: Path, *stems: str) -> None:
    for stem in stems:
        (directory / f"{stem}.pdf").write_bytes(b"%PDF")


@pytest.mark.parametrize(
    ("stems", "extra", "expected"),
    [
        pytest.param(("c", "a", "b"), None, ["a.pdf", "b.pdf", "c.pdf"], id="sorted"),
        pytest.param(("a",), "notes.txt", ["a.pdf"], id="non-pdfs-skipped"),
    ],
)
async def test_given_a_directory_when_indexed_then_the_right_pdfs_run_in_order(
    mocker: MockerFixture,
    tmp_path: Path,
    stems: tuple[str, ...],
    extra: str | None,
    expected: list[str],
) -> None:
    """Sorted so a run is reproducible; non-PDFs are skipped so a glob cannot parse them."""
    _pdfs(tmp_path, *stems)
    if extra:
        (tmp_path / extra).write_text("x")
    one, _ = _stub(mocker)

    await Ingest.directory(
        tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
    )

    assert [call.args[0].name for call in one.call_args_list] == expected


@pytest.mark.parametrize("entry", ["doc", "dir"])
async def test_given_either_entry_point_when_indexed_then_the_table_is_indexed_once(
    mocker: MockerFixture, tmp_path: Path, entry: str
) -> None:
    """Indexing belongs to ingest. Once per call, not per document: optimising compacts all."""
    _pdfs(tmp_path, "a", "b")
    _, indexed = _stub(mocker)

    if entry == "doc":
        await Ingest.document(
            tmp_path / "a.pdf", company="acme", domain="corporate", year=2025, extractor="docling"
        )
    else:
        await Ingest.directory(
            tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
        )

    indexed.assert_called_once()


async def test_given_an_empty_directory_when_indexed_then_it_fails(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """A silent no-op reads as a successful ingest and is how an empty index ships."""
    _stub(mocker)

    with pytest.raises(ValueError, match="no ingestable documents"):
        await Ingest.directory(
            tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
        )


@pytest.mark.parametrize("bad", ["invoices", "corporat", ""])
async def test_given_an_unconfigured_domain_when_indexed_then_it_fails(
    mocker: MockerFixture, tmp_path: Path, bad: str
) -> None:
    """A domain names a table, so a typo would open an empty one and refuse every answer."""
    _pdfs(tmp_path, "a")
    _stub(mocker)

    with pytest.raises(ValueError, match="unknown domain"):
        await Ingest.directory(tmp_path, company="acme", domain=bad, year=2025, extractor="docling")


@pytest.mark.parametrize("given", ["corporate", "CORPORATE", " Corporate "])
def test_given_a_configured_domain_in_any_case_when_resolved_then_it_is_normalised(
    given: str,
) -> None:
    """Callers type it by hand, so case and stray spaces must not decide the table."""
    assert resolve_domain(given) == "corporate"


def _failing(mocker: MockerFixture, *, bad: str) -> tuple[Any, Any, Any]:
    """Ingest that raises for one named document and succeeds for every other."""

    async def ingest(pdf_path: Any, **_: Any) -> dict[str, Any]:
        if Path(pdf_path).name == bad:
            raise RuntimeError("conversion worker panicked")
        return {"doc_id": Path(pdf_path).stem}

    one: Any = mocker.patch("index.ingest.Ingest._one", side_effect=ingest)
    table: Any = mocker.patch("index.ingest.TableIndexes.build")
    dlq: Any = mocker.patch("index.ingest.DeadLetterQueue.put")
    return one, table, dlq


async def test_given_one_unreadable_document_when_indexing_a_directory_then_the_rest_still_index(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """One document an extractor cannot read must not cost the other fifteen."""
    _pdfs(tmp_path, "a", "b", "c")
    _, table, _ = _failing(mocker, bad="b.pdf")

    results: list[dict[str, Any]] = await Ingest.directory(
        tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
    )

    assert [result.get("failed", False) for result in results] == [False, True, False]
    table.assert_called_once()


async def test_given_an_unreadable_document_when_indexing_then_the_traceback_is_kept(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """An upstream crash is reported as a bug, so it cannot live only in scrollback."""
    _pdfs(tmp_path, "a")
    _, _, dlq = _failing(mocker, bad="a.pdf")

    await Ingest.directory(
        tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
    )

    payload: dict[str, Any] = dlq.call_args.args[2]
    assert dlq.call_args.args[1] == "parse"
    assert "conversion worker panicked" in payload["error"]
    assert "RuntimeError" in payload["traceback"]
    assert payload["source"].endswith("a.pdf")
    assert payload["extractor"] == "docling"


async def test_given_a_single_unreadable_document_when_indexing_then_it_is_recorded_not_raised(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """A one-file run reports the skip the same way a directory run does."""
    _pdfs(tmp_path, "a")
    _failing(mocker, bad="a.pdf")

    result: dict[str, Any] = await Ingest.document(
        tmp_path / "a.pdf", company="acme", domain="corporate", year=2025, extractor="docling"
    )

    assert result["failed"] is True
    assert "conversion worker panicked" in result["error"]


async def test_given_every_document_fails_when_indexing_then_the_table_is_left_alone(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """Indexing a table that was never written would fail on an empty database."""
    _pdfs(tmp_path, "a")
    _, table, _ = _failing(mocker, bad="a.pdf")

    await Ingest.directory(
        tmp_path, company="acme", domain="corporate", year=2025, extractor="docling"
    )

    table.assert_not_called()
