"""One printed unit: what it measures, and its size against the canonical one."""

from dataclasses import dataclass
from decimal import Decimal

from quantity.dimension import Dimension


@dataclass(frozen=True)
class Unit:
    """One printed unit: what it measures, and its size against the canonical one."""

    symbol: str
    dimension: Dimension
    factor: Decimal = Decimal(1)
