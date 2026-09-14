"""Adds every operand, in the unit of the first."""

from collections.abc import Sequence
from functools import reduce

from quantity.operators.operator import Operator
from quantity.quantity import Quantity


class Sum(Operator):
    """Adds every operand, in the unit of the first."""

    def accepts(self, count: int) -> bool:
        """Whether adding is defined for that many operands.

        Args:
            count: How many operands were extracted.

        Returns:
            Whether there are at least two to add.
        """
        return count >= 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        """Add every operand.

        Args:
            parts: The operands, in the order the question named them.

        Returns:
            The total, in the unit of the first operand.
        """
        return reduce(lambda total, part: total + part, parts)
