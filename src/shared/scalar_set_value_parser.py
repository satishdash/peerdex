"""Comma-separated alternatives for one CLI key."""

import re
from typing import ClassVar

from shared.metadata import Scalar
from shared.scalar_value_parser import ScalarValueParser
from shared.value_parser import ValueParser


class ScalarSetValueParser(ValueParser[tuple[Scalar, ...]]):
    r"""Comma-separated alternatives; ``\,`` escapes a comma, mixed types fall back to text."""

    _SEPARATOR: ClassVar[re.Pattern[str]] = re.compile(r"(?<!\\),")

    def __init__(self) -> None:
        """Parse each alternative with the scalar parser."""
        self._member: ScalarValueParser = ScalarValueParser()

    def parse(self, raw: str) -> tuple[Scalar, ...]:
        """Every alternative given for one key.

        Args:
            raw: The text right of ``=``.

        Returns:
            The typed alternatives, all text when their types disagree.
        """
        parts: list[str] = [part.replace("\\,", ",") for part in self._SEPARATOR.split(raw)]
        typed: tuple[Scalar, ...] = tuple(self._member.parse(part) for part in parts)
        return typed if len({type(value) for value in typed}) == 1 else tuple(parts)
