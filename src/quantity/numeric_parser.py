"""The leading number in a piece of text, with any magnitude word folded in."""

import re
from collections.abc import Mapping
from typing import ClassVar, Final

from quantity.magnitudes import Magnitudes


class NumericParser:
    """Extracts the leading numeric quantity, folding a trailing magnitude word into it."""

    _NUMBER: ClassVar[Final[re.Pattern[str]]] = re.compile(
        r"(?<![A-Za-z0-9])(?P<paren>\()?\s*(?P<sign>[-\u2212])?\s*[$€£¥]?\s*"
        r"(?P<num>\d[\d,]*(?:\.\d+)?)"
    )
    _MAGNITUDE_WORD: ClassVar[Final[re.Pattern[str]]] = re.compile(r"\s*(?P<word>[A-Za-z]+)")
    _LENGTH_FOLLOWERS: ClassVar[frozenset[str]] = frozenset({"/", "²", "³"})

    def __init__(self, magnitudes: Mapping[str, float] | None = None) -> None:
        """Bind to a magnitude table.

        Args:
            magnitudes: The words that scale a number, or None for the standard set.
        """
        self._magnitudes: dict[str, float] = dict(
            Magnitudes.TABLE if magnitudes is None else magnitudes
        )

    def parse(self, text: str) -> float | None:
        """The first number in the text, honouring signs, parentheses and separators.

        Args:
            text: The text to read.

        Returns:
            The value, or None when the text holds no number.
        """
        match: re.Match[str] | None = self._NUMBER.search(text)
        return None if match is None else self._value(text, match)

    def parse_all(self, text: str) -> list[float]:
        """Every standalone number in the text.

        Args:
            text: The text to read.

        Returns:
            The values, in order of appearance.
        """
        return [self._value(text, match) for match in self._NUMBER.finditer(text)]

    def _value(self, text: str, match: re.Match[str]) -> float:
        """One matched number as a value.

        Args:
            text: The text being read.
            match: The number's match.

        Returns:
            The value, negative when parenthesised or signed.
        """
        value: float = float(match["num"].replace(",", "")) * self._magnitude(text, match.end())
        negative: bool = bool(match["paren"] or match["sign"])
        return -value if negative else value

    def _magnitude(self, text: str, offset: int) -> float:
        """The multiplier a trailing word applies, if it applies one.

        A trailing word scales the value only when it is known and is not a length
        unit such as m3, m2 or m/s.

        Args:
            text: The text being read.
            offset: Where the number ended.

        Returns:
            The multiplier, or one when no magnitude word follows.
        """
        word: re.Match[str] | None = self._MAGNITUDE_WORD.match(text, offset)
        if word is None or self._is_length_unit(text, word.end()):
            return 1.0
        return self._magnitudes.get(word["word"].lower(), 1.0)

    @classmethod
    def _is_length_unit(cls, text: str, end: int) -> bool:
        """Whether the word that follows a number is a length unit rather than a magnitude.

        Args:
            text: The text being read.
            end: Where the word ended.

        Returns:
            Whether it reads as a length unit.
        """
        follower: str = text[end : end + 1]
        return follower.isdigit() or follower in cls._LENGTH_FOLLOWERS
