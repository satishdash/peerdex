"""Rectangle in top-left-origin, 72-DPI viewport coordinates."""

from typing import Protocol


class RectLike(Protocol):
    """Rectangle in top-left-origin, 72-DPI viewport coordinates."""

    @property
    def x(self) -> float:
        """Left edge, in viewport points."""

    @property
    def y(self) -> float:
        """Top edge, in viewport points."""

    @property
    def width(self) -> float:
        """Width, in viewport points."""

    @property
    def height(self) -> float:
        """Height, in viewport points."""
