"""Caption text collected in a pre-scan, keyed by the element it describes."""

from typing import Any


class Captions:
    """Caption text collected in a pre-scan, keyed by the element it describes."""

    def __init__(self, kids: list[dict]) -> None:
        """Index the captions found in a pre-scan of the document.

        Args:
            kids: The child elements to scan.
        """
        self._by_id: dict[Any, str] = self._collect(kids)

    def of(self, el: dict) -> str | None:
        """The caption linked to this element, if one was found.

        Args:
            el: The element being read.

        Returns:
            The linked caption, or None when none was found.
        """
        return self._by_id.get(el.get("id"))

    @classmethod
    def _collect(cls, kids: list[dict]) -> dict[Any, str]:
        """Index every caption element by the content id it points at.

        Args:
            kids: The child elements to scan.

        Returns:
            Caption text keyed by the content id it points at.
        """
        captions: dict[Any, str] = {}
        for el in kids:
            cls._add(captions, el)
        return captions

    @staticmethod
    def _add(captions: dict[Any, str], el: dict) -> None:
        """Record one caption, ignoring elements that link to nothing.

        Args:
            captions: The captions collected so far.
            el: The element being read.
        """
        if el.get("type") != "caption":
            return
        linked: Any = el.get("linked content id")
        if linked is not None:
            captions[linked] = el.get("content", "").strip()
