"""Resolve runs no model: every gate in the diagram is decidable."""

import pytest

from ask import Reading, Resolver


def _reading(
    value: str = "62,587", unit: str = "Tonnes CO2e", label: str = "Scope 1", column: str = "2024"
) -> Reading:
    return Reading(value=value, unit=unit, label=label, column=column)


def test_given_a_complete_reading_when_resolved_then_the_value_stands() -> None:
    """A figure with a row label, a matching period and a bare number passes every gate."""
    resolved = Resolver.resolve([_reading()], period=2024, question="scope 1 emissions")

    assert resolved.refused is False
    assert resolved.value == "62,587"
    assert resolved.unit == "Tonnes CO2e"


def test_given_no_row_label_when_resolved_then_it_is_refused() -> None:
    """Without a row label there is no evidence the model read anything."""
    resolved = Resolver.resolve([_reading(label="")], period=2024, question="q")

    assert resolved.refused is True
    assert "label" in resolved.reason


@pytest.mark.parametrize("column", ["2023", "2022", "FY2019"])
def test_given_a_column_stating_another_period_when_resolved_then_it_is_refused(
    column: str,
) -> None:
    """The asked-for period comes from the year filter, so another period is the wrong cell."""
    resolved = Resolver.resolve([_reading(column=column)], period=2024, question="q")

    assert resolved.refused is True
    assert "period" in resolved.reason


@pytest.mark.parametrize("column", ["Female", "Unit", "", "Total"])
def test_given_a_column_stating_no_period_when_resolved_then_it_is_not_judged(
    column: str,
) -> None:
    """A Female column over a board count states no period, so it cannot be wrong."""
    resolved = Resolver.resolve([_reading(column=column)], period=2024, question="q")

    assert resolved.refused is False


def test_given_no_asked_for_period_when_resolved_then_no_column_is_judged() -> None:
    """With no year filter there is nothing to judge a column against."""
    resolved = Resolver.resolve([_reading(column="2019")], period=None, question="q")

    assert resolved.refused is False


@pytest.mark.parametrize("value", ["", "not stated", "about 62,587", "n/a", "-"])
def test_given_a_value_that_is_not_a_bare_number_when_resolved_then_it_is_refused(
    value: str,
) -> None:
    """A quantitative answer is the value alone, never a hedge."""
    resolved = Resolver.resolve([_reading(value=value)], period=2024, question="q")

    assert resolved.refused is True


@pytest.mark.parametrize("value", ["62,587", "62587", "1.5", "-3", "58,739.2"])
def test_given_a_bare_number_when_resolved_then_it_passes(value: str) -> None:
    """Thousands separators and decimals are how a document writes a number."""
    assert Resolver.resolve([_reading(value=value)], period=2024, question="q").refused is False


def test_given_nothing_read_when_resolved_then_it_is_refused() -> None:
    """Find returning nothing, or Read finding nothing, is a refusal with a reason."""
    resolved = Resolver.resolve([], period=2024, question="q")

    assert resolved.refused is True
    assert resolved.reason != ""


def test_given_operands_when_resolved_then_they_combine_as_typed_quantities() -> None:
    """Operands combine as typed quantities, converting units before adding."""
    parts = [
        _reading(value="1,000", unit="tonnes", label="Scope 1"),
        _reading(value="2,000", unit="tonnes", label="Scope 2"),
        _reading(value="3,000", unit="tonnes", label="Scope 3"),
    ]

    resolved = Resolver.resolve(
        parts, period=2024, question="Total GHG (Scope 1 + Scope 2 + Scope 3)"
    )

    assert resolved.refused is False
    assert resolved.value.replace(",", "") == "6000"


def test_given_operands_that_will_not_combine_when_resolved_then_the_single_figure_stands() -> None:
    """If two dimensions will not combine, nothing is derived and the first figure stands."""
    parts = [
        _reading(value="1,000", unit="tonnes", label="Scope 1"),
        _reading(value="50", unit="%", label="Scope 2"),
    ]

    resolved = Resolver.resolve(parts, period=2024, question="Total (Scope 1 + Scope 2)")

    assert resolved.refused is False
    assert resolved.value == "1,000"


def test_given_one_operand_refused_when_resolved_then_the_whole_answer_is_refused() -> None:
    """An operand that failed a gate cannot be silently dropped from a total."""
    parts = [
        _reading(value="1,000", unit="tonnes", label="Scope 1"),
        _reading(value="", unit="tonnes", label="Scope 2"),
    ]

    resolved = Resolver.resolve(parts, period=2024, question="Total (Scope 1 + Scope 2)")

    assert resolved.refused is True
