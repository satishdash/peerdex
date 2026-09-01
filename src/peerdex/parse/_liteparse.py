"""LiteParseExtractor: PDF -> ExtractedDoc via the liteparse native parser.

liteparse 2.x (Rust/PDFium) emits classified layout blocks -- headings,
paragraphs, list items, code, tables, figures -- plus the extracted raster
images. The projection onto the contract is pure and driven through the
public ``project`` seam, so tests exercise the full mapping with stub
objects and never touch a real PDF.
"""

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, Self

from liteparse import LiteParse, ParseResult
from PIL import Image

from peerdex.parse._contract import (
    Block,
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger("parse.liteparse")

_CONTROL_CHARS: re.Pattern[str] = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class RectLike(Protocol):
    """Rectangle in top-left-origin, 72-DPI viewport coordinates."""

    @property
    def x(self) -> float: ...

    @property
    def y(self) -> float: ...

    @property
    def width(self) -> float: ...

    @property
    def height(self) -> float: ...


class CellLike(Protocol):
    """One table cell."""

    @property
    def text(self) -> str: ...


class LayoutBlockLike(Protocol):
    """A classified layout block discriminated by ``kind``."""

    @property
    def kind(self) -> str: ...

    @property
    def text(self) -> str | None: ...

    @property
    def level(self) -> int | None: ...

    @property
    def ordered(self) -> bool | None: ...

    @property
    def header(self) -> Sequence[CellLike] | None: ...

    @property
    def rows(self) -> Sequence[Sequence[CellLike]] | None: ...

    @property
    def id(self) -> str | None: ...

    @property
    def bbox(self) -> RectLike | None: ...


class PageLike(Protocol):
    """One parsed page with its classified blocks."""

    @property
    def page_num(self) -> int: ...

    @property
    def width(self) -> float: ...

    @property
    def height(self) -> float: ...

    @property
    def blocks(self) -> Sequence[LayoutBlockLike] | None: ...


class ImageLike(Protocol):
    """One extracted raster image, keyed by the matching figure id."""

    @property
    def id(self) -> str: ...

    @property
    def bytes(self) -> bytes: ...


class ParseResultLike(Protocol):
    """The duck-typed slice of a liteparse parse result the projection reads."""

    @property
    def num_pages(self) -> int: ...

    @property
    def images(self) -> Sequence[ImageLike] | None: ...

    def get_page(self, page_num: int) -> PageLike | None: ...


class PictureGate:
    """VLM-parity figure gate: minimum bbox-area % and header/footer bands."""

    def __init__(self, min_bbox_area_pct: float, skip_header_footer_band_pct: float) -> None:
        self.min_bbox_area_pct: float = min_bbox_area_pct
        self.skip_header_footer_band_pct: float = skip_header_footer_band_pct

    @classmethod
    def from_settings(cls) -> Self:
        """Build the gate from the shared VLM settings."""
        vlm = get_settings().vlm
        return cls(vlm.min_bbox_area_pct, vlm.skip_header_footer_band_pct)

    def area_pct(self, bbox: RectLike, page_width: float, page_height: float) -> float:
        """Bbox area as a percentage of the page area."""
        page_area: float = page_width * page_height
        if page_area <= 0:
            return 0.0
        return 100.0 * (bbox.width * bbox.height) / page_area

    def admitted_area_pct(
        self, bbox: RectLike, page_width: float, page_height: float
    ) -> float | None:
        """The bbox area % when the figure passes both gates, else None."""
        area: float = self.area_pct(bbox, page_width, page_height)
        if area < self.min_bbox_area_pct:
            return None
        return None if self._in_band(bbox, page_height) else area

    def _in_band(self, bbox: RectLike, page_height: float) -> bool:
        band: float = page_height * self.skip_header_footer_band_pct / 100.0
        return bbox.y + bbox.height <= band or bbox.y >= page_height - band


class HeadingTracker:
    """Document-scoped heading stack persisting across pages."""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def path(self) -> list[str]:
        """Current heading ancestry, outermost first."""
        return [text for _, text in self._stack]

    def push(self, level: int, text: str) -> list[str]:
        """Pop entries at or below ``level``, return the ancestors, then push."""
        self._stack = [entry for entry in self._stack if entry[0] < level]
        ancestors: list[str] = self.path()
        self._stack.append((level, text))
        return ancestors


@dataclass
class _ProjectionState:
    """Mutable accumulator shared by the block mappers during one projection."""

    images: dict[str, ImageLike]
    blocks: list[Block] = field(default_factory=list)
    headings: HeadingTracker = field(default_factory=HeadingTracker)
    page_no: int = 0
    page_width: float = 0.0
    page_height: float = 0.0

    def begin_page(self, page: PageLike) -> None:
        self.page_no = page.page_num
        self.page_width = float(page.width)
        self.page_height = float(page.height)


class _BlockMapper(ABC):
    """Strategy mapping one layout block kind onto contract blocks."""

    @abstractmethod
    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
        """Append the contract projection of ``block`` to the state, or drop it."""

    @staticmethod
    def clean(text: str | None) -> str:
        """Strip control characters (keeping tab/newline) and trim."""
        return _CONTROL_CHARS.sub("", text or "").strip()


class _HeadingMapper(_BlockMapper):
    """``heading`` -> HeadingBlock, updating the document heading stack."""

    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
        text: str = self.clean(block.text)
        if not text:
            return
        level: int = block.level or 1
        ancestors: list[str] = state.headings.push(level, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading",
                level=level,
                text=text,
                page_no=state.page_no,
                heading_path=ancestors,
            )
        )


