"""Performs the arithmetic a question spelled out, or refuses to answer at all."""

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from quantity.derivation import Derivation, Operation
from quantity.incompatible_units_error import IncompatibleUnitsError
from quantity.operators.difference import Difference
from quantity.operators.operator import Operator
from quantity.operators.ratio import Ratio
from quantity.operators.sum import Sum
from quantity.quantity import Quantity
from shared.logging import Logging


class DerivationEngine:
    """Performs the arithmetic a question spelled out, or refuses to answer at all."""

    _LOG: ClassVar[Any] = Logging.get("quantity.derive")
    _OPERATORS: ClassVar[Mapping[Operation, Operator]] = {
        "sum": Sum(),
        "difference": Difference(),
        "ratio": Ratio(),
    }

    def __init__(self, operators: Mapping[Operation, Operator] | None = None) -> None:
        """Bind to the operators this engine may apply.

        Args:
            operators: The operator per operation, or None for the standard set.
        """
        self._operators: Mapping[Operation, Operator] = operators or self._OPERATORS

    def combine(self, derivation: Derivation, parts: Sequence[Quantity | None]) -> Quantity | None:
        """The derived figure, or None when any operand is missing or will not combine.

        Args:
            derivation: The arithmetic the question spelled out.
            parts: One quantity per operand, None where an operand was not found.

        Returns:
            The combined quantity, or None.
        """
        present: list[Quantity] = [part for part in parts if part is not None]
        if len(present) != len(parts):
            self._LOG.info(f"[derive] refused: {len(parts) - len(present)} operand(s) not found")
            return None
        return self._performed(derivation, present)

    def _performed(self, derivation: Derivation, parts: Sequence[Quantity]) -> Quantity | None:
        """The operation applied, when one is defined for that many operands.

        Args:
            derivation: The arithmetic the question spelled out.
            parts: The operands, all present.

        Returns:
            The combined quantity, or None when the operation does not apply.
        """
        strategy: Operator | None = self._operators.get(derivation.operation)
        if strategy is None or not strategy.accepts(len(parts)):
            return None
        return self._applied(strategy, parts)

    @classmethod
    def _applied(cls, strategy: Operator, parts: Sequence[Quantity]) -> Quantity | None:
        """One operator applied, refusing when the operands do not share a dimension.

        Args:
            strategy: The operator to apply.
            parts: The operands.

        Returns:
            The combined quantity, or None when the units do not combine.
        """
        try:
            return strategy.apply(parts)
        except IncompatibleUnitsError as error:
            cls._LOG.info(f"[derive] refused: {error}")
            return None
