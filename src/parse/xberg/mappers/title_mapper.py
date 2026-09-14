"""A title becomes a level-0 heading."""

from parse.contract import (
    HeadingBlock,
)
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.projection_state import ProjectionState


class TitleMapper(ElementMapper):
    """A title becomes a level-0 heading."""

    def map(self, text: str, state: ProjectionState) -> None:
        """Open the document title and record it.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        ancestors: list[str] = state.enter(0, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading", level=0, text=text, page_no=state.page_no, heading_path=ancestors
            )
        )
