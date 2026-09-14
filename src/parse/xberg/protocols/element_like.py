"""One classified element from xberg."""

from typing import Any, Protocol

from parse.xberg.protocols.metadata_like import MetadataLike


class ElementLike(Protocol):
    """One classified element from xberg."""

    @property
    def element_type(self) -> Any:
        """The element's classified type."""

    @property
    def text(self) -> str | None:
        """The element's text."""

    @property
    def metadata(self) -> MetadataLike:
        """The element's metadata."""
