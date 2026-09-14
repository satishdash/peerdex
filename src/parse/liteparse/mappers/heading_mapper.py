"""``heading`` -> HeadingBlock, updating the document heading stack."""

from parse.contract import (
    HeadingBlock,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class HeadingMapper(BlockMapper):
    """``heading`` -> HeadingBlock, updating the document heading stack."""

    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append a heading, and make it the new ancestor.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """
        text: str = self.clean(block.text)
        if not text:
            return
        level: int = block.level or 1
        ancestors: list[str] = state.headings.push(level, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading",
                level=level,
                text=text,
                page_no=state.page_no,
                heading_path=ancestors,
            )
        )
