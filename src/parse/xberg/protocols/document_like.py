"""The duck-typed slice of an xberg result the projection reads."""

from typing import Protocol

from parse.xberg.protocols.element_like import ElementLike
from parse.xberg.protocols.image_like import ImageLike
from parse.xberg.protocols.page_like import PageLike
from parse.xberg.protocols.table_like import TableLike


class DocumentLike(Protocol):
    """The duck-typed slice of an xberg result the projection reads."""

    @property
    def elements(self) -> list[ElementLike] | None:
        """Every classified element, in reading order."""

    @property
    def tables(self) -> list[TableLike] | None:
        """Every natively detected table."""

    @property
    def pages(self) -> list[PageLike] | None:
        """Every reported page."""

    @property
    def images(self) -> list[ImageLike] | None:
        """Every extracted figure bitmap."""
