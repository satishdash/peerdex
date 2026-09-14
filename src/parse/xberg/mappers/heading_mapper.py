"""A heading becomes a HeadingBlock at a fixed level."""

from parse.contract import (
    HeadingBlock,
)
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.projection_state import ProjectionState


class HeadingMapper(ElementMapper):
    """A heading becomes a HeadingBlock at a fixed level."""

    def __init__(self, level: int = 1) -> None:
        """Bind the level this mapper emits.

        Args:
            level: The heading depth.
        """
        self._level: int = level

    def map(self, text: str, state: ProjectionState) -> None:
        """Open a section at this level and record it.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        ancestors: list[str] = state.enter(self._level, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading",
                level=self._level,
                text=text,
                page_no=state.page_no,
                heading_path=ancestors,
            )
        )
