"""VLM-parity figure gate: minimum bbox-area % and header/footer bands."""

from typing import Self

from parse.liteparse.protocols.rect_like import RectLike
from shared.settings import get_settings


class PictureGate:
    """VLM-parity figure gate: minimum bbox-area % and header/footer bands."""

    def __init__(self, min_bbox_area_pct: float, skip_header_footer_band_pct: float) -> None:
        """Hold the two thresholds a figure must clear.

        Args:
            min_bbox_area_pct: Smallest share of a page a picture may cover and still be kept.
            skip_header_footer_band_pct: Height of the bands to skip, as a percentage of the page.
        """
        self.min_bbox_area_pct: float = min_bbox_area_pct
        self.skip_header_footer_band_pct: float = skip_header_footer_band_pct

    @classmethod
    def from_settings(cls) -> Self:
        """Build the gate from the shared VLM settings.

        Returns:
            A gate built from the shared VLM settings.
        """
        vlm = get_settings().vlm
        return cls(vlm.min_bbox_area_pct, vlm.skip_header_footer_band_pct)

    def area_pct(self, bbox: RectLike, page_width: float, page_height: float) -> float:
        """Bbox area as a percentage of the page area.

        Args:
            bbox: The bounding box, in page coordinates.
            page_width: The page width.
            page_height: The page height.

        Returns:
            The bbox area as a percentage of the page.
        """
        page_area: float = page_width * page_height
        if page_area <= 0:
            return 0.0
        return 100.0 * (bbox.width * bbox.height) / page_area

    def admitted_area_pct(
        self, bbox: RectLike, page_width: float, page_height: float
    ) -> float | None:
        """The bbox area % when the figure passes both gates, else None.

        Args:
            bbox: The bounding box, in page coordinates.
            page_width: The page width.
            page_height: The page height.

        Returns:
            The area percentage, or None when the figure is refused.
        """
        area: float = self.area_pct(bbox, page_width, page_height)
        if area < self.min_bbox_area_pct:
            return None
        return None if self._in_band(bbox, page_height) else area

    def _in_band(self, bbox: RectLike, page_height: float) -> bool:
        """Whether a figure sits wholly inside the header or footer band.

        Args:
            bbox: The bounding box, in page coordinates.
            page_height: The page height.

        Returns:
            True when the figure lies in the header or footer band.
        """
        band: float = page_height * self.skip_header_footer_band_pct / 100.0
        return bbox.y + bbox.height <= band or bbox.y >= page_height - band
