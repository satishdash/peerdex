"""Page furniture and element kinds the native table list already covers."""

from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.projection_state import ProjectionState


class SkipMapper(ElementMapper):
    """Page furniture and element kinds the native table list already covers."""

    def map(self, text: str, state: ProjectionState) -> None:
        """Drop the element.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        return None
