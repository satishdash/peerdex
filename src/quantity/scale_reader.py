"""Reads the scale a unit text declares, so the scale lives in the number."""

from collections.abc import Sequence
from decimal import Decimal

from quantity.magnitudes import Magnitudes


class ScaleReader:
    """Reads the scale a unit text declares, so the scale lives in the number."""

    def __init__(self, magnitudes: dict[str, float] | None = None) -> None:
        """Bind to a magnitude table.

        Args:
            magnitudes: The words that declare a scale, or None for the standard set.
        """
        source: dict[str, float] = dict(Magnitudes.TABLE if magnitudes is None else magnitudes)
        self._magnitudes: dict[str, Decimal] = {
            word: Decimal(str(factor)) for word, factor in source.items()
        }

    def read(self, text: str) -> Decimal:
        """The first scale word's factor, or one.

        Only whole words count, so ``Mt`` is not read as mega.

        Args:
            text: The unit text printed beside the figure.

        Returns:
            The factor the text declares, or one.
        """
        words: Sequence[str] = text.lower().replace("(", " ").replace(")", " ").split()
        factors: list[Decimal] = [self._magnitudes[word] for word in words if self._scale(word)]
        return factors[0] if factors else Decimal(1)

    def _scale(self, word: str) -> bool:
        """Whether one word names a scale.

        A single letter is a unit far more often than a scale, so it is not read as one.

        Args:
            word: One word of the unit text.

        Returns:
            Whether it names a scale.
        """
        return len(word) > 1 and word in self._magnitudes