class _ParagraphMapper(_BlockMapper):
    """``paragraph`` / ``code`` -> ParagraphBlock."""

    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
        text: str = self.clean(block.text)
        if not text:
            return
        state.blocks.append(
            ParagraphBlock(
                kind="paragraph",
                text=text,
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )


class _ListItemMapper(_BlockMapper):
    """``list_item`` -> ListBlock, folding consecutive compatible items."""

    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
        text: str = self.clean(block.text)
        if not text:
            return
        ordered: bool = bool(block.ordered)
        target: ListBlock | None = self._coalesced(state, ordered)
        if target is not None:
            target.items.append(text)
            return
        state.blocks.append(
            ListBlock(
                kind="list",
                items=[text],
                ordered=ordered,
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )

    @staticmethod
    def _coalesced(state: _ProjectionState, ordered: bool) -> ListBlock | None:
        last: Block | None = state.blocks[-1] if state.blocks else None
        if not isinstance(last, ListBlock):
            return None
        matches: bool = (last.page_no, last.ordered, last.heading_path) == (
            state.page_no,
            ordered,
            state.headings.path(),
        )
        return last if matches else None


class _TableMapper(_BlockMapper):
    """``table`` / ``grid_fallback`` -> TableBlock; content-free tables dropped."""

    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
        headers: list[str] = [self.clean(cell.text) for cell in block.header or []]
        rows: list[list[str]] = [
            [self.clean(cell.text) for cell in row] for row in block.rows or []
        ]
        cells: list[str] = headers + [text for row in rows for text in row]
        if not any(cells):
            return
        state.blocks.append(
            TableBlock(
                kind="table",
                headers=headers,
                rows=rows,
                caption="",
                page_no=state.page_no,
                heading_path=state.headings.path(),
            )
        )


class _FigureMapper(_BlockMapper):
    """``figure`` -> PictureBlock when it survives the VLM gate and decodes."""

    def __init__(self, gate: PictureGate) -> None:
        self._gate: PictureGate = gate

    def map(self, block: LayoutBlockLike, state: _ProjectionState) -> None:
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
        self, block: LayoutBlockLike, state: _ProjectionState
    ) -> tuple[Image.Image, float] | None:
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
        try:
            return Image.open(BytesIO(data)).convert("RGB")
        except OSError, ValueError:
            return None


class LiteParseProjector:
    """Pure projection from a liteparse parse result onto contract blocks."""

    def __init__(self, gate: PictureGate) -> None:
        paragraph_mapper: _ParagraphMapper = _ParagraphMapper()
        table_mapper: _TableMapper = _TableMapper()
        self._mappers: dict[str, _BlockMapper] = {
            "heading": _HeadingMapper(),
            "paragraph": paragraph_mapper,
            "code": paragraph_mapper,
            "list_item": _ListItemMapper(),
            "table": table_mapper,
            "grid_fallback": table_mapper,
            "figure": _FigureMapper(gate),
        }

    def project(self, result: ParseResultLike) -> tuple[list[Block], list[PageInfo]]:
        """Walk pages 1..num_pages, mapping each block; unknown kinds are skipped."""
        images: dict[str, ImageLike] = {image.id: image for image in result.images or []}
        state: _ProjectionState = _ProjectionState(images=images)
        pages: list[PageInfo] = []
        for page_num in range(1, result.num_pages + 1):
            page: PageLike | None = result.get_page(page_num)
            if page is None:
                continue
            pages.append(
                PageInfo(page_no=page.page_num, width=float(page.width), height=float(page.height))
            )
            self._project_page(page, state)
        return state.blocks, pages

    def _project_page(self, page: PageLike, state: _ProjectionState) -> None:
        state.begin_page(page)
        for block in page.blocks or []:
            mapper: _BlockMapper | None = self._mappers.get(block.kind)
            if mapper is not None:
                mapper.map(block, state)


class LiteParseExtractor:
    """PDF -> ExtractedDoc adapter around the native liteparse parser."""

    name: str = "liteparse"
    version: str = "2.14.2"

    def __init__(self, gate: PictureGate | None = None) -> None:
        self._gate: PictureGate = gate if gate is not None else PictureGate.from_settings()
        self._projector: LiteParseProjector = LiteParseProjector(self._gate)

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Parse the PDF with blocks + images enabled and project the result."""
        log.info(f"extracting {pdf_path} via liteparse")
        with LiteParse(
            extract_blocks=True, extract_images=True, ocr_enabled=True, quiet=True
        ) as parser:
            result: ParseResult = parser.parse(str(pdf_path))
        return self.project(result)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Run ``extract`` in a worker thread to keep the event loop free."""
        return await asyncio.to_thread(self.extract, pdf_path)

    def project(self, result: ParseResultLike) -> ExtractedDoc:
        """Public seam: project any parse-result-shaped object onto the contract."""
        blocks, pages = self._projector.project(result)
        log.info(f"[liteparse] blocks={len(blocks)} pages={len(pages)}")
        return ExtractedDoc(blocks=blocks, pages=pages, source_meta=self._source_meta())

    def _source_meta(self) -> dict[str, Any]:
        return {
            "extractor_name": self.name,
            "extractor_version": self.version,
            "options": {
                "extract_blocks": True,
                "extract_images": True,
                "ocr_enabled": True,
                "min_bbox_area_pct": self._gate.min_bbox_area_pct,
                "skip_header_footer_band_pct": self._gate.skip_header_footer_band_pct,
            },
        }
