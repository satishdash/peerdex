"""The static flow: two attempts at most, no agent, no loop."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from ask import AnswerKind, AskPipeline, Passage, Question, Reading


@pytest.fixture
def stages(mocker: MockerFixture) -> dict[str, Any]:
    """Every stage patched, so the flow's shape is what is under test.

    Returns:
        The patched stages, keyed by name.
    """
    cfg = mocker.patch("ask.ask_pipeline.get_settings").return_value
    cfg.retrieval.escalate_on_refusal = True
    return {
        "find": mocker.patch("ask.ask_pipeline.Finder.find", mocker.AsyncMock(return_value=[])),
        "read": mocker.patch("ask.ask_pipeline.Reader.read", mocker.AsyncMock(return_value=[])),
        "prose": mocker.patch(
            "ask.ask_pipeline.ProseReader.read", mocker.AsyncMock(return_value="")
        ),
        "parent": mocker.patch("ask.ask_pipeline.ParentFetch.widen", return_value=[]),
        "rewrite": mocker.patch("ask.ask_pipeline.Rewriter.rewrite", return_value="broader"),
        "cfg": cfg,
    }


def _passage() -> Passage:
    return Passage(id="d1:c0", text="| Scope 1 | 62,587 |", score=1.0, parent_id="d1:p0")


def _reading(value: str = "62,587", label: str = "Scope 1", column: str = "2024") -> Reading:
    return Reading(value=value, unit="t", label=label, column=column)


def _question(kind: AnswerKind = AnswerKind.QUANTITATIVE) -> Question:
    return Question(
        text="scope 1 emissions",
        kind=kind,
        company="acme",
        domain="corporate",
        filters={"year": 2024},
    )


async def test_given_a_value_on_the_first_attempt_when_asked_then_it_answers_once(
    stages: dict[str, Any],
) -> None:
    """The passed branch leaves the flow immediately; nothing escalates."""
    stages["find"].return_value = [_passage()]
    stages["read"].return_value = [_reading()]

    answer = await AskPipeline.ask(_question())

    assert (answer.refused, answer.value, answer.attempts) == (False, "62,587", 1)
    assert stages["find"].await_count == 1
    stages["parent"].assert_not_called()
    stages["rewrite"].assert_not_called()


async def test_given_no_passages_when_asked_then_it_rewrites_and_searches_again(
    stages: dict[str, Any],
) -> None:
    """The no-passages branch rewrites lexically, then runs Find a second time."""
    stages["find"].side_effect = [[], [_passage()]]
    stages["read"].return_value = [_reading()]

    answer = await AskPipeline.ask(_question())

    stages["rewrite"].assert_called_once()
    stages["parent"].assert_not_called()
    assert stages["find"].await_count == 2
    assert (answer.refused, answer.attempts) == (False, 2)


async def test_given_found_but_no_value_when_asked_then_it_fetches_parents_without_searching(
    stages: dict[str, Any],
) -> None:
    """The found-no-value branch fetches by id and never searches again."""
    stages["find"].return_value = [_passage()]
    stages["read"].side_effect = [[_reading(value="not stated")], [_reading()]]
    stages["parent"].return_value = [Passage(id="d1:p0", text="whole section", score=0.0)]

    answer = await AskPipeline.ask(_question())

    stages["parent"].assert_called_once()
    stages["rewrite"].assert_not_called()
    assert stages["find"].await_count == 1
    assert (answer.refused, answer.attempts) == (False, 2)


async def test_given_both_attempts_refuse_when_asked_then_the_reason_is_carried(
    stages: dict[str, Any],
) -> None:
    """A refusal carries its reason, and the flow stops at two attempts."""
    stages["find"].return_value = [_passage()]
    stages["read"].return_value = [_reading(value="not stated")]
    stages["parent"].return_value = [Passage(id="d1:p0", text="section", score=0.0)]

    answer = await AskPipeline.ask(_question())

    assert answer.refused is True
    assert answer.reason != ""
    assert answer.attempts == 2
    assert stages["read"].await_count == 2


async def test_given_escalation_switched_off_when_refused_then_there_is_one_attempt(
    stages: dict[str, Any],
) -> None:
    """Escalate on refusal is a toggle, so it must be possible to measure it off."""
    stages["cfg"].retrieval.escalate_on_refusal = False
    stages["find"].return_value = [_passage()]
    stages["read"].return_value = [_reading(value="not stated")]

    answer = await AskPipeline.ask(_question())

    assert (answer.refused, answer.attempts) == (True, 1)
    stages["parent"].assert_not_called()
    stages["rewrite"].assert_not_called()


async def test_given_a_qualitative_question_when_asked_then_prose_is_returned(
    stages: dict[str, Any],
) -> None:
    """The same question asked as qualitative returns prose, and no value is gated."""
    stages["find"].return_value = [_passage()]
    stages["prose"].return_value = "The company targets net zero by 2050."

    answer = await AskPipeline.ask(_question(AnswerKind.QUALITATIVE))

    assert answer.refused is False
    assert answer.text == "The company targets net zero by 2050."
    assert answer.value == ""
    stages["read"].assert_not_called()


async def test_given_a_qualitative_question_with_no_passages_when_asked_then_it_refuses(
    stages: dict[str, Any],
) -> None:
    """Prose from nothing would be invention, so it refuses with a reason."""
    stages["find"].return_value = []
    stages["prose"].return_value = ""

    answer = await AskPipeline.ask(_question(AnswerKind.QUALITATIVE))

    assert answer.refused is True
    assert answer.reason != ""


async def test_given_any_question_when_asked_then_it_never_runs_a_third_attempt(
    stages: dict[str, Any],
) -> None:
    """Two attempts at most: every path is the same length every time."""
    stages["find"].side_effect = [[], []]
    stages["read"].return_value = []

    answer = await AskPipeline.ask(_question())

    assert answer.attempts == 2
    assert stages["find"].await_count == 2
