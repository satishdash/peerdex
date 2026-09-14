"""Document-scoped heading stack persisting across pages."""


class HeadingTracker:
    """Document-scoped heading stack persisting across pages."""

    def __init__(self) -> None:
        """Start with an empty heading stack."""
        self._stack: list[tuple[int, str]] = []

    def path(self) -> list[str]:
        """Current heading ancestry, outermost first.

        Returns:
            The open heading ancestry, outermost first.
        """
        return [text for _, text in self._stack]

    def push(self, level: int, text: str) -> list[str]:
        """Pop entries at or below ``level``, return the ancestors, then push.

        Args:
            level: The heading depth.
            text: The text being handled.

        Returns:
            The ancestor titles above the newly pushed heading.
        """
        self._stack = [entry for entry in self._stack if entry[0] < level]
        ancestors: list[str] = self.path()
        self._stack.append((level, text))
        return ancestors
