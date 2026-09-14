"""Greedy packing of rendered blocks into groups that each fit a token budget."""

from chunk.tokenizer import Tokenizer


class GreedyPacker:
    """Groups rendered blocks so each group fits a token budget."""

    def __init__(self, preamble: str, budget: int, carryover: int = 0) -> None:
        """Start an empty packer.

        Args:
            preamble: Text every group opens with.
            budget: Tokens a group may hold beyond the preamble.
            carryover: What the preamble costs a group it is repeated into.
        """
        self._preamble: str = preamble
        self._budget: int = budget
        self._carryover: int = carryover
        self._buffer: list[str] = []
        self._used: int = 0
        self._groups: list[str] = []

    def add(self, line: str) -> None:
        """Take one rendered block, closing the open group first when it would overflow.

        Args:
            line: The rendered block.
        """
        cost: int = Tokenizer.count(line)
        if self._buffer and self._used + cost > self._budget:
            self._close()
        self._buffer.append(line)
        self._used += cost

    def groups(self) -> list[str]:
        """Close the open group and return every group rendered with its preamble.

        Returns:
            Every group, each opening with the preamble.
        """
        self._close()
        return self._groups

    def _close(self) -> None:
        """Bank the open group, unless nothing landed in it."""
        if not self._buffer:
            return
        self._groups.append(self._preamble + "\n".join(self._buffer))
        self._buffer = []
        self._used = self._carryover
