"""Gate: a column that states another period is the wrong cell."""

import re
from typing import ClassVar

from ask.reading import Reading


class PeriodGate:
    """Refuses a value read from a column that states a period other than the one asked for.

    The asked-for period comes from the year filter, not from the question text, which
    usually contains no year. Only a column that actually states a period is judged: a
    ``Female`` column over a board count states none, so it cannot be wrong.
    """

    _YEAR: ClassVar[re.Pattern[str]] = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

    @classmethod
    def check(cls, reading: Reading, period: int | None) -> str:
        """Whether this reading's column agrees with the period asked for.

        Args:
            reading: The figure and the evidence for it.
            period: The year the caller filtered on, or None when they named no year.

        Returns:
            The refusal reason, empty when the column states no period or the right one.
        """
        stated: int | None = cls._stated(reading.column)
        if period is None or stated is None or stated == period:
            return ""
        return f"column states another period: {stated} not {period}"

    @classmethod
    def _stated(cls, column: str) -> int | None:
        """The period a column states, if it states one.

        Args:
            column: The column heading, quoted as the document writes it.

        Returns:
            The year, or None when the column names no period.
        """
        found: re.Match[str] | None = cls._YEAR.search(column)
        if found is None:
            return None
        return int(found.group(1))
