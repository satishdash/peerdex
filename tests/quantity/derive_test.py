"""Deriving a figure is allowed only where the question itself spells the arithmetic out."""

from decimal import Decimal

import pytest

from peerdex.quantity import (
    ArithmeticQuestion,
    Derivation,
    DerivationEngine,
    Quantity,
    QuantityParser,
)

READER: ArithmeticQuestion = ArithmeticQuestion()
ENGINE: DerivationEngine = DerivationEngine()
PARSER: QuantityParser = QuantityParser()

TOTAL_GHG: str = "Total GHG emissions (Scope 1 + Scope 2 + Scope 3)"


def _quantity(magnitude: str, unit: str) -> Quantity:
    parsed: Quantity | None = PARSER.parse(magnitude, unit)
    assert parsed is not None
    return parsed


@pytest.mark.parametrize(
    ("question", "operation", "operands"),
    [
        pytest.param(TOTAL_GHG, "sum", ("Scope 1", "Scope 2", "Scope 3"), id="sum-of-three"),
        pytest.param(
            "Waste diverted (Total waste - Waste to landfill)",
            "difference",
            ("Total waste", "Waste to landfill"),
            id="difference",
        ),
        pytest.param(
            "Energy intensity (Total energy consumption / Revenue)",
            "ratio",
            ("Total energy consumption", "Revenue"),
            id="ratio",
        ),
    ],
)
def test_given_a_question_that_spells_out_arithmetic_when_read_then_the_operands_are_named(
    question: str, operation: str, operands: tuple[str, ...]
) -> None:
    """The question is the only mandate to compute, so the operands come from it verbatim."""
    derivation: Derivation | None = READER.read(question)

    assert derivation is not None
    assert derivation.operation == operation
    assert derivation.operands == operands


@pytest.mark.parametrize(
    "question",
    [
        pytest.param("Total energy consumed that is not renewable", id="no-arithmetic"),
        pytest.param("Water intensity ratio per revenue", id="named-but-unspelled"),
        pytest.param("Total energy consumption (MWh)", id="trailing-unit-only"),
        pytest.param("Scope 3 emissions - category 1", id="a-dash-in-a-label"),
        pytest.param("Total GHG emissions (Scope 1 +)", id="one-operand-only"),
    ],
)
def test_given_a_question_without_spelled_out_arithmetic_when_read_then_nothing(
    question: str,
) -> None:
    """Reading arithmetic into a plain question is how a printed figure gets overruled."""
    assert READER.read(question) is None


@pytest.mark.parametrize(
    ("operation", "parts", "expected", "symbol"),
    [
        pytest.param(
            "sum",
            [("62,587", "t"), ("108,000", "t"), ("6,100,000", "t")],
            "6270587",
            "t",
            id="sum",
        ),
        pytest.param("sum", [("1", "GWh"), ("500", "MWh")], "1.5", "GWh", id="sum-across-units"),
        pytest.param("difference", [("15,022", "t"), ("9,587", "t")], "5435", "t", id="difference"),
        pytest.param("ratio", [("3.44", "m3"), ("1.72", "m3")], "2", "", id="ratio"),
    ],
)
def test_given_typed_operands_when_combined_then_the_arithmetic_is_performed(
    operation: str, parts: list[tuple[str, str]], expected: str, symbol: str
) -> None:
    """The whole point of typing a unit is that the arithmetic can then be trusted."""
    quantities: list[Quantity | None] = [_quantity(value, unit) for value, unit in parts]

    combined: Quantity | None = ENGINE.combine(
        Derivation(operation=operation, operands=("a", "b", "c")[: len(parts)]), quantities
    )

    assert combined is not None
    assert combined.magnitude == Decimal(expected)
    assert combined.unit.symbol == symbol


@pytest.mark.parametrize(
    ("operation", "parts"),
    [
        pytest.param("sum", [("62,587", "t"), None], id="an-operand-was-not-found"),
        pytest.param("sum", [("62,587", "t"), ("3.44", "m3")], id="operands-of-two-dimensions"),
        pytest.param("difference", [("62,587", "t")], id="too-few-operands"),
        pytest.param("ratio", [("62,587", "t"), ("0", "t")], id="ratio-by-zero"),
    ],
)
def test_given_operands_that_cannot_be_combined_when_derived_then_nothing(
    operation: str, parts: list[tuple[str, str] | None]
) -> None:
    """A partial sum is a wrong figure wearing the shape of a right one."""
    quantities: list[Quantity | None] = [
        None if part is None else _quantity(part[0], part[1]) for part in parts
    ]

    assert (
        ENGINE.combine(
            Derivation(operation=operation, operands=("a", "b", "c")[: len(parts)]), quantities
        )
        is None
    )
