"""Heading ancestry, shared by the extractors that walk a document in order."""


class HeadingStack:
    """The heading ancestry currently open as a document is walked."""

    def __init__(self) -> None:
        """Start with no heading open."""
        self._open: list[tuple[int, str]] = []

    @property
    def path(self) -> list[str]:
        """Titles of the open ancestors, outermost first.

        Returns:
            The ancestor titles.
        """
        return [text for _, text in self._open if text]

    def reset_to_title(self, text: str) -> None:
        """Begin a new document title, discarding any open sections.

        Args:
            text: The document title.
        """
        self._open[:] = [(0, text)]

    def open_section(self, level: int, text: str) -> list[str]:
        """Close sections at or below this level, return the parent path, then open this one.

        Args:
            level: Depth of the section being opened.
            text: Its title.

        Returns:
            The ancestor titles above the newly opened section.
        """
        self._open[:] = [entry for entry in self._open if entry[0] < level]
        parent: list[str] = self.path
        self._open.append((level, text))
        return parent
