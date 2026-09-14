"""Gate: a quantitative answer is a bare number."""

import re
from typing import ClassVar

from ask.reading import Reading


class NumberGate:
    """Refuses anything that is not a bare number.

    A quantitative answer is the value alone. A hedge, a dash or a note that the figure
    was not stated is a refusal, not an answer.
    """

    _BARE: ClassVar[re.Pattern[str]] = re.compile(r"^-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")

    @classmethod
    def check(cls, reading: Reading) -> str:
        """Whether this reading's value is a number the document wrote.

        Thousands separators and decimals are how a document writes a number, so both
        are allowed; words and blanks are not.

        Args:
            reading: The figure and the evidence for it.

        Returns:
            The refusal reason, empty when the value is a bare number.
        """
        if cls._BARE.match(reading.value.strip()):
            return ""
        return f"value is not a bare number: {reading.value!r}"
