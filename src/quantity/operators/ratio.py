"""Divides the first operand by the second."""

from collections.abc import Sequence

from quantity.operators.operator import Operator
from quantity.quantity import Quantity


class Ratio(Operator):
    """Divides the first operand by the second."""

    def accepts(self, count: int) -> bool:
        """Whether division is defined for that many operands.

        Args:
            count: How many operands were extracted.

        Returns:
            Whether there are exactly two.
        """
        return count == 2

    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        """Divide the first operand by the second.

        Args:
            parts: The operands, in the order the question named them.

        Returns:
            The ratio, its unit derived from the two.
        """
        return parts[0] / parts[1]
