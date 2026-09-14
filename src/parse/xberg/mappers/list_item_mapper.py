"""List items fold into one ListBlock while they share a page."""

from parse.contract import (
    Block,
    ListBlock,
)
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.projection_state import ProjectionState


class ListItemMapper(ElementMapper):
    """List items fold into one ListBlock while they share a page."""

    def map(self, text: str, state: ProjectionState) -> None:
        """Append an item, folding it into the open list when there is one.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        item: str = self._BULLET.sub("", text).strip()
        existing: ListBlock | None = self._open_list(state)
        if existing is not None:
            existing.items.append(item)
            return
        state.blocks.append(
            ListBlock(
                kind="list",
                items=[item],
                ordered=False,
                page_no=state.page_no,
                heading_path=state.heading_path,
            )
        )

    @staticmethod
    def _open_list(state: ProjectionState) -> ListBlock | None:
        """The list block still open on this page, if any.

        Args:
            state: The accumulator this projection is building into.

        Returns:
            The list block still open on this page, or None.
        """
        if not state.blocks:
            return None
        last: Block = state.blocks[-1]
        if not isinstance(last, ListBlock) or last.page_no != state.page_no:
            return None
        return last
