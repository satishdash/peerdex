"""``list_item`` -> ListBlock, folding consecutive compatible items."""

from parse.contract import (
    Block,
    ListBlock,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class ListItemMapper(BlockMapper):
    """``list_item`` -> ListBlock, folding consecutive compatible items."""

    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append an item, folding it into the previous list when compatible.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """
        text: str = self.clean(block.text)
        if not text:
            return
        ordered: bool = bool(block.ordered)
        target: ListBlock | None = self._coalesced(state, ordered)
        if target is not None:
            target.items.append(text)
            return
        state.blocks.append(
            ListBlock(
                kind="list",
                items=[text],
                ordered=ordered,
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )

    @staticmethod
    def _coalesced(state: ProjectionState, ordered: bool) -> ListBlock | None:
        """The previous list block, when this item belongs to it.

        Args:
            state: The accumulator this projection is building into.
            ordered: Whether the list is numbered.

        Returns:
            The list block this item extends, or None.
        """
        last: Block | None = state.blocks[-1] if state.blocks else None
        if not isinstance(last, ListBlock):
            return None
        matches: bool = (last.page_no, last.ordered, last.heading_path) == (
            state.page_no,
            ordered,
            state.headings.path(),
        )
        return last if matches else None
