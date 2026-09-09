"""Retrieval mode is configuration, and each mode must reach LanceDB correctly."""

from typing import Any

from pytest_mock import MockerFixture

from peerdex.retrieve import PassageRetriever

ROW: dict[str, Any] = {
    "id": "d1:c7",
    "text": "| Scope 1 | Tonnes CO2e | 62,587 |",
    "metadata": {"page_no": 4, "company": "acme"},
    "_score": 9.5,
}

VECTOR: list[float] = [0.1, 0.2, 0.3]


def _table(mocker: MockerFixture) -> tuple[Any, Any]:
    search = mocker.MagicMock()
    search.where.return_value = search
    search.limit.return_value = search
    search.refine_factor.return_value = search
    search.to_list.return_value = [ROW]
    tbl = mocker.MagicMock()
    tbl.search.return_value = search
    mocker.patch("peerdex.retrieve._retriever.table", return_value=tbl)
    return tbl, search


def _embedding(mocker: MockerFixture) -> Any:
    """A stand-in embedding model, so a vector search needs no network."""
    embed = mocker.MagicMock()
    embed.aget_query_embedding = mocker.AsyncMock(return_value=VECTOR)
    return mocker.patch("peerdex.retrieve._retriever.embed_model", return_value=embed)


async def test_given_vector_mode_when_retrieving_then_the_embedded_query_is_searched(
    mocker: MockerFixture,
) -> None:
    """Dense retrieval measured 19/28 against full text's 17/28, so it must be reachable."""
    tbl, search = _table(mocker)
    _embedding(mocker)

    result = await PassageRetriever(company="acme", query_type="vector").retrieve("scope 1")

    tbl.search.assert_called_once_with(VECTOR, query_type="vector")
    search.where.assert_called_once_with("metadata.company = 'acme'")
    assert len(result.nodes) == 1


async def test_given_vector_mode_when_retrieving_then_candidates_are_refined(
    mocker: MockerFixture,
) -> None:
    """Product quantisation costs recall; refining against the exact vectors recovers it.

    Measured: 17/28 indexed without refinement, 19/28 with it, which is the exact
    brute-force baseline. Skipping this silently gives up the whole dense gain.
    """
    _, search = _table(mocker)
    _embedding(mocker)

    await PassageRetriever(company="acme", query_type="vector").retrieve("scope 1")

    search.refine_factor.assert_called_once_with(5)


async def test_given_full_text_mode_when_retrieving_then_it_is_not_refined(
    mocker: MockerFixture,
) -> None:
    """Refinement is a vector-index concept and would be meaningless on full text."""
    _, search = _table(mocker)

    await PassageRetriever(company="acme", query_type="fts").retrieve("scope 1")

    search.refine_factor.assert_not_called()


async def test_given_full_text_mode_when_retrieving_then_nothing_is_embedded(
    mocker: MockerFixture,
) -> None:
    """Full text costs no API call, and choosing it must keep that true."""
    tbl, _ = _table(mocker)
    embed = _embedding(mocker)

    await PassageRetriever(company="acme", query_type="fts").retrieve("scope 1")

    tbl.search.assert_called_once_with("scope 1", query_type="fts")
    embed.assert_not_called()


async def test_given_vector_mode_when_nothing_matches_then_the_reason_names_the_mode(
    mocker: MockerFixture,
) -> None:
    """A refusal has to say which search found nothing, or it cannot be diagnosed."""
    _, search = _table(mocker)
    search.to_list.return_value = []
    _embedding(mocker)

    result = await PassageRetriever(company="acme", query_type="vector").retrieve("nothing")

    assert result.refused is True
    assert result.reason == "no_vector_matches"


async def test_given_no_mode_when_retrieving_then_the_configured_default_is_used(
    mocker: MockerFixture,
) -> None:
    """The mode is a setting, so callers need not know which one is current."""
    tbl, _ = _table(mocker)
    _embedding(mocker)
    settings = mocker.patch("peerdex.retrieve._retriever.get_settings")
    settings.return_value.retrieval.query_type = "fts"
    settings.return_value.retrieval.final_top_k = 25

    await PassageRetriever(company="acme").retrieve("scope 1")

    tbl.search.assert_called_once_with("scope 1", query_type="fts")
