"""Subtracts the second operand from the first."""

from collections.abc import Sequence

from quantity.operators.operator import Operator
from quantity.quantity import Quantity


class Difference(Operator):
    """Subtracts the second operand from the first."""

    def accepts(self, count: int) -> bool:
        """Whether subtraction is defined for that many operands.

        Args:
            count: How many operands were extracted.

        Returns:
            Whether there are exactly two.
        """
        return count == 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        """Subtract the second operand from the first.

        Args:
            parts: The operands, in the order the question named them.

        Returns:
            The difference, in the unit of the first operand.
        """
        return parts[0] - parts[1]
