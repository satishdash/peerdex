"""One figure read out of the passages, with the evidence for it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Reading:
    """A value and the evidence for it: which row it came from, and which column.

    The label and column exist so the next stage can catch the model out. Asking a
    model whether it was right returns yes; asking which row and column it read
    returns something testable.
    """

    value: str
    unit: str
    label: str
    column: str
