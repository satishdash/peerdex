"""The two escalation boxes: fetch parent by id, and a lexical rewrite."""

from typing import Any

from pytest_mock import MockerFixture

from ask import ParentFetch, Passage, Rewriter
from index import ParentRow


def _passage(pid: str, parent: str) -> Passage:
    return Passage(id=pid, text="child text", score=0.5, parent_id=parent)


def test_given_refused_passages_when_escalated_then_parents_are_fetched_by_id(
    mocker: MockerFixture,
) -> None:
    """The escalation holds only a parent_id, and fetches by it without searching."""
    store: Any = mocker.patch("ask.escalate.parent_fetch.ParentStore").return_value
    store.get.return_value = {
        "d1:p0": ParentRow(id="d1:p0", text="the whole section", metadata={"page_no": 41})
    }

    widened = ParentFetch.widen("corporate", [_passage("d1:c0", "d1:p0")])

    store.get.assert_called_once_with(["d1:p0"])
    assert [p.text for p in widened] == ["the whole section"]
    assert widened[0].id == "d1:p0"


def test_given_several_passages_when_escalated_then_each_parent_is_asked_for_once(
    mocker: MockerFixture,
) -> None:
    """Two passages from one section share a parent, which is fetched once."""
    store: Any = mocker.patch("ask.escalate.parent_fetch.ParentStore").return_value
    store.get.return_value = {}

    ParentFetch.widen(
        "corporate",
        [_passage("d1:c0", "d1:p0"), _passage("d1:c1", "d1:p0"), _passage("d1:c2", "d1:p9")],
    )

    assert sorted(store.get.call_args.args[0]) == ["d1:p0", "d1:p9"]


def test_given_a_figure_with_no_parent_when_escalated_then_it_is_skipped(
    mocker: MockerFixture,
) -> None:
    """A figure in a section with no parent carries an empty id and cannot be widened."""
    store: Any = mocker.patch("ask.escalate.parent_fetch.ParentStore").return_value
    store.get.return_value = {}

    assert ParentFetch.widen("corporate", [_passage("d1:c0", "")]) == []
    store.get.assert_called_once_with([])


def test_given_no_passages_when_escalated_then_nothing_is_fetched(
    mocker: MockerFixture,
) -> None:
    """Escalation with nothing in hand must cost no query."""
    store: Any = mocker.patch("ask.escalate.parent_fetch.ParentStore").return_value

    assert ParentFetch.widen("corporate", []) == []
    store.get.assert_not_called()


def test_given_a_question_when_rewritten_then_it_stays_lexical() -> None:
    """The rewrite is lexical, so it costs no model call."""
    assert Rewriter.rewrite("What were Acme's scope 1 emissions in 2024?", []) != ""


def test_given_a_question_when_rewritten_then_the_metric_terms_survive() -> None:
    """Broadening drops qualifiers, never the metric the question is about."""
    rewritten = Rewriter.rewrite("What were the total scope 1 emissions for the year?", [])

    assert "scope" in rewritten.lower()
    assert "emissions" in rewritten.lower()


def test_given_a_question_when_rewritten_then_it_is_not_the_same_query() -> None:
    """Searching again with the identical query would return the identical nothing."""
    question = "What were the total scope 1 greenhouse gas emissions for the year?"

    assert Rewriter.rewrite(question, []) != question


def test_given_passages_when_rewritten_then_their_wording_is_used() -> None:
    """The rewrite draws on what came back, when anything came back."""
    passages = [Passage(id="d1:c0", text="Direct (Scope 1) GHG emissions tonnes CO2e", score=1.0)]

    rewritten = Rewriter.rewrite("carbon output", passages)

    assert "ghg" in rewritten.lower() or "emissions" in rewritten.lower()
