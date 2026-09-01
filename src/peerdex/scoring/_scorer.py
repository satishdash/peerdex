"""Pure answer-accuracy comparison of model answers against oracle values. No IO."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

type Category = Literal["match", "mismatch", "scale_mismatch", "missed", "abstained", "extra"]

_NUMBER: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9])(?P<paren>\()?\s*(?P<sign>[-\u2212])?\s*[$€£¥]?\s*(?P<num>\d[\d,]*(?:\.\d+)?)"
)


_MAGNITUDE_WORD: re.Pattern[str] = re.compile(r"\s*(?P<word>[A-Za-z]+)")

MAGNITUDES: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "tn": 1e12,
    "trillion": 1e12,
}


@dataclass(frozen=True)
class Comparison:
    """Outcome of one oracle-vs-answer comparison, with the numbers compared."""

    category: Category
    expected_number: float | None
    actual_number: float | None
    scale: float | None = None


class NumericParser:
    """Extracts the leading numeric quantity, folding a trailing magnitude word into it."""

    def __init__(self, magnitudes: Mapping[str, float] | None = None) -> None:
        self._magnitudes: dict[str, float] = dict(MAGNITUDES if magnitudes is None else magnitudes)

    def parse(self, text: str) -> float | None:
        """First number in the text, honouring signs, parens, separators; None when absent."""
        match: re.Match[str] | None = _NUMBER.search(text)
        return None if match is None else self._value(text, match)

    def parse_all(self, text: str) -> list[float]:
        """Every standalone number in the text, in order of appearance."""
        return [self._value(text, match) for match in _NUMBER.finditer(text)]

    def _value(self, text: str, match: re.Match[str]) -> float:
        value: float = float(match["num"].replace(",", "")) * self._magnitude(text, match.end())
        negative: bool = bool(match["paren"] or match["sign"])
        return -value if negative else value

    def _magnitude(self, text: str, offset: int) -> float:
        """A trailing word scales the value only when known and not a length unit (m3, m2, m/s)."""
        word: re.Match[str] | None = _MAGNITUDE_WORD.match(text, offset)
        if word is None or self._is_length_unit(text, word.end()):
            return 1.0
        return self._magnitudes.get(word["word"].lower(), 1.0)

    @staticmethod
    def _is_length_unit(text: str, end: int) -> bool:
        follower: str = text[end : end + 1]
        return follower.isdigit() or follower in {"/", "²", "³"}


class AnswerScorer:
    """Scores a model answer against an oracle value with power-of-ten scale awareness."""

    def __init__(self, rel_tol: float = 0.01, scales: tuple[float, ...] = (1e3, 1e6, 1e9)) -> None:
        self._rel_tol: float = rel_tol
        self._scales: tuple[float, ...] = scales
        self._parser: NumericParser = NumericParser()

    def score(self, expected: str, actual: str) -> Comparison:
        """Categorise the raw model answer against the oracle value string."""
        presence: Comparison | None = self._presence(expected, actual)
        return presence if presence is not None else self._compare(expected, actual)

    def _presence(self, expected: str, actual: str) -> Comparison | None:
        if not expected.strip():
            return self._oracle_empty(actual)
        return None if actual.strip() else Comparison("missed", self._parser.parse(expected), None)

    def _oracle_empty(self, actual: str) -> Comparison:
        category: Category = "extra" if actual.strip() else "abstained"
        return Comparison(category, None, self._parser.parse(actual))

    def _compare(self, expected: str, actual: str) -> Comparison:
        expected_num: float | None = self._parser.parse(expected)
        actual_num: float | None = self._parser.parse(actual)
        if expected_num is None or actual_num is None:
            return Comparison("mismatch", expected_num, actual_num)
        return self.categorise(expected_num, actual_num)

    def categorise(self, expected_num: float, actual_num: float) -> Comparison:
        """match, scale_mismatch or mismatch for two parsed numbers."""
        if self._close(expected_num, actual_num):
            return Comparison("match", expected_num, actual_num)
        scale: float | None = self._matching_scale(expected_num, actual_num)
        if scale is not None:
            return Comparison("scale_mismatch", expected_num, actual_num, scale=scale)
        return Comparison("mismatch", expected_num, actual_num)

    def _matching_scale(self, expected_num: float, actual_num: float) -> float | None:
        """Factor applied to the actual number that reproduces the expected one, if any."""
        candidates: list[float] = [*self._scales, *(1.0 / s for s in self._scales)]
        return next((s for s in candidates if self._close(expected_num, actual_num * s)), None)

    def _close(self, a: float, b: float) -> bool:
        return math.isclose(a, b, rel_tol=self._rel_tol, abs_tol=0.0)
