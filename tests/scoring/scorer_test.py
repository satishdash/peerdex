"""Unit tests for the pure answer-accuracy comparison seam."""

import pytest

from peerdex.scoring import AnswerScorer, Comparison, NumericParser


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        pytest.param("62587.0", "62,587 tCO2e", id="thousands-separator-and-unit"),
        pytest.param("1.26", "1.26", id="plain-decimal"),
        pytest.param("2045.0", "2,045 GWh", id="unit-suffix"),
        pytest.param("-1234.0", "(1,234)", id="parenthesised-negative"),
        pytest.param("-5.2", "-5.2%", id="leading-minus-percent"),
        pytest.param("-42.0", "\u221242 GWh", id="unicode-minus"),
        pytest.param("-2045.5", "($2,045.50)", id="parenthesised-currency-negative"),
        pytest.param("100.0", "100.9", id="within-one-percent"),
        pytest.param("42.0", "approximately 42 GWh", id="number-after-words"),
        pytest.param("0.0", "0", id="zero"),
        pytest.param("58739000000.0", "$58,739,000,000", id="currency-full-magnitude"),
        pytest.param("58739000000.0", "$58,739 million", id="currency-magnitude-word"),
        pytest.param("58739000000.0", "58,739 million", id="bare-magnitude-word"),
        pytest.param("1200000000.0", "£1.2bn", id="pound-bn"),
        pytest.param("22150000.0", "22.15 million m3", id="magnitude-then-length-unit"),
        pytest.param("6400000.0", "6.4m tCO2e", id="single-m-magnitude"),
        pytest.param("747000.0", "747k", id="thousands-k"),
        pytest.param("62000.0", "62 thousand", id="thousand-word"),
        pytest.param("2000000000000.0", "2tn", id="trillion-tn"),
        pytest.param("1000000.0", "1 mn", id="million-mn"),
        pytest.param("-3000.0", "-3k", id="negative-magnitude"),
        pytest.param("7000000.0", "7 M", id="uppercase-m"),
        pytest.param("1.2", "1.2 m3", id="single-m-is-cubic-metres"),
        pytest.param("3.0", "3 m2", id="single-m-is-square-metres"),
        pytest.param("5.0", "5 m/s", id="single-m-is-metres-per-second"),
    ],
)
def test_given_equivalent_values_when_scored_then_match(expected: str, actual: str) -> None:
    result: Comparison = AnswerScorer().score(expected, actual)
    assert result.category == "match"
    assert result.expected_number == float(expected)


@pytest.mark.parametrize(
    ("expected", "actual"),
    [
        pytest.param("747.0", "90,000", id="oracle-sample-different-value"),
        pytest.param("100.0", "102", id="outside-one-percent"),
        pytest.param("500.0", "no such figure is stated", id="numberless-prose"),
        pytest.param("62587.0", "6,258", id="not-a-power-of-ten-off"),
    ],
)
def test_given_different_values_when_scored_then_mismatch(expected: str, actual: str) -> None:
    assert AnswerScorer().score(expected, actual).category == "mismatch"


@pytest.mark.parametrize(
    ("expected", "actual", "scale"),
    [
        pytest.param("6.368763888888889", "6,368,764", 1e-6, id="oracle-normalised-energy"),
        pytest.param("22.15022", "22,150.22", 1e-3, id="oracle-normalised-water"),
        pytest.param("1.26", "1,260", 1e-3, id="thousand-scale"),
    ],
)
def test_given_power_of_ten_offset_when_scored_then_scale_mismatch(
    expected: str, actual: str, scale: float
) -> None:
    result: Comparison = AnswerScorer().score(expected, actual)
    assert result.category == "scale_mismatch"
    assert result.scale == scale
    assert result.expected_number == float(expected)
    assert result.actual_number is not None


@pytest.mark.parametrize(
    ("expected", "actual", "category"),
    [
        pytest.param("", "", "abstained", id="both-empty"),
        pytest.param("", "   ", "abstained", id="whitespace-answer"),
        pytest.param("", "42 GWh", "extra", id="oracle-empty-answer-present"),
        pytest.param("500.0", "", "missed", id="oracle-present-answer-empty"),
        pytest.param("500.0", "  ", "missed", id="oracle-present-answer-blank"),
    ],
)
def test_given_empty_sides_when_scored_then_presence_category(
    expected: str, actual: str, category: str
) -> None:
    assert AnswerScorer().score(expected, actual).category == category


def test_given_extra_answer_when_scored_then_actual_number_recorded() -> None:
    result: Comparison = AnswerScorer().score("", "62,587 tCO2e")
    assert result.category == "extra"
    assert result.expected_number is None
    assert result.actual_number == 62587.0


def test_given_a_unit_naming_the_scale_when_scored_then_it_is_a_match() -> None:
    """ "58,739" reported in $m IS 58.739 billion; the unit is the missing evidence."""
    result: Comparison = AnswerScorer().score("58739000000.0", "58,739", unit="$m")

    assert result.category == "match"
    assert result.scale is None


def test_given_a_spelled_out_unit_naming_the_scale_when_scored_then_it_is_a_match() -> None:
    """Units are written by an LLM, so "USD, million" must work as well as "$m"."""
    assert AnswerScorer().score("127000000.0", "127", unit="USD, million").category == "match"


def test_given_a_unit_naming_a_different_scale_when_scored_then_it_stays_a_scale_mismatch() -> None:
    """A unit only corroborates the scale it actually names."""
    result: Comparison = AnswerScorer().score("58739000000.0", "58,739", unit="thousand")

    assert result.category == "scale_mismatch"
    assert result.scale == 1e6


def test_given_a_magnitude_only_after_per_when_scored_then_it_is_not_upgraded() -> None:
    """In "per million of revenue" the magnitude is the denominator, not the quantity."""
    result: Comparison = AnswerScorer().score(
        "1260000.0", "1.26", unit="Tonnes CO2e per million of Total Revenue"
    )

    assert result.category == "scale_mismatch"


def test_given_a_plain_mismatch_when_scored_then_a_unit_cannot_rescue_it() -> None:
    """3.44 and 22.15 are not a power of ten apart, so no unit makes them agree."""
    assert AnswerScorer().score("22.15022", "3.44", unit="Million m 3").category == "mismatch"


def test_given_no_unit_when_scored_then_the_verdict_is_unchanged() -> None:
    """The unit is optional; omitting it must score exactly as before."""
    assert AnswerScorer().score("58739000000.0", "58,739").category == "scale_mismatch"
    assert AnswerScorer().score("62587.0", "62,587").category == "match"


def test_given_wider_tolerance_when_scored_then_match() -> None:
    assert AnswerScorer(rel_tol=0.05).score("100.0", "104").category == "match"
    assert AnswerScorer(rel_tol=0.05).score("100.0", "106").category == "mismatch"


def test_given_match_when_scored_then_numbers_recorded() -> None:
    result: Comparison = AnswerScorer().score("62587.0", "62,587 tCO2e")
    assert result.expected_number == 62587.0
    assert result.actual_number == 62587.0
    assert result.scale is None


def test_given_custom_magnitude_table_when_parsed_then_table_wins() -> None:
    parser: NumericParser = NumericParser(magnitudes={"lakh": 1e5})
    assert parser.parse("2 lakh") == 200000.0
    assert parser.parse("2 million") == 2.0
