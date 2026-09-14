"""A printed figure is only comparable once its unit and its scale are typed."""

from decimal import Decimal

import pytest

from quantity import IncompatibleUnitsError, Quantity, QuantityParser, UnitRegistry

PARSER: QuantityParser = QuantityParser()
REGISTRY: UnitRegistry = UnitRegistry()


def _quantity(magnitude: str, unit: str) -> Quantity:
    parsed: Quantity | None = PARSER.parse(magnitude, unit)
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("value", "unit", "symbol", "magnitude"),
    [
        pytest.param("8,388", "Tonnes", "t", "8388", id="mass"),
        pytest.param("6,197,690", "Tonnes CO₂e", "t", "6197690", id="mass-with-qualifier"),
        pytest.param("19.65", "thousand tonnes", "t", "19650", id="mass-scaled-by-word"),
        pytest.param("3.44", "Million m 3", "m3", "3440000", id="volume-spaced-exponent"),
        pytest.param("22.15", "million m³", "m3", "22150000", id="volume-superscript"),
        pytest.param("1,216,901", "MWh", "MWh", "1216901", id="energy-symbol"),
        pytest.param("6.37", "Megawatt hours (MWh)", "MWh", "6.37", id="energy-spelled-out"),
        pytest.param("5,803,690", "GJ", "GJ", "5803690", id="energy-canonical"),
        pytest.param("1.1", "%", "%", "1.1", id="fraction"),
        pytest.param("95,100", "", "", "95100", id="bare-count"),
        pytest.param("(1,024)", "kg", "kg", "-1024", id="negative-in-parens"),
    ],
)
def test_given_a_printed_figure_when_parsed_then_its_unit_and_scale_are_typed(
    value: str, unit: str, symbol: str, magnitude: str
) -> None:
    """The scale a unit declares belongs in the number, or 3.44 and 3,440,000 differ."""
    parsed: Quantity = _quantity(value, unit)

    assert parsed.unit.symbol == symbol
    assert parsed.magnitude == Decimal(magnitude)


@pytest.mark.parametrize(
    ("value", "unit"),
    [
        pytest.param("5", "widgets per fortnight", id="unknown-unit"),
        pytest.param("", "t", id="no-number"),
        pytest.param("about a third", "%", id="no-number-in-words"),
    ],
)
def test_given_a_figure_that_cannot_be_typed_when_parsed_then_nothing(
    value: str, unit: str
) -> None:
    """Guessing a unit is worse than having none: every later step would trust the guess."""
    assert PARSER.parse(value, unit) is None


@pytest.mark.parametrize(
    ("magnitude", "source", "target", "expected"),
    [
        pytest.param("1", "GWh", "MWh", "1000", id="energy-down"),
        pytest.param("3.6", "GJ", "MWh", "1", id="energy-across-families"),
        pytest.param("2", "t", "kg", "2000", id="mass-down"),
        pytest.param("1", "ML", "m3", "1000", id="volume-down"),
        pytest.param("2500", "kg", "t", "2.5", id="mass-up"),
    ],
)
def test_given_a_target_unit_in_the_same_dimension_when_converted_then_the_magnitude_scales(
    magnitude: str, source: str, target: str, expected: str
) -> None:
    """Two figures cannot be added, compared or scored until they are in one unit."""
    unit = REGISTRY.resolve(target)
    assert unit is not None

    converted: Quantity = _quantity(magnitude, source).to(unit)

    assert converted.magnitude == Decimal(expected)
    assert converted.unit.symbol == target


@pytest.mark.parametrize(
    ("left", "left_unit", "operation", "right", "right_unit", "expected"),
    [
        pytest.param("1", "GWh", "add", "500", "MWh", "1.5", id="sum-converts-the-operand"),
        pytest.param("8,388", "t", "add", "15,022", "t", "23410", id="sum-same-unit"),
        pytest.param("1", "Mt", "subtract", "500", "t", "0.9995", id="difference-converts"),
        pytest.param("15,022", "t", "subtract", "9,587", "t", "5435", id="difference-same-unit"),
    ],
)
def test_given_two_quantities_in_one_dimension_when_combined_then_the_operand_is_converted(
    left: str, left_unit: str, operation: str, right: str, right_unit: str, expected: str
) -> None:
    """Adding 1 GWh to 500 MWh as printed would report 501 of nothing.

    The result is always in the first operand's unit, so that unit is what the
    answer is reported in.
    """
    first: Quantity = _quantity(left, left_unit)
    second: Quantity = _quantity(right, right_unit)
    combined: Quantity = first + second if operation == "add" else first - second

    assert combined.magnitude == Decimal(expected)
    assert combined.unit.symbol == left_unit


@pytest.mark.parametrize("operation", ["add", "subtract", "convert"])
def test_given_two_dimensions_when_combined_then_it_is_refused(operation: str) -> None:
    """Tonnes and cubic metres have no sum, and a silent one is a fabricated figure."""
    mass: Quantity = _quantity("8,388", "t")
    volume: Quantity = _quantity("3.44", "m3")

    with pytest.raises(IncompatibleUnitsError, match="t"):
        if operation == "add":
            mass + volume
        elif operation == "subtract":
            mass - volume
        else:
            mass.to(volume.unit)


@pytest.mark.parametrize(
    ("left_unit", "right_unit", "expected", "symbol"),
    [
        pytest.param("m3", "t", "2", "m3/t", id="compound"),
        pytest.param("t", "t", "2", "", id="dimensionless"),
    ],
)
def test_given_a_ratio_when_divided_then_the_unit_records_what_it_is_per(
    left_unit: str, right_unit: str, expected: str, symbol: str
) -> None:
    """An intensity is meaningless without its denominator, so the unit carries it."""
    ratio: Quantity = _quantity("10", left_unit) / _quantity("5", right_unit)

    assert ratio.magnitude == Decimal(expected)
    assert ratio.unit.symbol == symbol


def test_given_a_zero_denominator_when_divided_then_it_is_refused() -> None:
    """A division by zero is an arithmetic accident, not an answer."""
    with pytest.raises(IncompatibleUnitsError, match="zero"):
        _quantity("10", "t") / _quantity("0", "t")


@pytest.mark.parametrize(
    ("magnitude", "unit", "expected"),
    [
        pytest.param("6271593", "t", "6,271,593", id="separated-thousands"),
        pytest.param("2.50", "MWh", "2.5", id="trailing-zero-dropped"),
        pytest.param("-1024", "kg", "-1,024", id="negative"),
    ],
)
def test_given_a_quantity_when_rendered_then_it_reads_as_a_printed_figure(
    magnitude: str, unit: str, expected: str
) -> None:
    """The answer is scored as text, so the rendering is part of being right."""
    assert _quantity(magnitude, unit).rendered == expected
