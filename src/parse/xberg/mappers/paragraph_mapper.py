"""Prose becomes a ParagraphBlock."""

from parse.contract import (
    ParagraphBlock,
)
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.projection_state import ProjectionState


class ParagraphMapper(ElementMapper):
    """Prose becomes a ParagraphBlock."""

    def map(self, text: str, state: ProjectionState) -> None:
        """Append body text under the open heading path.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        state.blocks.append(
            ParagraphBlock(
                kind="paragraph", text=text, page_no=state.page_no, heading_path=state.heading_path
            )
        )
