"""A figure with its unit: one value object, and the only arithmetic allowed on figures.

Every combination goes through the unit. Two figures in one dimension are put in
one unit before they are combined, and two figures in different dimensions are
refused rather than combined into a plausible-looking wrong number.

Magnitudes are ``Decimal``: a report prints exact decimal figures, and binary
floats would make 62,587 + 108,000 depend on the order it was added in.
"""

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from peerdex.quantity._unit import Dimension, Unit, UnitRegistry
from peerdex.scoring import MAGNITUDES, NumericParser


class IncompatibleUnitsError(ValueError):
    """Raised when an arithmetic step would combine figures that do not combine."""


@dataclass(frozen=True)
class Quantity:
    """One figure in one unit, comparable and combinable with another of its dimension."""

    magnitude: Decimal
    unit: Unit

    @property
    def canonical(self) -> Decimal:
        """The magnitude in its dimension's canonical unit."""
        return self.magnitude * self.unit.factor

    @property
    def rendered(self) -> str:
        """The magnitude as a report would print it, thousands separated."""
        return f"{self.magnitude.normalize():,f}"

    def to(self, unit: Unit) -> Quantity:
        """The same figure expressed in another unit of the same dimension."""
        self._compatible(unit)
        return Quantity(self.canonical / unit.factor, unit)

    def __add__(self, other: Quantity) -> Quantity:
        return self._combined(other, operator.add)

    def __sub__(self, other: Quantity) -> Quantity:
        return self._combined(other, operator.sub)

    def __truediv__(self, other: Quantity) -> Quantity:
        """The ratio of two figures, its unit naming what the figure is per.

        Magnitudes are divided as printed rather than canonically, so the unit the
        result names is the unit the number is actually in.
        """
        if not other.magnitude:
            return self._refuse_zero(other)
        return Quantity(self.magnitude / other.magnitude, self._per(other.unit))

    def _combined(
        self, other: Quantity, combine: Callable[[Decimal, Decimal], Decimal]
    ) -> Quantity:
        converted: Quantity = other.to(self.unit)
        return Quantity(combine(self.magnitude, converted.magnitude), self.unit)

    def _compatible(self, unit: Unit) -> None:
        if unit.dimension != self.unit.dimension:
            raise IncompatibleUnitsError(
                f"{self.unit.symbol or self.unit.dimension} and "
                f"{unit.symbol or unit.dimension} do not combine"
            )

    def _per(self, unit: Unit) -> Unit:
        """The compound unit of a ratio, empty when the two units cancel out."""
        if unit == self.unit:
            return Unit("", Dimension.RATIO)
        return Unit(f"{self.unit.symbol}/{unit.symbol}", Dimension.RATIO)

    def _refuse_zero(self, other: Quantity) -> Quantity:
        raise IncompatibleUnitsError(
            f"{self.rendered} {self.unit.symbol} cannot be divided by zero {other.unit.symbol}"
        )


class ScaleReader:
    """Reads the scale a unit text declares, so the scale lives in the number."""

    def __init__(self, magnitudes: dict[str, float] | None = None) -> None:
        source: dict[str, float] = dict(MAGNITUDES if magnitudes is None else magnitudes)
        self._magnitudes: dict[str, Decimal] = {
            word: Decimal(str(factor)) for word, factor in source.items()
        }

    def read(self, text: str) -> Decimal:
        """The first scale word's factor, or one. Only whole words count, so ``Mt`` is not mega."""
        words: Sequence[str] = text.lower().replace("(", " ").replace(")", " ").split()
        factors: list[Decimal] = [self._magnitudes[word] for word in words if self._scale(word)]
        return factors[0] if factors else Decimal(1)

    def _scale(self, word: str) -> bool:
        """A single letter is a unit far more often than a scale, so it is not read as one."""
        return len(word) > 1 and word in self._magnitudes


class QuantityParser:
    """Turns the value and unit text an extraction carries into one typed quantity."""

    def __init__(
        self,
        registry: UnitRegistry | None = None,
        numbers: NumericParser | None = None,
        scales: ScaleReader | None = None,
    ) -> None:
        self._registry: UnitRegistry = registry or UnitRegistry()
        self._numbers: NumericParser = numbers or NumericParser()
        self._scales: ScaleReader = scales or ScaleReader()

    def parse(self, value: str, unit: str) -> Quantity | None:
        """The typed figure, or None when either the number or the unit cannot be read."""
        number: float | None = self._numbers.parse(value)
        resolved: Unit | None = self._registry.resolve(unit)
        if number is None or resolved is None:
            return None
        return Quantity(Decimal(str(number)) * self._scales.read(unit), resolved)
