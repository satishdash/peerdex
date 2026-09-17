"""Scores a model answer against an oracle value with power-of-ten scale awareness."""

import math

from evaluation.comparison import Category, Comparison
from quantity.magnitudes import Magnitudes
from quantity.numeric_parser import NumericParser


class AnswerScorer:
    """Scores a model answer against an oracle value with power-of-ten scale awareness."""

    def __init__(self, rel_tol: float = 0.01, scales: tuple[float, ...] = (1e3, 1e6, 1e9)) -> None:
        """Bind to a tolerance and the scales a mismatch may be out by.

        Args:
            rel_tol: Relative tolerance, so 100.9 matches 100.
            scales: The powers of ten an answer may be out by.
        """
        self._rel_tol: float = rel_tol
        self._scales: tuple[float, ...] = scales
        self._parser: NumericParser = NumericParser()

    def score(self, expected: str, actual: str, unit: str = "") -> Comparison:
        """Categorise the raw model answer against the oracle value string.

        ``unit`` is what the answer was reported in. The oracle stores a bare
        number with no unit, so an answer of "58,739" in $m looks a millionfold
        wrong against 58739000000 until the unit is read. It is only ever used to
        confirm a scale the two numbers already imply, never to rescale alone.

        Args:
            expected: The oracle value.
            actual: The answer the model gave.
            unit: What the answer was reported in.

        Returns:
            The comparison.
        """
        presence: Comparison | None = self._presence(expected, actual)
        if presence is not None:
            return presence
        return self._confirmed(self._compare(expected, actual), unit)

    def _confirmed(self, comparison: Comparison, unit: str) -> Comparison:
        """A scale mismatch that the unit accounts for is a match, not an error.

        Args:
            comparison: What the numbers alone decided.
            unit: What the answer was reported in.

        Returns:
            The comparison, upgraded to a match when the unit explains the scale.
        """
        if comparison.category != "scale_mismatch":
            return comparison
        if Magnitudes.of_unit(unit) != comparison.scale:
            return comparison
        return Comparison("match", comparison.expected_number, comparison.actual_number)

    def _presence(self, expected: str, actual: str) -> Comparison | None:
        """The category decided by presence alone, before any number is compared.

        Args:
            expected: The oracle value.
            actual: The answer the model gave.

        Returns:
            The comparison, or None when both sides carry something.
        """
        if not expected.strip():
            return self._oracle_empty(actual)
        return None if actual.strip() else Comparison("missed", self._parser.parse(expected), None)

    def _oracle_empty(self, actual: str) -> Comparison:
        """The category when the oracle states no value.

        Args:
            actual: The answer the model gave.

        Returns:
            Extra when a value was produced anyway, otherwise abstained.
        """
        category: Category = "extra" if actual.strip() else "abstained"
        return Comparison(category, None, self._parser.parse(actual))

    def _compare(self, expected: str, actual: str) -> Comparison:
        """The two sides parsed and compared as numbers.

        Args:
            expected: The oracle value.
            actual: The answer the model gave.

        Returns:
            The comparison, a mismatch when either side does not parse.
        """
        expected_num: float | None = self._parser.parse(expected)
        actual_num: float | None = self._parser.parse(actual)
        if expected_num is None or actual_num is None:
            return Comparison("mismatch", expected_num, actual_num)
        return self.categorise(expected_num, actual_num)

    def categorise(self, expected_num: float, actual_num: float) -> Comparison:
        """How two parsed numbers compare.

        Args:
            expected_num: The oracle number.
            actual_num: The answered number.

        Returns:
            A match, a scale mismatch, or a mismatch.
        """
        if self._close(expected_num, actual_num):
            return Comparison("match", expected_num, actual_num)
        scale: float | None = self._matching_scale(expected_num, actual_num)
        if scale is not None:
            return Comparison("scale_mismatch", expected_num, actual_num, scale=scale)
        return Comparison("mismatch", expected_num, actual_num)

    def _matching_scale(self, expected_num: float, actual_num: float) -> float | None:
        """The factor that would reconcile the two numbers.

        Args:
            expected_num: The oracle number.
            actual_num: The answered number.

        Returns:
            The factor applied to the answer that reproduces the oracle, or None.
        """
        candidates: list[float] = [*self._scales, *(1.0 / s for s in self._scales)]
        return next((s for s in candidates if self._close(expected_num, actual_num * s)), None)

    def _close(self, a: float, b: float) -> bool:
        """Whether two numbers agree within the tolerance.

        Args:
            a: One number.
            b: The other.

        Returns:
            Whether they are close enough to count as equal.
        """
        return math.isclose(a, b, rel_tol=self._rel_tol, abs_tol=0.0)
