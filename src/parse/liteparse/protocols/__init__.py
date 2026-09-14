"""Protocols."""

from parse.liteparse.protocols.cell_like import CellLike
from parse.liteparse.protocols.image_like import ImageLike
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike
from parse.liteparse.protocols.page_like import PageLike
from parse.liteparse.protocols.parse_result_like import ParseResultLike
from parse.liteparse.protocols.rect_like import RectLike

__all__ = [
    "CellLike",
    "ImageLike",
    "LayoutBlockLike",
    "PageLike",
    "ParseResultLike",
    "RectLike",
]
