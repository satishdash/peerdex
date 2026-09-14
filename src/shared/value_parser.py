"""How the text right of ``=`` becomes a typed value."""

from abc import ABC, abstractmethod


class ValueParser[T](ABC):
    """Strategy: how the text right of ``=`` becomes a typed value."""

    @abstractmethod
    def parse(self, raw: str) -> T:
        """Typed value for raw text.

        Args:
            raw: The text right of ``=``.

        Returns:
            The typed value.
        """
