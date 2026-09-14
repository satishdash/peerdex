"""Decides whether an undifferentiated text run reads as a section heading."""

import re
from typing import ClassVar


class HeadingRule:
    """Decides whether an undifferentiated text run reads as a section heading.

    Returns the heading level, or zero when the text is ordinary prose.
    """

    _SENTENCE: ClassVar[re.Pattern[str]] = re.compile(r"\.\s+[A-Z]")
    _TERMINAL: ClassVar[frozenset[str]] = frozenset(".,:;")
    _MAX_HEADING_CHARS: ClassVar[int] = 120
    _MIN_HEADING_CHARS: ClassVar[int] = 2
    _MAX_DIGIT_RATIO: ClassVar[float] = 0.30
    _MIN_SHOUT_RATIO: ClassVar[float] = 0.60

    def level(self, text: str) -> int:
        """The heading level this text reads as, or 0 for prose.

        Args:
            text: The text being handled.

        Returns:
            The heading depth, or 0 when the text is prose.
        """
        stripped: str = text.strip()
        if not self._shaped(stripped):
            return 0
        return 1 if self._shouted(stripped) else 2

    def _shaped(self, text: str) -> bool:
        """Whether the text has the shape of a heading.

        Args:
            text: The text being handled.

        Returns:
            True when the text passes every shape rule.
        """
        return all(
            rule(text)
            for rule in (
                self._single_line,
                self._sized,
                self._unterminated,
                self._one_sentence,
                self._mostly_letters,
            )
        )

    @classmethod
    def _single_line(cls, text: str) -> bool:
        """Headings occupy one line.

        Args:
            text: The text being handled.

        Returns:
            True when the text occupies one line.
        """
        return "\n" not in text.strip()

    @classmethod
    def _sized(cls, text: str) -> bool:
        """Headings fall within the allowed length.

        Args:
            text: The text being handled.

        Returns:
            True when the length is within the allowed range.
        """
        return cls._MIN_HEADING_CHARS <= len(text) <= cls._MAX_HEADING_CHARS

    @classmethod
    def _unterminated(cls, text: str) -> bool:
        """Headings do not end in sentence punctuation.

        Args:
            text: The text being handled.

        Returns:
            True when the text does not end in sentence punctuation.
        """
        return bool(text) and text[-1] not in cls._TERMINAL

    @classmethod
    def _one_sentence(cls, text: str) -> bool:
        """Headings do not run to a second sentence.

        Args:
            text: The text being handled.

        Returns:
            True when the text holds no sentence break.
        """
        return cls._SENTENCE.search(text) is None

    @classmethod
    def _mostly_letters(cls, text: str) -> bool:
        """Headings are not mostly digits.

        Args:
            text: The text being handled.

        Returns:
            True when digits stay below the allowed ratio.
        """
        digits: int = sum(1 for char in text if char.isdigit())
        return digits / len(text) < cls._MAX_DIGIT_RATIO

    @classmethod
    def _shouted(cls, text: str) -> bool:
        """Whether the text is predominantly upper case.

        Args:
            text: The text being handled.

        Returns:
            True when upper-case letters dominate.
        """
        letters: int = sum(1 for char in text if char.isalpha())
        upper: int = sum(1 for char in text if char.isupper())
        return letters > 0 and upper / letters > cls._MIN_SHOUT_RATIO
