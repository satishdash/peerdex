"""One figure in one unit, comparable and combinable with another of its dimension."""

import operator
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from quantity.dimension import Dimension
from quantity.incompatible_units_error import IncompatibleUnitsError
from quantity.unit import Unit


@dataclass(frozen=True)
class Quantity:
    """One figure in one unit, comparable and combinable with another of its dimension."""

    magnitude: Decimal
    unit: Unit

    @property
    def canonical(self) -> Decimal:
        """The magnitude in its dimension's canonical unit.

        Returns:
            The canonical magnitude.
        """
        return self.magnitude * self.unit.factor

    @property
    def rendered(self) -> str:
        """The magnitude as a report would print it, thousands separated.

        Returns:
            The rendered magnitude.
        """
        return f"{self.magnitude.normalize():,f}"

    def to(self, unit: Unit) -> Quantity:
        """The same figure expressed in another unit of the same dimension.

        Args:
            unit: The unit to express it in.

        Returns:
            The converted quantity.
        """
        self._compatible(unit)
        return Quantity(self.canonical / unit.factor, unit)

    def __add__(self, other: Quantity) -> Quantity:
        """Add another figure, converting it into this one's unit first.

        Args:
            other: The figure to add.

        Returns:
            The total, in this figure's unit.
        """
        return self._combined(other, operator.add)

    def __sub__(self, other: Quantity) -> Quantity:
        """Subtract another figure, converting it into this one's unit first.

        Args:
            other: The figure to subtract.

        Returns:
            The difference, in this figure's unit.
        """
        return self._combined(other, operator.sub)

    def __truediv__(self, other: Quantity) -> Quantity:
        """The ratio of two figures, its unit naming what the figure is per.

        Magnitudes are divided as printed rather than canonically, so the unit the
        result names is the unit the number is actually in.

        Args:
            other: The figure to divide by.

        Returns:
            The ratio.
        """
        if not other.magnitude:
            return self._refuse_zero(other)
        return Quantity(self.magnitude / other.magnitude, self._per(other.unit))

    def _combined(
        self, other: Quantity, combine: Callable[[Decimal, Decimal], Decimal]
    ) -> Quantity:
        """Two figures combined in this one's unit.

        Args:
            other: The other figure.
            combine: How to combine the two magnitudes.

        Returns:
            The combined quantity.
        """
        converted: Quantity = other.to(self.unit)
        return Quantity(combine(self.magnitude, converted.magnitude), self.unit)

    def _compatible(self, unit: Unit) -> None:
        """Refuse a unit from another dimension.

        Args:
            unit: The unit to check.

        Raises:
            IncompatibleUnitsError: If the unit belongs to another dimension.
        """
        if unit.dimension != self.unit.dimension:
            raise IncompatibleUnitsError(
                f"{self.unit.symbol or self.unit.dimension} and "
                f"{unit.symbol or unit.dimension} do not combine"
            )

    def _per(self, unit: Unit) -> Unit:
        """The compound unit of a ratio, empty when the two units cancel out.

        Args:
            unit: The divisor's unit.

        Returns:
            The ratio's unit.
        """
        if unit == self.unit:
            return Unit("", Dimension.RATIO)
        return Unit(f"{self.unit.symbol}/{unit.symbol}", Dimension.RATIO)

    def _refuse_zero(self, other: Quantity) -> Quantity:
        """Refuse a division by zero.

        Args:
            other: The zero divisor.

        Raises:
            IncompatibleUnitsError: Always.
        """
        raise IncompatibleUnitsError(
            f"{self.rendered} {self.unit.symbol} cannot be divided by zero {other.unit.symbol}"
        )
