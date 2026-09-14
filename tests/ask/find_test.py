"""Find is one database call: filter, search, rerank, top k."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from ask import AnswerKind, Finder, Question


@pytest.fixture
def table(mocker: MockerFixture) -> Any:
    """A stand-in LanceDB table whose builder records what Find asked of it.

    Returns:
        The table mock, with ``builder`` exposed for assertions.
    """
    builder = mocker.MagicMock()
    for chained in ("where", "rerank", "limit", "vector", "text"):
        getattr(builder, chained).return_value = builder
    builder.to_list.return_value = []
    tbl = mocker.MagicMock()
    tbl.search.return_value = builder
    tbl.builder = builder
    mocker.patch("ask.find.finder.Tables.open", return_value=tbl)
    return tbl


@pytest.fixture
def embed(mocker: MockerFixture) -> Any:
    """The query embedder, counted so a lexical search can be shown to skip it.

    Returns:
        The patched embedding model.
    """
    model = mocker.MagicMock()
    model.aget_query_embedding = mocker.AsyncMock(return_value=[0.5, 0.5])
    return mocker.patch("ask.find.finder.Embeddings.model", return_value=model)


def _settings(mocker: MockerFixture, *, mode: str, reranker: str, top_k: int = 25) -> None:
    cfg = mocker.patch("ask.find.finder.get_settings").return_value
    cfg.retrieval.query_type = mode
    cfg.retrieval.reranker = reranker
    cfg.retrieval.final_top_k = top_k


def _question(**filters: object) -> Question:
    return Question(
        text="scope 1 emissions",
        kind=AnswerKind.QUANTITATIVE,
        company="Acme",
        domain="corporate",
        filters=filters,
    )


async def test_given_vector_mode_when_finding_then_the_query_is_embedded_once(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Dense search costs exactly one embedding of the question."""
    _settings(mocker, mode="vector", reranker="none")

    await Finder.find(_question())

    assert embed.return_value.aget_query_embedding.await_count == 1
    table.search.assert_called_once_with([0.5, 0.5])


async def test_given_fts_mode_when_finding_then_nothing_is_embedded(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Full-text search uses the question verbatim, so it must cost no API call."""
    _settings(mocker, mode="fts", reranker="none")

    await Finder.find(_question())

    assert embed.return_value.aget_query_embedding.await_count == 0
    table.search.assert_called_once_with("scope 1 emissions", query_type="fts")


async def test_given_hybrid_mode_when_finding_then_both_lists_are_asked_for(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Hybrid ranks twice, so it needs the vector and the text set explicitly."""
    _settings(mocker, mode="hybrid", reranker="none")

    await Finder.find(_question())

    table.search.assert_called_once_with(query_type="hybrid")
    table.builder.vector.assert_called_once_with([0.5, 0.5])
    table.builder.text.assert_called_once_with("scope 1 emissions")


async def test_given_no_reranker_when_finding_then_nothing_reranks(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """The default path ranks once and stops."""
    _settings(mocker, mode="vector", reranker="none")

    await Finder.find(_question())

    table.builder.rerank.assert_not_called()


async def test_given_rrf_when_finding_then_the_shortlist_is_fused(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Reciprocal-rank fusion is arithmetic over two ranked lists, so it costs no call."""
    _settings(mocker, mode="hybrid", reranker="rrf")

    await Finder.find(_question())

    table.builder.rerank.assert_called_once()


async def test_given_filters_when_finding_then_company_is_always_on(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """The filter narrows before ranking, and company is never optional."""
    _settings(mocker, mode="vector", reranker="none")

    await Finder.find(_question(year=2025))

    predicate = table.builder.where.call_args.args[0]
    assert "metadata.company = 'acme'" in predicate
    assert "metadata.year = 2025" in predicate


async def test_given_top_k_when_finding_then_that_many_are_asked_for(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Top k is a toggle, so it must reach the query."""
    _settings(mocker, mode="vector", reranker="none", top_k=7)

    await Finder.find(_question())

    table.builder.limit.assert_called_once_with(7)


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"_score": 4.0}, 4.0),
        ({"_relevance_score": 0.75}, 0.75),
        ({"_distance": 0.0}, 1.0),
        ({"_distance": 1.0}, 0.5),
        ({}, 0.0),
    ],
)
async def test_given_a_mode_score_when_finding_then_higher_always_means_better(
    table: Any, embed: Any, mocker: MockerFixture, row: dict[str, float], expected: float
) -> None:
    """Each mode scores differently; vector returns a distance, where smaller is better."""
    _settings(mocker, mode="vector", reranker="none")
    table.builder.to_list.return_value = [
        {"id": "d1:c0", "text": "t", "parent_id": "d1:p0", "metadata": {}, **row}
    ]

    found = await Finder.find(_question())

    assert found[0].score == pytest.approx(expected)


async def test_given_rows_when_finding_then_each_passage_carries_its_parent(
    table: Any, embed: Any, mocker: MockerFixture
) -> None:
    """Escalation fetches by parent_id, so a passage must carry the one it came from."""
    _settings(mocker, mode="vector", reranker="none")
    table.builder.to_list.return_value = [
        {
            "id": "d1:c0",
            "text": "Scope 1 was 62,587",
            "parent_id": "d1:p3",
            "metadata": {"page_no": 12, "company": "acme"},
            "_distance": 0.2,
        }
    ]

    found = await Finder.find(_question())

    assert len(found) == 1
    assert found[0].id == "d1:c0"
    assert found[0].text == "Scope 1 was 62,587"
    assert found[0].parent_id == "d1:p3"
    assert found[0].metadata["page_no"] == 12
