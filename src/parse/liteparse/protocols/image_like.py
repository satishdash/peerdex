"""One extracted raster image, keyed by the matching figure id."""

import builtins
from typing import Protocol


class ImageLike(Protocol):
    """One extracted raster image, keyed by the matching figure id."""

    @property
    def id(self) -> str:
        """Identifier matching the figure block."""

    @property
    def bytes(self) -> builtins.bytes:
        """The encoded image bytes."""
