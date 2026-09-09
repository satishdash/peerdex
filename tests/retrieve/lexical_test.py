"""Retrieval is one filtered full-text query, so the filter must reach the database."""

from typing import Any

from pytest_mock import MockerFixture

from peerdex.retrieve import LexicalRetriever

ROW: dict[str, Any] = {
    "id": "d1:c7",
    "text": "| Scope 1 - Total | 62,587 |",
    "metadata": {"page_no": 4, "company": "acme"},
    "_score": 9.5,
}


def _table(mocker: MockerFixture, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
    search = mocker.MagicMock()
    search.where.return_value = search
    search.limit.return_value = search
    search.to_list.return_value = rows
    tbl = mocker.MagicMock()
    tbl.search.return_value = search
    mocker.patch("peerdex.retrieve._retriever.table", return_value=tbl)
    return tbl, search


async def test_given_filters_when_retrieving_then_predicate_is_pushed_to_lancedb(
    mocker: MockerFixture,
) -> None:
    """Narrowing in the database is the point; filtering in Python would reload the corpus."""
    tbl, search = _table(mocker, [ROW])

    result = await LexicalRetriever(company="Acme", attributes={"year": 2025}).retrieve("scope 1")

    tbl.search.assert_called_once_with("scope 1", query_type="fts")
    search.where.assert_called_once_with("metadata.company = 'acme' AND metadata.year = 2025")
    assert len(result.nodes) == 1
    assert result.refused is False


async def test_given_a_row_when_retrieving_then_id_page_and_score_survive(
    mocker: MockerFixture,
) -> None:
    """A passage must stay traceable to its chunk and page, and keep its rank."""
    _table(mocker, [ROW])

    result = await LexicalRetriever(company="acme").retrieve("scope 1")
    node = result.nodes[0]

    assert node.node.node_id == "d1:c7"
    assert node.node.metadata["page_no"] == 4
    assert node.score == 9.5
    assert "62,587" in node.node.get_content()


async def test_given_no_matches_when_retrieving_then_it_refuses(mocker: MockerFixture) -> None:
    """Nothing found must be a refusal the caller can see, not an empty answer."""
    _table(mocker, [])

    result = await LexicalRetriever(company="acme").retrieve("nothing matches this")

    assert result.nodes == []
    assert result.refused is True
    assert result.reason == "no_full_text_matches"
