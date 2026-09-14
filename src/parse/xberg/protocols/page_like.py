"""One reported page."""

from typing import Protocol


class PageLike(Protocol):
    """One reported page."""

    @property
    def page_number(self) -> int | None:
        """The 1-based page number."""
