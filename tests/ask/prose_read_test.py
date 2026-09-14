"""The same question asked as qualitative returns prose, not a value."""

from typing import Any

from pytest_mock import MockerFixture

from ask import AnswerKind, Passage, ProseReader, Question


def _client(mocker: MockerFixture, body: str) -> Any:
    client = mocker.MagicMock()
    client.chat.completions.create = mocker.AsyncMock(
        return_value=mocker.MagicMock(
            choices=[mocker.MagicMock(message=mocker.MagicMock(content=body))]
        )
    )
    mocker.patch("ask.read.prose_reader.Clients.openai_async", return_value=client)
    return client


def _passages() -> list[Passage]:
    return [
        Passage(id="d1:c0", text="Acme Air set a 2050 net-zero goal.", score=0.9),
        Passage(id="d1:c1", text="Interim targets cover 2030.", score=0.8),
    ]


def _question() -> Question:
    return Question(
        text="What is the climate strategy?",
        kind=AnswerKind.QUALITATIVE,
        company="acme",
        domain="corporate",
    )


async def test_given_passages_when_read_as_prose_then_one_call_returns_the_text(
    mocker: MockerFixture,
) -> None:
    """A qualitative answer is prose, produced in one call over the passages found."""
    client = _client(mocker, "The company targets net zero by 2050.")

    text = await ProseReader.read(_question(), _passages())

    assert client.chat.completions.create.await_count == 1
    assert text == "The company targets net zero by 2050."


async def test_given_no_passages_when_read_as_prose_then_nothing_is_asked_of_the_model(
    mocker: MockerFixture,
) -> None:
    """Find returning nothing must not cost an LLM call."""
    client = _client(mocker, "unused")

    assert await ProseReader.read(_question(), []) == ""
    assert client.chat.completions.create.await_count == 0


async def test_given_passages_when_read_as_prose_then_they_are_the_evidence(
    mocker: MockerFixture,
) -> None:
    """The model reads the passages Find returned, and nothing else."""
    client = _client(mocker, "text")

    await ProseReader.read(_question(), _passages())

    sent = str(client.chat.completions.create.await_args.kwargs["messages"])
    assert "net-zero goal" in sent
    assert "What is the climate strategy?" in sent


async def test_given_an_empty_reply_when_read_as_prose_then_the_text_is_empty(
    mocker: MockerFixture,
) -> None:
    """A model that says nothing yields no answer rather than a crash."""
    _client(mocker, "")

    assert await ProseReader.read(_question(), _passages()) == ""
