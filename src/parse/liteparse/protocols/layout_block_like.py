"""A classified layout block discriminated by ``kind``."""

from collections.abc import Sequence
from typing import Protocol

from parse.liteparse.protocols.cell_like import CellLike
from parse.liteparse.protocols.rect_like import RectLike


class LayoutBlockLike(Protocol):
    """A classified layout block discriminated by ``kind``."""

    @property
    def kind(self) -> str:
        """The classified block kind."""

    @property
    def text(self) -> str | None:
        """The block's text, when it carries any."""

    @property
    def level(self) -> int | None:
        """Heading depth, for heading blocks."""

    @property
    def ordered(self) -> bool | None:
        """Whether a list item is numbered."""

    @property
    def header(self) -> Sequence[CellLike] | None:
        """The table's header cells."""

    @property
    def rows(self) -> Sequence[Sequence[CellLike]] | None:
        """The table's body cells, row-major."""

    @property
    def id(self) -> str | None:
        """Identifier linking a figure to its image."""

    @property
    def bbox(self) -> RectLike | None:
        """The block's bounding box."""
