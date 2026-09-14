"""A described figure, held until its section is reached."""

from dataclasses import dataclass

from chunk.section import Section


@dataclass(frozen=True, slots=True)
class PendingNode:
    """A described figure held until its section is reached and its child node can be built."""

    text: str
    heading_path: list[str]
    page_no: int
    sec_idx: int

    @property
    def section(self) -> Section:
        """Where this figure sits: its own heading path and its own page.

        Returns:
            A section carrying the figure's placement.
        """
        return Section(self.heading_path, self.page_no, [])
