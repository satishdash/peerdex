"""``figure`` -> PictureBlock when it survives the VLM gate and decodes."""

from io import BytesIO

from PIL import Image

from parse.contract import (
    PictureBlock,
)
from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.picture_gate import PictureGate
from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.image_like import ImageLike
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class FigureMapper(BlockMapper):
    """``figure`` -> PictureBlock when it survives the VLM gate and decodes."""

    def __init__(self, gate: PictureGate) -> None:
        """Hold the gate a figure must clear.

        Args:
            gate: Decides which pictures are worth describing.
        """
        self._gate: PictureGate = gate

    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append a figure that survives the gate and decodes.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """
        admitted: tuple[Image.Image, float] | None = self._admit(block, state)
        if admitted is None:
            return
        pil_image, area_pct = admitted
        state.blocks.append(
            PictureBlock(
                kind="picture",
                pil_image=pil_image,
                bbox_area_pct=area_pct,
                page_no=state.page_no,
                heading_path=state.headings.path(),
                self_ref=block.id or "",
            )
        )

    def _admit(
        self, block: LayoutBlockLike, state: ProjectionState
    ) -> tuple[Image.Image, float] | None:
        """The decoded image and its area share, when the figure passes every gate.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.

        Returns:
            The decoded image and its area share, or None when refused.
        """
        image: ImageLike | None = state.images.get(block.id or "")
        if image is None or block.bbox is None:
            return None
        area_pct: float | None = self._gate.admitted_area_pct(
            block.bbox, state.page_width, state.page_height
        )
        if area_pct is None:
            return None
        pil_image: Image.Image | None = self._decode(image.bytes)
        return None if pil_image is None else (pil_image, area_pct)

    @staticmethod
    def _decode(data: bytes) -> Image.Image | None:
        """Decode raster bytes to RGB, or None when unreadable.

        Args:
            data: The encoded image bytes.

        Returns:
            The decoded RGB image, or None when unreadable.
        """
        try:
            return Image.open(BytesIO(data)).convert("RGB")
        except OSError, ValueError:
            return None
