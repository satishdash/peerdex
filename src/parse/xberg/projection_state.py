"""Blocks gathered so far, the live heading stack, and each page's section."""

from parse.contract import (
    Block,
)


class ProjectionState:
    """Blocks gathered so far, the live heading stack, and each page's section."""

    def __init__(self) -> None:
        """Start with no blocks and no heading open."""
        self.blocks: list[Block] = []
        self.page_no: int = 0
        self._stack: list[tuple[int, str]] = []
        self.section_of_page: dict[int, list[str]] = {}

    @property
    def heading_path(self) -> list[str]:
        """Titles of the open ancestors, outermost first."""
        return [title for _level, title in self._stack]

    def enter(self, level: int, title: str) -> list[str]:
        """Close deeper headings, return the ancestors, then open this one.

        Args:
            level: The heading depth.
            title: The section title.

        Returns:
            The ancestor titles above the newly opened heading.
        """
        self._stack[:] = [entry for entry in self._stack if entry[0] < level]
        ancestors: list[str] = self.heading_path
        self._stack.append((level, title))
        return ancestors

    def observe(self, page_no: int) -> None:
        """Record the current page and the section it starts in.

        Args:
            page_no: The 1-based page the item sits on.
        """
        self.page_no = page_no
        self.section_of_page.setdefault(page_no, self.heading_path)
