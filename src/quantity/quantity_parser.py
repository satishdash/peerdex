"""Turns the value and unit text an extraction carries into one typed quantity."""

from decimal import Decimal

from quantity.numeric_parser import NumericParser
from quantity.quantity import Quantity
from quantity.scale_reader import ScaleReader
from quantity.unit import Unit
from quantity.unit_registry import UnitRegistry


class QuantityParser:
    """Turns the value and unit text an extraction carries into one typed quantity."""

    def __init__(
        self,
        registry: UnitRegistry | None = None,
        numbers: NumericParser | None = None,
        scales: ScaleReader | None = None,
    ) -> None:
        """Bind to the parsers that read a value and a unit.

        Args:
            registry: Resolves the unit text, or None for the standard registry.
            numbers: Reads the number, or None for the standard parser.
            scales: Reads a scale word, or None for the standard reader.
        """
        self._registry: UnitRegistry = registry or UnitRegistry()
        self._numbers: NumericParser = numbers or NumericParser()
        self._scales: ScaleReader = scales or ScaleReader()

    def parse(self, value: str, unit: str) -> Quantity | None:
        """The typed figure a value and unit describe.

        Args:
            value: The figure as the document writes it.
            unit: The unit text printed beside it.

        Returns:
            The quantity, or None when either the number or the unit cannot be read.
        """
        number: float | None = self._numbers.parse(value)
        resolved: Unit | None = self._registry.resolve(unit)
        if number is None or resolved is None:
            return None
        return Quantity(Decimal(str(number)) * self._scales.read(unit), resolved)
