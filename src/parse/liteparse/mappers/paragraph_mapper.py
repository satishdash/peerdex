"""``paragraph`` / ``code`` -> ParagraphBlock."""

from parse.contract import (
    ParagraphBlock,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class ParagraphMapper(BlockMapper):
    """``paragraph`` / ``code`` -> ParagraphBlock."""

    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append body text under the open heading path.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """
        text: str = self.clean(block.text)
        if not text:
            return
        state.blocks.append(
            ParagraphBlock(
                kind="paragraph",
                text=text,
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )
