"""The words a document uses to scale a number, and what they multiply by."""

import re
from typing import ClassVar, Final


class Magnitudes:
    """Thousand, million, billion and their abbreviations, as multipliers."""

    TABLE: ClassVar[dict[str, float]] = {
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

    _PER: ClassVar[Final[re.Pattern[str]]] = re.compile(r"\bper\b")
    _WORD: ClassVar[Final[re.Pattern[str]]] = re.compile(r"[A-Za-z]+")

    @classmethod
    def of_unit(cls, unit: str) -> float | None:
        """The magnitude a unit declares for its own quantity.

        Only the text before ``per`` is read, so "per million of revenue" contributes
        nothing: there the magnitude belongs to the denominator, and folding it in
        would corrupt an intensity that is already right.

        A bare "m" is read as million, which is ambiguous with metres. That is
        tolerable because the caller only consults this once two numbers are already
        a power of ten apart.

        Args:
            unit: The unit as the document spells it.

        Returns:
            The multiplier, or None when the unit declares none.
        """
        head: str = cls._PER.split(unit, maxsplit=1)[0].lower()
        factors: list[float] = [
            cls.TABLE[word] for word in cls._WORD.findall(head) if word in cls.TABLE
        ]
        return factors[0] if factors else None
