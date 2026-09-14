"""The duck-typed slice of a liteparse parse result the projection reads."""

from collections.abc import Sequence
from typing import Protocol

from parse.liteparse.protocols.image_like import ImageLike
from parse.liteparse.protocols.page_like import PageLike


class ParseResultLike(Protocol):
    """The duck-typed slice of a liteparse parse result the projection reads."""

    @property
    def num_pages(self) -> int:
        """How many pages the document has."""

    @property
    def images(self) -> Sequence[ImageLike] | None:
        """Every extracted raster image."""

    def get_page(self, page_num: int) -> PageLike | None:
        """The page with this number, when it exists.

        Args:
            page_num: The 1-based page number.
        """
