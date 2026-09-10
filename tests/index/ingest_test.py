"""Ingest fans out over a directory and always leaves the rows searchable."""

from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from peerdex.index._index import index_dir, index_doc
from peerdex.shared.settings import resolve_domain


def _stub(mocker: MockerFixture) -> tuple[Any, Any]:
    """The per-document work and the index step, both stubbed out.

    ``_index_table`` must be stubbed or these tests reach the real LanceDB.
    """
    one: Any = mocker.patch(
        "peerdex.index._index._ingest_one", mocker.AsyncMock(return_value={"doc_id": "x"})
    )
    return one, mocker.patch("peerdex.index._index._index_table")


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

    await index_dir(tmp_path, company="acme", domain="corporate", year=2025)

    assert [call.args[0].name for call in one.call_args_list] == expected


@pytest.mark.parametrize("entry", ["doc", "dir"])
async def test_given_either_entry_point_when_indexed_then_the_table_is_indexed_once(
    mocker: MockerFixture, tmp_path: Path, entry: str
) -> None:
    """Indexing belongs to ingest. Once per call, not per document: optimising compacts all."""
    _pdfs(tmp_path, "a", "b")
    _, indexed = _stub(mocker)

    if entry == "doc":
        await index_doc(tmp_path / "a.pdf", company="acme", domain="corporate", year=2025)
    else:
        await index_dir(tmp_path, company="acme", domain="corporate", year=2025)

    indexed.assert_called_once()


async def test_given_an_empty_directory_when_indexed_then_it_fails(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """A silent no-op reads as a successful ingest and is how an empty index ships."""
    _stub(mocker)

    with pytest.raises(ValueError, match="no PDFs"):
        await index_dir(tmp_path, company="acme", domain="corporate", year=2025)


@pytest.mark.parametrize("bad", ["invoices", "corporat", ""])
async def test_given_an_unconfigured_domain_when_indexed_then_it_fails(
    mocker: MockerFixture, tmp_path: Path, bad: str
) -> None:
    """A domain names a table, so a typo would open an empty one and refuse every answer."""
    _pdfs(tmp_path, "a")
    _stub(mocker)

    with pytest.raises(ValueError, match="unknown domain"):
        await index_dir(tmp_path, company="acme", domain=bad, year=2025)


@pytest.mark.parametrize("given", ["corporate", "CORPORATE", " Corporate "])
def test_given_a_configured_domain_in_any_case_when_resolved_then_it_is_normalised(
    given: str,
) -> None:
    """Callers type it by hand, so case and stray spaces must not decide the table."""
    assert resolve_domain(given) == "corporate"
