"""Undifferentiated PDF text: a bullet is a list item, heading shape wins next."""

from parse.xberg.heading_rule import HeadingRule
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.mappers.heading_mapper import HeadingMapper
from parse.xberg.mappers.list_item_mapper import ListItemMapper
from parse.xberg.mappers.paragraph_mapper import ParagraphMapper
from parse.xberg.projection_state import ProjectionState


class NarrativeMapper(ElementMapper):
    """Undifferentiated PDF text: a bullet is a list item, heading shape wins next.

    The other extractors are told the kind outright. Here only the text says so,
    and a bullet must be read before heading shape or a short bulleted line is
    mistaken for a section title.
    """

    def __init__(self, rule: HeadingRule) -> None:
        """Hold the heading rule and the mappers prose can become.

        Args:
            rule: Decides which elements count as headings.
        """
        self._rule: HeadingRule = rule
        self._paragraph: ParagraphMapper = ParagraphMapper()
        self._item: ListItemMapper = ListItemMapper()

    def map(self, text: str, state: ProjectionState) -> None:
        """A bullet is a list item; anything else is judged as prose.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        if self._BULLET.match(text):
            self._item.map(text, state)
            return
        self._as_prose(text, state)

    def _as_prose(self, text: str, state: ProjectionState) -> None:
        """Heading shape wins, otherwise it is a paragraph.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
        level: int = self._rule.level(text)
        if level == 0:
            self._paragraph.map(text, state)
            return
        HeadingMapper(level).map(text, state)
