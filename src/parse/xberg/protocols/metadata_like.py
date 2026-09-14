"""Element metadata carrying the page number."""

from typing import Protocol


class MetadataLike(Protocol):
    """Element metadata carrying the page number."""

    @property
    def page_number(self) -> int | None:
        """The page this element sits on."""
