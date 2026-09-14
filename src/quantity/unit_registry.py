"""Resolves the unit text printed beside a figure to one typed unit."""

import re
from collections.abc import Mapping
from decimal import Decimal
from itertools import pairwise
from typing import ClassVar

from quantity.dimension import Dimension
from quantity.unit import Unit


class UnitRegistry:
    """Resolves the unit text printed beside a figure to one typed unit."""

    UNITS: ClassVar[tuple[Unit, ...]] = (
        Unit("t", Dimension.MASS, Decimal(1)),
        Unit("kg", Dimension.MASS, Decimal("0.001")),
        Unit("kt", Dimension.MASS, Decimal(1000)),
        Unit("Mt", Dimension.MASS, Decimal(1000000)),
        Unit("GJ", Dimension.ENERGY, Decimal(1)),
        Unit("MJ", Dimension.ENERGY, Decimal("0.001")),
        Unit("TJ", Dimension.ENERGY, Decimal(1000)),
        Unit("PJ", Dimension.ENERGY, Decimal(1000000)),
        Unit("kWh", Dimension.ENERGY, Decimal("0.0036")),
        Unit("MWh", Dimension.ENERGY, Decimal("3.6")),
        Unit("GWh", Dimension.ENERGY, Decimal(3600)),
        Unit("TWh", Dimension.ENERGY, Decimal(3600000)),
        Unit("m3", Dimension.VOLUME, Decimal(1)),
        Unit("L", Dimension.VOLUME, Decimal("0.001")),
        Unit("ML", Dimension.VOLUME, Decimal(1000)),
        Unit("%", Dimension.FRACTION, Decimal(1)),
        Unit("", Dimension.COUNT, Decimal(1)),
    )
    BY_SYMBOL: ClassVar[Mapping[str, Unit]] = {unit.symbol: unit for unit in UNITS}
    ALIASES: ClassVar[Mapping[str, str]] = {
        "t": "t",
        "ton": "t",
        "tons": "t",
        "tonne": "t",
        "tonnes": "t",
        "metric ton": "t",
        "metric tons": "t",
        "metric tonne": "t",
        "metric tonnes": "t",
        "tco2e": "t",
        "kg": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "kt": "kt",
        "kilotonne": "kt",
        "kilotonnes": "kt",
        "mt": "Mt",
        "megatonne": "Mt",
        "megatonnes": "Mt",
        "gj": "GJ",
        "gigajoule": "GJ",
        "gigajoules": "GJ",
        "mj": "MJ",
        "megajoule": "MJ",
        "megajoules": "MJ",
        "tj": "TJ",
        "terajoule": "TJ",
        "terajoules": "TJ",
        "pj": "PJ",
        "petajoule": "PJ",
        "petajoules": "PJ",
        "kwh": "kWh",
        "kilowatt hour": "kWh",
        "kilowatt hours": "kWh",
        "mwh": "MWh",
        "megawatt hour": "MWh",
        "megawatt hours": "MWh",
        "gwh": "GWh",
        "gigawatt hour": "GWh",
        "gigawatt hours": "GWh",
        "twh": "TWh",
        "terawatt hour": "TWh",
        "terawatt hours": "TWh",
        "m3": "m3",
        "cubic metre": "m3",
        "cubic metres": "m3",
        "cubic meter": "m3",
        "cubic meters": "m3",
        "l": "L",
        "litre": "L",
        "litres": "L",
        "liter": "L",
        "liters": "L",
        "ml": "ML",
        "megalitre": "ML",
        "megalitres": "ML",
        "megaliter": "ML",
        "megaliters": "ML",
        "%": "%",
        "percent": "%",
        "percentage": "%",
    }

    _DENOMINATOR: ClassVar[re.Pattern[str]] = re.compile(r"(^|[\s(])per([\s)]|$)|/")
    _BRACKETED: ClassVar[re.Pattern[str]] = re.compile(r"\(([^()]+)\)")
    _EXPONENT: ClassVar[Mapping[str, str]] = {"²": "2", "³": "3"}
    _SPACED_EXPONENT: ClassVar[re.Pattern[str]] = re.compile(r"(?<=[a-z])\s+(?=\d)")
    _WORD: ClassVar[re.Pattern[str]] = re.compile(r"[a-z0-9%]+")

    def resolve(self, text: str) -> Unit | None:
        """The unit that text names, or None when it names none or names a denominator.

        Any scale word is ignored here: a scale belongs to the number, so
        ``QuantityParser`` folds it into the magnitude instead.

        Args:
            text: The unit text printed beside the figure.

        Returns:
            The unit, or None.
        """
        if self._DENOMINATOR.search(text.lower()):
            return None
        exact: Unit | None = self.BY_SYMBOL.get(text.strip())
        return exact if exact is not None else self._by_words(self._normalised(text))

    def _by_words(self, normalised: str) -> Unit | None:
        """The first spelling in the text that names a unit, longest phrase first.

        Args:
            normalised: The unit text, lowercased and tidied.

        Returns:
            The unit, or None when no spelling names one.
        """
        words: list[str] = self._WORD.findall(normalised)
        phrases: list[str] = [
            *(f"{first} {second}" for first, second in pairwise(words)),
            *words,
        ]
        symbols: list[str] = [self.ALIASES[p] for p in phrases if p in self.ALIASES]
        return self.BY_SYMBOL[symbols[0]] if symbols else self._empty(normalised)

    @classmethod
    def _empty(cls, normalised: str) -> Unit | None:
        """No unit at all is a count; unrecognised words are not.

        Args:
            normalised: The unit text, lowercased and tidied.

        Returns:
            The count unit when the text is blank, otherwise None.
        """
        return cls.BY_SYMBOL[""] if not normalised.strip() else None

    @classmethod
    def _normalised(cls, text: str) -> str:
        """Lowercased, with a bracketed symbol preferred and ``m 3`` read as ``m3``.

        Args:
            text: The unit text printed beside the figure.

        Returns:
            The tidied text.
        """
        bracketed: re.Match[str] | None = cls._BRACKETED.search(text)
        chosen: str = bracketed[1] if bracketed is not None else text
        lowered: str = chosen.lower()
        for superscript, digit in cls._EXPONENT.items():
            lowered = lowered.replace(superscript, digit)
        return cls._SPACED_EXPONENT.sub("", lowered)
