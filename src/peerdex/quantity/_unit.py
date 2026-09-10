"""Units of measure as printed in reports, typed so two figures can be combined.

A unit is what a figure measures plus how big it is against that dimension's
canonical unit: tonnes for mass, gigajoules for energy, cubic metres for volume.
Energy is canonically GJ rather than MWh so every factor stays an exact decimal -
1 MWh is 3.6 GJ, while 1 GJ is 0.2777... MWh and would round on every conversion.

Only a bare unit resolves. Text naming a denominator ("tonnes per employee",
"MWh/m2") is refused, because the denominator cannot be typed from that text and
reading only the numerator would silently retype an intensity as a total.

Two lowercase spellings collide and are resolved the way corporate reports use
them: ``mt`` is a megatonne, not a metric ton, and ``ml`` a megalitre, not a
millilitre. Exact-case ``Mt`` and ``ML`` mean the same thing, so only an
unconventional spelling is affected.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Final


class Dimension(StrEnum):
    """What a figure measures. Figures combine only inside one dimension."""

    MASS = "mass"
    ENERGY = "energy"
    VOLUME = "volume"
    COUNT = "count"
    FRACTION = "fraction"
    RATIO = "ratio"


@dataclass(frozen=True)
class Unit:
    """One printed unit: what it measures, and its size against the canonical one."""

    symbol: str
    dimension: Dimension
    factor: Decimal = Decimal(1)


_UNITS: Final[tuple[Unit, ...]] = (
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

_BY_SYMBOL: Final[Mapping[str, Unit]] = {unit.symbol: unit for unit in _UNITS}

_ALIASES: Final[Mapping[str, str]] = {
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

_DENOMINATOR: Final[re.Pattern[str]] = re.compile(r"(^|[\s(])per([\s)]|$)|/")
_BRACKETED: Final[re.Pattern[str]] = re.compile(r"\(([^()]+)\)")
_EXPONENT: Final[Mapping[str, str]] = {"²": "2", "³": "3"}
_SPACED_EXPONENT: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z])\s+(?=\d)")
_WORD: Final[re.Pattern[str]] = re.compile(r"[a-z0-9%]+")


class UnitRegistry:
    """Resolves the unit text printed beside a figure to one typed unit."""

    def resolve(self, text: str) -> Unit | None:
        """The unit that text names, or None when it names none or names a denominator.

        Any scale word is ignored here: a scale belongs to the number, so
        ``QuantityParser`` folds it into the magnitude instead.
        """
        if _DENOMINATOR.search(text.lower()):
            return None
        exact: Unit | None = _BY_SYMBOL.get(text.strip())
        return exact if exact is not None else self._by_words(self._normalised(text))

    def _by_words(self, normalised: str) -> Unit | None:
        """The first spelling in the text that names a unit, longest phrase first."""
        words: list[str] = _WORD.findall(normalised)
        phrases: list[str] = [
            *(f"{first} {second}" for first, second in pairwise(words)),
            *words,
        ]
        symbols: list[str] = [_ALIASES[phrase] for phrase in phrases if phrase in _ALIASES]
        return _BY_SYMBOL[symbols[0]] if symbols else self._empty(normalised)

    @staticmethod
    def _empty(normalised: str) -> Unit | None:
        """No unit at all is a count; unrecognised words are not."""
        return _BY_SYMBOL[""] if not normalised.strip() else None

    @staticmethod
    def _normalised(text: str) -> str:
        """Lowercased, with a bracketed symbol preferred and ``m 3`` read as ``m3``."""
        bracketed: re.Match[str] | None = _BRACKETED.search(text)
        chosen: str = bracketed[1] if bracketed is not None else text
        lowered: str = chosen.lower()
        for superscript, digit in _EXPONENT.items():
            lowered = lowered.replace(superscript, digit)
        return _SPACED_EXPONENT.sub("", lowered)
