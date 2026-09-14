"""Every cell of the design's mode/reranker table, including the two it forbids."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from ask import CrossEncoderReranker, NoReranker, RerankerFactory, RrfReranker
from shared.settings import RetrievalCfg

MODES: list[str] = ["fts", "vector", "hybrid"]
ALLOWED: list[tuple[str, str]] = [
    (mode, reranker)
    for mode in MODES
    for reranker in ("none", "rrf", "cross_encoder")
    if not (reranker == "rrf" and mode != "hybrid")
]
FORBIDDEN: list[tuple[str, str]] = [("fts", "rrf"), ("vector", "rrf")]


@pytest.mark.parametrize(("mode", "reranker"), ALLOWED)
def test_given_an_allowed_cell_when_configured_then_it_loads(mode: str, reranker: str) -> None:
    """Seven of the table's nine cells are ticked, so seven must configure."""
    cfg = RetrievalCfg(query_type=mode, reranker=reranker)

    assert (cfg.query_type, cfg.reranker) == (mode, reranker)


@pytest.mark.parametrize(("mode", "reranker"), FORBIDDEN)
def test_given_a_forbidden_cell_when_configured_then_it_is_refused(
    mode: str, reranker: str
) -> None:
    """Fusion merges two ranked lists, so a single-list mode has nothing to merge."""
    with pytest.raises(ValueError, match="rrf"):
        RetrievalCfg(query_type=mode, reranker=reranker)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("none", NoReranker), ("rrf", RrfReranker), ("cross_encoder", CrossEncoderReranker)],
)
def test_given_a_reranker_name_when_built_then_it_is_that_reranker(
    name: str, expected: type
) -> None:
    """Each name the setting allows maps to exactly one reranker."""
    assert isinstance(RerankerFactory.for_name(name), expected)


def test_given_an_unknown_reranker_when_built_then_it_is_refused() -> None:
    """A name nothing is registered under must fail loudly, not rank silently."""
    with pytest.raises(ValueError, match="unknown reranker"):
        RerankerFactory.for_name("magic")


def test_given_no_reranker_when_asked_for_its_engine_then_there_is_none() -> None:
    """Ranking once means handing the query nothing to rerank with."""
    assert NoReranker().engine() is None


def test_given_rrf_when_asked_for_its_engine_then_it_is_the_fusion() -> None:
    """Fusion is arithmetic, so it needs no model and costs no call."""
    assert RrfReranker().engine() is not None


def test_given_a_cross_encoder_when_asked_for_its_engine_then_it_uses_the_configured_model(
    mocker: MockerFixture,
) -> None:
    """The model is a setting, never a literal in the code."""
    engine: Any = mocker.patch("ask.find.cross_encoder_reranker.EngineCrossEncoder")
    settings: Any = mocker.patch("ask.find.cross_encoder_reranker.get_settings")
    settings.return_value.retrieval.reranker_model = "BAAI/bge-reranker-base"

    CrossEncoderReranker().engine()

    engine.assert_called_once_with(model_name="BAAI/bge-reranker-base")
