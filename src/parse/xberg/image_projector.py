"""Decodes xberg's figure bitmaps, dropping whatever the gate refuses."""

import io
from typing import Any, ClassVar

from PIL import Image

from parse.contract import (
    PictureBlock,
)
from parse.liteparse import PictureGate
from parse.xberg.geometry.page_box import PageBox
from parse.xberg.geometry.rect import Rect
from parse.xberg.projection_state import ProjectionState
from parse.xberg.protocols.box_like import BoxLike
from parse.xberg.protocols.image_like import ImageLike
from shared.logging import Logging


class ImageProjector:
    """Decodes xberg's figure bitmaps, dropping whatever the gate refuses."""

    _LOG: ClassVar[Any] = Logging.get(__name__)

    def __init__(self, gate: PictureGate) -> None:
        """Hold the gate a figure must clear.

        Args:
            gate: Decides which pictures are worth describing.
        """
        self._gate: PictureGate = gate

    def project(self, images: list[ImageLike], state: ProjectionState) -> None:
        """Append every figure the gate admits.

        Args:
            images: The images found on the page.
            state: The accumulator this projection is building into.
        """
        page: PageBox = PageBox.spanning(images)
        for image in images:
            self._project_one(image, page, state)

    def _project_one(self, image: ImageLike, page: PageBox, state: ProjectionState) -> None:
        """Append one figure, or drop it.

        Args:
            image: The image to project.
            page: The page being projected.
            state: The accumulator this projection is building into.
        """
        admitted: tuple[Image.Image, float] | None = self._admit(image, page)
        if admitted is None:
            return
        bitmap, area = admitted
        page_no: int = int(image.page_number or 0)
        state.blocks.append(
            PictureBlock(
                kind="picture",
                pil_image=bitmap,
                bbox_area_pct=area,
                page_no=page_no,
                heading_path=state.section_of_page.get(page_no, []),
            )
        )

    def _admit(self, image: ImageLike, page: PageBox) -> tuple[Image.Image, float] | None:
        """The decoded bitmap and its area share, when the figure passes the gate.

        Args:
            image: The image to project.
            page: The page being projected.

        Returns:
            The decoded bitmap and its area share, or None when refused.
        """
        box: BoxLike | None = image.bounding_box
        if box is None:
            return None
        area: float | None = self._gate.admitted_area_pct(Rect.of(box), page.width, page.height)
        if area is None:
            return None
        bitmap: Image.Image | None = self._decode(image.data)
        return None if bitmap is None else (bitmap, area)

    @staticmethod
    def _decode(data: bytes | None) -> Image.Image | None:
        """Decode raster bytes to RGB, or None when unreadable.

        Args:
            data: The encoded image bytes.

        Returns:
            The decoded RGB image, or None when unreadable.
        """
        if not data:
            return None
        try:
            return Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as error:
            ImageProjector._LOG.debug(f"[xberg] image decode failed: {error}")
            return None
