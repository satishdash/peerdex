"""Repeatable ``KEY=VALUE`` CLI arguments."""

from collections.abc import Sequence

from shared.value_parser import ValueParser


class KeyValueParser[T]:
    """Parses repeatable ``KEY=VALUE`` arguments; a ``ValueParser`` types the value side."""

    def __init__(self, values: ValueParser[T]) -> None:
        """Bind to the strategy that types each value.

        Args:
            values: The value parser.
        """
        self._values: ValueParser[T] = values

    def parse(self, pairs: Sequence[str]) -> dict[str, T]:
        """Every pair, with each key allowed only once.

        Args:
            pairs: The raw ``KEY=VALUE`` arguments.

        Returns:
            The parsed pairs.

        Raises:
            ValueError: If a key is given more than once.
        """
        parsed: dict[str, T] = {}
        for pair in pairs:
            key, value = self._parse_one(pair)
            if key in parsed:
                raise ValueError(f"key {key!r} given more than once, got {pair!r}")
            parsed[key] = value
        return parsed

    def _parse_one(self, pair: str) -> tuple[str, T]:
        """One ``KEY=VALUE`` argument.

        Args:
            pair: The raw argument.

        Returns:
            The key and its typed value.

        Raises:
            ValueError: If the argument is not ``KEY=VALUE``.
        """
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"expected KEY=VALUE, got {pair!r}")
        return key, self._values.parse(raw)
