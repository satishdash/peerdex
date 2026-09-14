"""The arithmetic a question spelled out: what to do, and to which named operands."""

from dataclasses import dataclass
from typing import Literal

type Operation = Literal["sum", "difference", "ratio"]


@dataclass(frozen=True)
class Derivation:
    """The arithmetic a question spelled out: what to do, and to which named operands."""

    operation: Operation
    operands: tuple[str, ...]
