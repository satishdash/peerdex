"""Page and bounding-box questions about one DoclingDocument."""

from typing import Any

from parse.contract import (
    PageInfo,
)


class Geometry:
    """Page and bounding-box questions about one DoclingDocument."""

    def __init__(self, doc: Any) -> None:
        """Wrap one DoclingDocument.

        Args:
            doc: The document to measure.
        """
        self._doc: Any = doc

    def pages(self) -> list[PageInfo]:
        """Every page that reports a size.

        Returns:
            One entry per page that reports a size.
        """
        return [
            PageInfo(
                page_no=int(number), width=float(page.size.width), height=float(page.size.height)
            )
            for number, page in self._doc.pages.items()
            if page.size is not None
        ]

    def page_no(self, item: Any) -> int:
        """The 1-based page an item sits on, or 0 when it has no provenance.

        Args:
            item: The document item.

        Returns:
            The 1-based page, or 0 when provenance is missing.
        """
        return int(item.prov[0].page_no) if getattr(item, "prov", None) else 0

    def area_pct(self, item: Any) -> float | None:
        """An item's share of its page area, as a percentage.

        Args:
            item: The document item.

        Returns:
            The area share as a percentage, or None when it cannot be measured.
        """
        page: Any = self._page_of(item)
        if page is None:
            return None
        return self._area_ratio(item.prov[0].bbox, page.size)

    def in_band(self, item: Any, band_pct: float) -> bool:
        """Whether an item lies entirely in the header or footer band.

        Args:
            item: The document item.
            band_pct: Height of each band, as a percentage of the page.

        Returns:
            True when the item lies in the header or footer band.
        """
        page: Any = self._page_of(item)
        if page is None:
            return False
        return self._within_band(item.prov[0].bbox, float(page.size.height), band_pct)

    def _page_of(self, item: Any) -> Any:
        """The sized page an item belongs to, or None.

        Args:
            item: The document item.

        Returns:
            The sized page the item belongs to, or None.
        """
        if not getattr(item, "prov", None):
            return None
        return self._sized_page(item.prov[0].page_no)

    def _sized_page(self, page_no: int) -> Any:
        """A page, but only if it reports a size.

        Args:
            page_no: The 1-based page number.

        Returns:
            The page, or None when it reports no size.
        """
        page: Any = self._doc.pages.get(page_no)
        return page if page is not None and page.size is not None else None

    @staticmethod
    def _area_ratio(bbox: Any, size: Any) -> float | None:
        """Bounding-box area as a percentage of page area.

        Args:
            bbox: The item's bounding box.
            size: The page's dimensions.

        Returns:
            The area percentage, or None when the page has no area.
        """
        page_area: float = size.width * size.height
        if page_area <= 0:
            return None
        return 100.0 * abs((bbox.r - bbox.l) * (bbox.t - bbox.b)) / page_area

    @staticmethod
    def _within_band(bbox: Any, height: float, band_pct: float) -> bool:
        """Whether a bounding box falls inside the top or bottom band of a page.

        Args:
            bbox: The item's bounding box.
            height: The page height.
            band_pct: Height of each band, as a percentage of the page.

        Returns:
            True when the box falls inside the top or bottom band.
        """
        band: float = height * band_pct / 100.0
        return min(bbox.t, bbox.b) >= height - band or max(bbox.t, bbox.b) <= band
