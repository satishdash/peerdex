"""Mutable accumulator shared by the block mappers during one projection."""

from dataclasses import dataclass, field

from parse.contract import (
    Block,
)
from parse.liteparse.heading_tracker import HeadingTracker
from parse.liteparse.protocols.image_like import ImageLike
from parse.liteparse.protocols.page_like import PageLike


@dataclass
class ProjectionState:
    """Mutable accumulator shared by the block mappers during one projection."""

    images: dict[str, ImageLike]
    blocks: list[Block] = field(default_factory=list)
    headings: HeadingTracker = field(default_factory=HeadingTracker)
    page_no: int = 0
    page_width: float = 0.0
    page_height: float = 0.0

    def begin_page(self, page: PageLike) -> None:
        """Point the accumulator at a new page.

        Args:
            page: The page being projected.
        """
        self.page_no = page.page_num
        self.page_width = float(page.width)
        self.page_height = float(page.height)
