"""Strategy: one arithmetic combination of typed quantities."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from quantity.quantity import Quantity


class Operator(ABC):
    """Strategy: one arithmetic combination of typed quantities."""

    @abstractmethod
    def accepts(self, count: int) -> bool:
        """Whether this operation is defined for that many operands.

        Args:
            count: How many operands were extracted.

        Returns:
            Whether the operation applies.
        """

    @abstractmethod
    def apply(self, parts: Sequence[Quantity]) -> Quantity:
        """Combine the operands.

        Args:
            parts: The operands, in the order the question named them.

        Returns:
            The combined quantity.

        Raises:
            IncompatibleUnitsError: If the operands do not share a dimension.
        """
