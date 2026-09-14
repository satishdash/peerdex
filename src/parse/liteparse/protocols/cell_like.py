"""One table cell."""

from typing import Protocol


class CellLike(Protocol):
    """One table cell."""

    @property
    def text(self) -> str:
        """The cell's text."""
