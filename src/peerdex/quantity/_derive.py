"""Deriving a figure the report does not print, only where the question asks for it.

The extractor is told never to compute, because a computed figure is
indistinguishable from a fabricated one. This module is the single exception: a
question that spells its own arithmetic out - "Total GHG emissions (Scope 1 +
Scope 2 + Scope 3)" - has asked for the combination, and the operands it names
are the only ones used.

Nothing is derived from a question that merely sounds derived. "Water intensity
ratio per revenue" names no operands, so it is left to the extractor.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import reduce
from typing import Final, Literal

from peerdex.quantity._quantity import IncompatibleUnitsError, Quantity
from peerdex.shared.logging import get_logger

log = get_logger("quantity.derive")

type Operation = Literal["sum", "difference", "ratio"]


@dataclass(frozen=True)
class Derivation:
    """The arithmetic a question spelled out: what to do, and to which named operands."""

    operation: Operation
    operands: tuple[str, ...]


class Operator(ABC):
    """Strategy: one arithmetic combination of typed quantities."""

    @abstractmethod
    def accepts(self, count: int) -> bool:
        """Whether this operation is defined for that many operands."""

    @abstractmethod
    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        """Combine the operands, raising ``IncompatibleUnitsError`` when they do not combine."""


class Sum(Operator):
    """Adds every operand, in the unit of the first."""

    def accepts(self, count: int) -> bool:
        return count >= 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        return reduce(lambda total, part: total + part, parts)


class Difference(Operator):
    """Subtracts the second operand from the first."""

    def accepts(self, count: int) -> bool:
        return count == 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        return parts[0] - parts[1]


class Ratio(Operator):
    """Divides the first operand by the second."""

    def accepts(self, count: int) -> bool:
        return count == 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        return parts[0] / parts[1]


_OPERATORS: Final[Mapping[Operation, Operator]] = {
    "sum": Sum(),
    "difference": Difference(),
    "ratio": Ratio(),
}
_SYMBOLS: Final[Mapping[str, Operation]] = {"+": "sum", "-": "difference", "/": "ratio"}
_BRACKETED: Final[re.Pattern[str]] = re.compile(r"\(([^()]+)\)")


class ArithmeticQuestion:
    """Reads the arithmetic a question spells out inside brackets, or nothing.

    Only a bracketed expression counts, and only one carrying a single kind of
    operator: a dash in a plain label ("Scope 3 - category 1") is punctuation, and
    treating it as a subtraction would overrule a printed figure with a guess.
    """

    def read(self, question: str) -> Derivation | None:
        """The derivation the question asks for, or None when it asks for none."""
        return next(
            (
                derivation
                for inner in self._brackets(question)
                if (derivation := self._derivation(inner)) is not None
            ),
            None,
        )

    def _derivation(self, inner: str) -> Derivation | None:
        symbols: list[str] = [symbol for symbol in _SYMBOLS if symbol in inner]
        if len(symbols) != 1:
            return None
        operands: tuple[str, ...] = tuple(part.strip() for part in inner.split(symbols[0]))
        return self._checked(_SYMBOLS[symbols[0]], operands)

    @staticmethod
    def _checked(operation: Operation, operands: tuple[str, ...]) -> Derivation | None:
        if len(operands) < 2 or not all(operands):
            return None
        return Derivation(operation=operation, operands=operands)

    @staticmethod
    def _brackets(question: str) -> list[str]:
        return _BRACKETED.findall(question)


class DerivationEngine:
    """Performs the arithmetic a question spelled out, or refuses to answer at all."""

    def __init__(self, operators: Mapping[Operation, Operator] | None = None) -> None:
        self._operators: Mapping[Operation, Operator] = operators or _OPERATORS

    def combine(self, derivation: Derivation, parts: Sequence[Quantity | None]) -> Quantity | None:
        """The derived figure, or None when any operand is missing or will not combine."""
        present: list[Quantity] = [part for part in parts if part is not None]
        if len(present) != len(parts):
            log.info(f"[derive] refused: {len(parts) - len(present)} operand(s) not found")
            return None
        return self._performed(derivation, present)

    def _performed(self, derivation: Derivation, parts: Sequence[Quantity]) -> Quantity | None:
        strategy: Operator | None = self._operators.get(derivation.operation)
        if strategy is None or not strategy.accepts(len(parts)):
            return None
        return self._applied(strategy, parts)

    @staticmethod
    def _applied(strategy: Operator, parts: Sequence[Quantity]) -> Quantity | None:
        try:
            return strategy.apply(parts)
        except IncompatibleUnitsError as error:
            log.info(f"[derive] refused: {error}")
            return None
