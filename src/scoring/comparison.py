"""Outcome of one oracle-vs-answer comparison, with the numbers compared."""

from dataclasses import dataclass
from typing import Literal

type Category = Literal["match", "mismatch", "scale_mismatch", "missed", "abstained", "extra"]


@dataclass(frozen=True)
class Comparison:
    """Outcome of one oracle-vs-answer comparison, with the numbers compared."""

    category: Category
    expected_number: float | None
    actual_number: float | None
    scale: float | None = None
