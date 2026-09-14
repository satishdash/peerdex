"""One parsed page with its classified blocks."""

from collections.abc import Sequence
from typing import Protocol

from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class PageLike(Protocol):
    """One parsed page with its classified blocks."""

    @property
    def page_num(self) -> int:
        """The 1-based page number."""

    @property
    def width(self) -> float:
        """Page width, in points."""

    @property
    def height(self) -> float:
        """Page height, in points."""

    @property
    def blocks(self) -> Sequence[LayoutBlockLike] | None:
        """The classified blocks on this page."""
