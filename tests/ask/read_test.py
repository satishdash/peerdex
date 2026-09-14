"""Read returns the value and the evidence for it, in one call per figure."""

import json
from typing import Any

import pytest
from pytest_mock import MockerFixture

from ask import AnswerKind, Passage, Question, Reader


def _reply(mocker: MockerFixture, *bodies: str) -> Any:
    """Patch the client so each call returns the next body.

    Returns:
        The patched client, for asserting how many calls were made.
    """
    calls = [
        mocker.MagicMock(choices=[mocker.MagicMock(message=mocker.MagicMock(content=b))])
        for b in bodies
    ]
    client = mocker.MagicMock()
    client.chat.completions.create = mocker.AsyncMock(side_effect=calls)
    mocker.patch("ask.read.reader.Clients.openai_async", return_value=client)
    return client


def _passages() -> list[Passage]:
    return [
        Passage(
            id="d1:c0",
            text="| Scope 1 | Tonnes CO2e | 62,587 |",
            score=0.9,
            parent_id="d1:p0",
            metadata={"page_no": 41},
        )
    ]


def _question(text: str = "What were scope 1 emissions?") -> Question:
    return Question(
        text=text,
        kind=AnswerKind.QUANTITATIVE,
        company="acme",
        domain="corporate",
        filters={"year": 2024},
    )


async def test_given_passages_when_read_then_one_call_returns_value_and_evidence(
    mocker: MockerFixture,
) -> None:
    """The label and column exist so the next stage can catch the model out."""
    body = {"value": "62,587", "unit": "Tonnes CO2e", "label": "Scope 1", "column": "2024"}
    client = _reply(mocker, json.dumps(body))

    readings = await Reader.read(_question(), _passages())

    assert client.chat.completions.create.await_count == 1
    assert len(readings) == 1
    assert readings[0].value == "62,587"
    assert readings[0].unit == "Tonnes CO2e"
    assert readings[0].label == "Scope 1"
    assert readings[0].column == "2024"


async def test_given_no_passages_when_read_then_nothing_is_asked_of_the_model(
    mocker: MockerFixture,
) -> None:
    """Find returning nothing must not cost an LLM call."""
    client = _reply(mocker, "{}")

    assert await Reader.read(_question(), []) == []
    assert client.chat.completions.create.await_count == 0


async def test_given_the_passages_when_read_then_their_text_is_the_evidence(
    mocker: MockerFixture,
) -> None:
    """The model reads the passages Find returned, and nothing else."""
    client = _reply(mocker, json.dumps({"value": "1", "unit": "", "label": "x", "column": ""}))

    await Reader.read(_question(), _passages())

    sent = json.dumps(client.chat.completions.create.await_args.kwargs["messages"])
    assert "62,587" in sent
    assert "What were scope 1 emissions?" in sent


@pytest.mark.parametrize("body", ["not json at all", "", "{", "null"])
async def test_given_an_unreadable_reply_when_read_then_the_reading_is_empty(
    mocker: MockerFixture, body: str
) -> None:
    """A model that does not answer in the shape asked for must not crash the flow."""
    _reply(mocker, body)

    readings = await Reader.read(_question(), _passages())

    assert len(readings) == 1
    assert readings[0].value == ""


async def test_given_missing_keys_when_read_then_the_fields_are_empty(
    mocker: MockerFixture,
) -> None:
    """Every field is present so Resolve can gate on it, even when the model omits it."""
    _reply(mocker, json.dumps({"value": "5"}))

    reading = (await Reader.read(_question(), _passages()))[0]

    assert (reading.value, reading.unit, reading.label, reading.column) == ("5", "", "", "")


async def test_given_arithmetic_when_read_then_one_call_per_operand(
    mocker: MockerFixture,
) -> None:
    """Each operand is extracted separately from the passages already in hand."""
    client = _reply(
        mocker,
        json.dumps({"value": "1", "unit": "t", "label": "Scope 1", "column": "2024"}),
        json.dumps({"value": "2", "unit": "t", "label": "Scope 2", "column": "2024"}),
        json.dumps({"value": "3", "unit": "t", "label": "Scope 3", "column": "2024"}),
    )

    readings = await Reader.read(_question("Total GHG (Scope 1 + Scope 2 + Scope 3)"), _passages())

    assert client.chat.completions.create.await_count == 3
    assert [r.value for r in readings] == ["1", "2", "3"]


async def test_given_arithmetic_when_read_then_no_further_search_happens(
    mocker: MockerFixture,
) -> None:
    """Operands come from the passages already in hand, at no further search cost."""
    finder = mocker.patch("ask.find.finder.Finder.find")
    _reply(
        mocker,
        json.dumps({"value": "1", "unit": "t", "label": "Scope 1", "column": "2024"}),
        json.dumps({"value": "2", "unit": "t", "label": "Scope 2", "column": "2024"}),
        json.dumps({"value": "3", "unit": "t", "label": "Scope 3", "column": "2024"}),
    )

    await Reader.read(_question("Total GHG (Scope 1 + Scope 2 + Scope 3)"), _passages())

    finder.assert_not_called()
