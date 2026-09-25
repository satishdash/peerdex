"""A table without the columns that add nothing."""

from dataclasses import replace

from chunk.table_headers import TableHeaders
from parse import TableBlock


class RedundantColumns:
    """Drops the columns that are blank, or copy their left neighbour, in every line.

    A merged cell repeats its text in every column it spans, and a sheet formatted out to
    its last column reports thousands of blank ones. Either way each column is rendered
    into every row of every chunk while saying nothing new.
    """

    @classmethod
    def dropped(cls, b: TableBlock) -> TableBlock:
        """The table with only the columns that add a cell or a real column name.

        Args:
            b: The table block.

        Returns:
            The narrowed table, or the table unchanged when no column adds anything.
        """
        keep: list[int] = cls._kept(b)
        if not keep:
            return b
        headers: list[str] = cls._picked(b.headers, keep) if b.headers else []
        return replace(b, headers=headers, rows=[cls._picked(r, keep) for r in b.rows])

    @classmethod
    def _kept(cls, b: TableBlock) -> list[int]:
        """Indexes of the columns worth rendering.

        Args:
            b: The table block.

        Returns:
            Each column where some row, or a non-positional name, adds something.
        """
        named: list[str] = [
            "" if TableHeaders.POSITIONAL.match(h.strip()) else h for h in b.headers
        ]
        width: int = max([len(b.headers), *(len(r) for r in b.rows)])
        return [i for i in range(width) if any(cls._adds(line, i) for line in (named, *b.rows))]

    @classmethod
    def _adds(cls, cells: list[str], i: int) -> bool:
        """Whether a line holds something at a column that its left neighbour does not.

        Args:
            cells: One row, or the column names.
            i: The column index.

        Returns:
            True when the cell is filled and differs from the one before it.
        """
        cell: str = cls._at(cells, i)
        return bool(cell) and (i == 0 or cell != cls._at(cells, i - 1))

    @staticmethod
    def _at(cells: list[str], i: int) -> str:
        """The stripped cell at a column, blank past the end of a short line.

        Args:
            cells: One row, or the column names.
            i: The column index.

        Returns:
            The cell text.
        """
        return (cells[i] or "").strip() if i < len(cells) else ""

    @staticmethod
    def _picked(cells: list[str], keep: list[int]) -> list[str]:
        """One line narrowed to the kept columns.

        Args:
            cells: One row, or the column names.
            keep: The column indexes to keep.

        Returns:
            The kept cells, blank where a short row has none.
        """
        return [cells[i] if i < len(cells) else "" for i in keep]
