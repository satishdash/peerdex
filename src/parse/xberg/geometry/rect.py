"""An xberg box in the shape the shared picture gate expects."""

from dataclasses import dataclass

from parse.xberg.protocols.box_like import BoxLike


@dataclass(frozen=True)
class Rect:
    """An xberg box in the shape the shared picture gate expects."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def of(cls, box: BoxLike) -> Rect:
        """Normalise an xberg box to a top-left origin rectangle.

        Args:
            box: The bounding box to convert.

        Returns:
            The box normalised to a top-left origin rectangle.
        """
        left: float = min(box.x0, box.x1)
        bottom: float = min(box.y0, box.y1)
        return cls(left, bottom, abs(box.x1 - box.x0), abs(box.y1 - box.y0))
