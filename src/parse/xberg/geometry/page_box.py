"""The page extent in points."""

from parse.xberg.geometry.rect import Rect
from parse.xberg.protocols.box_like import BoxLike
from parse.xberg.protocols.image_like import ImageLike


class PageBox:
    """The page extent in points.

    xberg reports image geometry but never page size, and a report's pages share
    one size, so the furthest corner any image reaches bounds them all.
    """

    def __init__(self, width: float, height: float) -> None:
        """Hold the page extent in points.

        Args:
            width: The page width.
            height: The page height.
        """
        self.width: float = width
        self.height: float = height

    @classmethod
    def spanning(cls, images: list[ImageLike]) -> PageBox:
        """The extent that bounds every image on the page.

        Args:
            images: The images found on the page.

        Returns:
            The extent bounding every image, or zero when there are none.
        """
        rects: list[Rect] = [Rect.of(box) for box in cls._boxes(images)]
        if not rects:
            return cls(0.0, 0.0)
        return cls(
            max(rect.x + rect.width for rect in rects),
            max(rect.y + rect.height for rect in rects),
        )

    @staticmethod
    def _boxes(images: list[ImageLike]) -> list[BoxLike]:
        """Every image bounding box that exists.

        Args:
            images: The images found on the page.

        Returns:
            Every bounding box that exists.
        """
        return [image.bounding_box for image in images if image.bounding_box is not None]
