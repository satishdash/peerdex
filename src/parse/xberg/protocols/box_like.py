"""An xberg bounding box in its own coordinates."""

from typing import Protocol


class BoxLike(Protocol):
    """An xberg bounding box in its own coordinates."""

    @property
    def x0(self) -> float:
        """First horizontal edge."""

    @property
    def y0(self) -> float:
        """First vertical edge."""

    @property
    def x1(self) -> float:
        """Second horizontal edge."""

    @property
    def y1(self) -> float:
        """Second vertical edge."""
