"""A document's blocks cut into the heading sections chunking works over."""

from chunk.section import Section
from parse import HeadingBlock


class SectionGrouper:
    """Splits a document's blocks into the heading sections chunking works over."""

    @classmethod
    def group(cls, blocks: list) -> list[Section]:
        """Every section of a document, in reading order.

        Args:
            blocks: The document's blocks, in reading order.

        Returns:
            One section per heading that has blocks, plus any blocks before the first heading.
        """
        sections: list[Section] = []
        current: Section = cls._opened(None)
        for b in blocks:
            if isinstance(b, HeadingBlock):
                cls._keep(sections, current)
                current = cls._opened(b)
            else:
                current.blocks.append(b)
        cls._keep(sections, current)
        return sections

    @staticmethod
    def _opened(b: HeadingBlock | None) -> Section:
        """An empty section under a heading, or under the document root when there is none.

        Args:
            b: The heading opening the section, or None for the root section.

        Returns:
            The opened section.
        """
        if b is None:
            return Section([], 0, [])
        return Section([*b.heading_path, b.text], getattr(b, "page_no", 0), [])

    @staticmethod
    def _keep(sections: list[Section], current: Section) -> None:
        """Close the open section, dropping it when no block landed in it.

        Args:
            sections: The sections closed so far.
            current: The section being closed.
        """
        if current.blocks:
            sections.append(current)
