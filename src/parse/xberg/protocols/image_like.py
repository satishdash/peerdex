"""One extracted figure bitmap with its geometry."""

from typing import Protocol

from parse.xberg.protocols.box_like import BoxLike


class ImageLike(Protocol):
    """One extracted figure bitmap with its geometry."""

    @property
    def bounding_box(self) -> BoxLike | None:
        """The image's bounding box."""

    @property
    def data(self) -> bytes | None:
        """The encoded image bytes."""

    @property
    def page_number(self) -> int | None:
        """The page this image sits on."""
