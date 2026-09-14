"""Every answer traces back to the chunks it was read from."""

from typing import Any

import pytest
from pytest_mock import MockerFixture

from ask import AnswerKind, AskPipeline, Citation, Passage, Question, Reading


@pytest.fixture
def stages(mocker: MockerFixture) -> dict[str, Any]:
    """Every stage patched, so what is under test is what the answer carries.

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
    }


def _passage(pid: str = "d1:c0", page: int = 41) -> Passage:
    return Passage(
        id=pid,
        text="| Direct (Scope 1) | Tonnes CO2e | 62,587 |",
        score=0.9,
        parent_id="d1:p0",
        metadata={
            "company": "acmeair",
            "year": 2024,
            "page_no": page,
            "heading_path": "GHG emissions",
            "source_doc_id": "abc123",
        },
    )


def _question(kind: AnswerKind = AnswerKind.QUANTITATIVE) -> Question:
    return Question(
        text="scope 1 emissions",
        kind=kind,
        company="acmeair",
        domain="corporate",
        filters={"year": 2024},
    )


async def test_given_an_answer_when_returned_then_it_cites_the_passages_read(
    stages: dict[str, Any],
) -> None:
    """The value stays bare, and the citations ride alongside it."""
    stages["find"].return_value = [_passage()]
    stages["read"].return_value = [Reading(value="62,587", unit="t", label="S1", column="2024")]

    answer = await AskPipeline.ask(_question())

    assert answer.value == "62,587"
    assert len(answer.citations) == 1
    cited: Citation = answer.citations[0]
    assert cited.chunk_id == "d1:c0"
    assert cited.company == "acmeair"
    assert cited.year == 2024
    assert cited.page_no == 41
    assert cited.heading_path == "GHG emissions"


async def test_given_several_passages_when_answered_then_each_is_cited(
    stages: dict[str, Any],
) -> None:
    """Every chunk the reader was given is traceable, in the order it was ranked."""
    stages["find"].return_value = [_passage("d1:c0", 41), _passage("d1:c1", 42)]
    stages["read"].return_value = [Reading(value="1", unit="t", label="S1", column="2024")]

    answer = await AskPipeline.ask(_question())

    assert [c.chunk_id for c in answer.citations] == ["d1:c0", "d1:c1"]
    assert [c.page_no for c in answer.citations] == [41, 42]


async def test_given_a_qualitative_answer_when_returned_then_it_also_cites(
    stages: dict[str, Any],
) -> None:
    """Prose needs provenance at least as much as a value does."""
    stages["find"].return_value = [_passage()]
    stages["prose"].return_value = "Acme Air targets net zero by 2050."

    answer = await AskPipeline.ask(_question(AnswerKind.QUALITATIVE))

    assert answer.text != ""
    assert [c.chunk_id for c in answer.citations] == ["d1:c0"]


async def test_given_escalation_when_answered_then_it_cites_what_was_actually_read(
    stages: dict[str, Any],
) -> None:
    """The second attempt reads the parents, so those are what the answer cites."""
    stages["find"].return_value = [_passage()]
    stages["read"].side_effect = [
        [Reading(value="", unit="", label="", column="")],
        [Reading(value="62,587", unit="t", label="S1", column="2024")],
    ]
    stages["parent"].return_value = [
        Passage(id="d1:p0", text="the whole section", score=0.0, metadata={"page_no": 41})
    ]

    answer = await AskPipeline.ask(_question())

    assert answer.attempts == 2
    assert [c.chunk_id for c in answer.citations] == ["d1:p0"]


async def test_given_a_refusal_when_returned_then_it_cites_nothing(
    stages: dict[str, Any],
) -> None:
    """A refusal has no answer to trace, so it carries a reason instead."""
    stages["find"].return_value = []

    answer = await AskPipeline.ask(_question())

    assert answer.refused is True
    assert answer.citations == ()
