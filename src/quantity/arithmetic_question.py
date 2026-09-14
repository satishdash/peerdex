"""Reads the arithmetic a question spells out inside brackets, or nothing."""

import re
from collections.abc import Mapping
from typing import ClassVar

from quantity.derivation import Derivation, Operation


class ArithmeticQuestion:
    """Reads the arithmetic a question spells out inside brackets, or nothing.

    Only a bracketed expression counts, and only one carrying a single kind of
    operator: a dash in a plain label ("Scope 3 - category 1") is punctuation, and
    treating it as a subtraction would overrule a printed figure with a guess.
    """

    _SYMBOLS: ClassVar[Mapping[str, Operation]] = {
        "+": "sum",
        "-": "difference",
        "/": "ratio",
    }
    _BRACKETED: ClassVar[re.Pattern[str]] = re.compile(r"\(([^()]+)\)")

    def read(self, question: str) -> Derivation | None:
        """The derivation the question asks for, or None when it asks for none.

        Args:
            question: The question as the caller asked it.

        Returns:
            The derivation, or None.
        """
        return next(
            (
                derivation
                for inner in self._brackets(question)
                if (derivation := self._derivation(inner)) is not None
            ),
            None,
        )

    def _derivation(self, inner: str) -> Derivation | None:
        """One bracketed expression as a derivation, when it names exactly one operator.

        Args:
            inner: The text inside one pair of brackets.

        Returns:
            The derivation, or None when it names no single operator.
        """
        symbols: list[str] = [symbol for symbol in self._SYMBOLS if symbol in inner]
        if len(symbols) != 1:
            return None
        operands: tuple[str, ...] = tuple(part.strip() for part in inner.split(symbols[0]))
        return self._checked(self._SYMBOLS[symbols[0]], operands)

    @staticmethod
    def _checked(operation: Operation, operands: tuple[str, ...]) -> Derivation | None:
        """The derivation, unless an operand is missing or blank.

        Args:
            operation: The arithmetic named.
            operands: The names either side of the operator.

        Returns:
            The derivation, or None when the operands do not stand up.
        """
        if len(operands) < 2 or not all(operands):
            return None
        return Derivation(operation=operation, operands=operands)

    @classmethod
    def _brackets(cls, question: str) -> list[str]:
        """Every bracketed expression in the question.

        Args:
            question: The question as the caller asked it.

        Returns:
            The text inside each pair of brackets.
        """
        return cls._BRACKETED.findall(question)
