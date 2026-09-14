"""Route selects the answer's shape from the declared kind and the period from the filters."""

import pytest

from ask import AnswerKind, Question, Router


def _question(kind: AnswerKind = AnswerKind.QUANTITATIVE, **filters: object) -> Question:
    return Question(
        text="What were scope 1 emissions?",
        kind=kind,
        company="acme",
        domain="corporate",
        filters=filters,
    )


@pytest.mark.parametrize("kind", [AnswerKind.QUANTITATIVE, AnswerKind.QUALITATIVE])
def test_given_a_declared_kind_when_routed_then_it_is_carried_through(kind: AnswerKind) -> None:
    """The caller declares kind, so nothing is inferred and nothing is paid for."""
    assert Router.route(_question(kind)).kind is kind


def test_given_one_year_filter_when_routed_then_it_is_the_period() -> None:
    """The asked-for period comes from the year filter, not from the question text."""
    assert Router.route(_question(year=2025)).period == 2025


def test_given_a_year_as_text_when_routed_then_it_is_still_the_period() -> None:
    """A filter arriving from the CLI is text, and a period is a number."""
    assert Router.route(_question(year="2024")).period == 2024


def test_given_a_single_year_in_a_sequence_when_routed_then_it_is_the_period() -> None:
    """One admitted value in a repeatable filter still names one period."""
    assert Router.route(_question(year=(2023,))).period == 2023


def test_given_no_year_filter_when_routed_then_there_is_no_period() -> None:
    """With no year asked for, no column can be judged against one."""
    assert Router.route(_question()).period is None


def test_given_several_years_when_routed_then_there_is_no_period() -> None:
    """Two admitted years name no single period, so Resolve must judge no column."""
    assert Router.route(_question(year=(2024, 2025))).period is None


def test_given_a_year_that_is_not_a_number_when_routed_then_there_is_no_period() -> None:
    """A filter the caller mistyped must not become a period that gates every column."""
    assert Router.route(_question(year="latest")).period is None


def test_given_other_filters_when_routed_then_they_do_not_become_a_period() -> None:
    """Only the year filter names a period; company and attributes never do."""
    assert Router.route(_question(sector="airline", benchmark=True)).period is None
