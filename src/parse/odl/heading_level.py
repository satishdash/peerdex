"""ODL heading levels, mapped onto our 0-based scheme."""

from typing import Any, ClassVar


class HeadingLevel:
    """ODL heading levels, mapped onto our 0-based scheme."""

    _NAMED: ClassVar[dict[str, int]] = {"Title": 0, "Subtitle": 1}

    @classmethod
    def of(cls, el: dict) -> int:
        """The depth an ODL heading element declares.

        Args:
            el: The element being read.

        Returns:
            The declared depth, 0-based.
        """
        raw: Any = el.get("heading level", el.get("level", "1"))
        if isinstance(raw, int):
            return raw
        return cls._from_name(raw)

    @classmethod
    def _from_name(cls, raw: Any) -> int:
        """Named levels first, then anything that parses as a number.

        Args:
            raw: The raw value as the engine spells it.

        Returns:
            The mapped depth, or 1 when the name is unrecognised.
        """
        if raw in cls._NAMED:
            return cls._NAMED[raw]
        return cls._parsed(raw)

    @staticmethod
    def _parsed(raw: Any) -> int:
        """A numeric level, defaulting to 1.

        Args:
            raw: The raw value as the engine spells it.

        Returns:
            The parsed depth, or 1 when the value is not numeric.
        """
        try:
            return int(raw)
        except TypeError, ValueError:
            return 1
