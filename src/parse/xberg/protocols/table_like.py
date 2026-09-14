"""One native table with its cells."""

from typing import Protocol


class TableLike(Protocol):
    """One native table with its cells."""

    @property
    def cells(self) -> list[list[str]] | None:
        """The table's cells, row-major."""

    @property
    def page_number(self) -> int | None:
        """The page this table sits on."""
