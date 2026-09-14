"""A table's real column names, told apart from an extractor's positional ones."""

import re
from typing import ClassVar

from parse import TableBlock


class TableHeaders:
    """Tells a table's real column names apart from an extractor's positional ones."""

    POSITIONAL: ClassVar[re.Pattern[str]] = re.compile(r"^(?:col)?\d+$")

    @classmethod
    def split(cls, b: TableBlock) -> tuple[list[str], list[list[str]]]:
        """Column names plus the rows beneath them.

        Extractors that number their columns carry the real names in the first row, so a
        row group headed by ``0 | 1 | 2`` would never say which year a value belongs to.

        Args:
            b: The table block.

        Returns:
            The column names and the rows they head.
        """
        headers: list[str] = list(b.headers or [])
        if headers and not all(cls.POSITIONAL.match(h.strip()) for h in headers):
            return headers, list(b.rows)
        if b.rows:
            return list(b.rows[0]), list(b.rows[1:])
        return headers, list(b.rows)
