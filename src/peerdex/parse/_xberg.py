"""XbergExtractor: PDF -> ExtractedDoc via xberg, the successor to kreuzberg.

xberg reports tables and figure bitmaps natively with page numbers, so the
whitespace-alignment heuristic its predecessor needed is gone. Its PDF path
still emits every text run as ``narrative_text``, so heading shape is decided
here. Figures pass the same area and header/footer gate the other extractors use.

The projector is pure and drives the tests; the adapter owns the one IO call.
"""

import asyncio
import io
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
from peerdex.parse._liteparse import PictureGate
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger(__name__)

_BULLET: re.Pattern[str] = re.compile(r"^[•‣◦\-\*·]\s*")
_SENTENCE: re.Pattern[str] = re.compile(r"\.\s+[A-Z]")
_TERMINAL: frozenset[str] = frozenset(".,:;")
_MAX_HEADING_CHARS: int = 120
_MIN_HEADING_CHARS: int = 2
_MAX_DIGIT_RATIO: float = 0.30
_MIN_SHOUT_RATIO: float = 0.60


class MetadataLike(Protocol):
    @property
    def page_number(self) -> int | None: ...


class ElementLike(Protocol):
    @property
    def element_type(self) -> Any: ...

    @property
    def text(self) -> str | None: ...

    @property
    def metadata(self) -> MetadataLike: ...


class TableLike(Protocol):
    @property
    def cells(self) -> list[list[str]] | None: ...

    @property
    def page_number(self) -> int | None: ...


class PageLike(Protocol):
    @property
    def page_number(self) -> int | None: ...


class BoxLike(Protocol):
    @property
    def x0(self) -> float: ...

    @property
    def y0(self) -> float: ...

    @property
    def x1(self) -> float: ...

    @property
    def y1(self) -> float: ...


class ImageLike(Protocol):
    @property
    def bounding_box(self) -> BoxLike | None: ...

    @property
    def data(self) -> bytes | None: ...

    @property
    def page_number(self) -> int | None: ...


class DocumentLike(Protocol):
    @property
    def elements(self) -> list[ElementLike] | None: ...

    @property
    def tables(self) -> list[TableLike] | None: ...

    @property
    def pages(self) -> list[PageLike] | None: ...

    @property
    def images(self) -> list[ImageLike] | None: ...


class HeadingRule:
    """Decides whether an undifferentiated text run reads as a section heading.

    Returns the heading level, or zero when the text is ordinary prose.
    """

    def level(self, text: str) -> int:
        stripped: str = text.strip()
        if not self._shaped(stripped):
            return 0
        return 1 if self._shouted(stripped) else 2

    def _shaped(self, text: str) -> bool:
        return all(
            rule(text)
            for rule in (
                self._single_line,
                self._sized,
                self._unterminated,
                self._one_sentence,
                self._mostly_letters,
            )
        )

    @staticmethod
    def _single_line(text: str) -> bool:
        return "\n" not in text.strip()

    @staticmethod
    def _sized(text: str) -> bool:
        return _MIN_HEADING_CHARS <= len(text) <= _MAX_HEADING_CHARS

    @staticmethod
    def _unterminated(text: str) -> bool:
        return bool(text) and text[-1] not in _TERMINAL

    @staticmethod
    def _one_sentence(text: str) -> bool:
        return _SENTENCE.search(text) is None

    @staticmethod
    def _mostly_letters(text: str) -> bool:
        digits: int = sum(1 for char in text if char.isdigit())
        return digits / len(text) < _MAX_DIGIT_RATIO

    @staticmethod
    def _shouted(text: str) -> bool:
        letters: int = sum(1 for char in text if char.isalpha())
        upper: int = sum(1 for char in text if char.isupper())
        return letters > 0 and upper / letters > _MIN_SHOUT_RATIO


class _ProjectionState:
    """Blocks gathered so far, the live heading stack, and each page's section."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.page_no: int = 0
        self._stack: list[tuple[int, str]] = []
        self.section_of_page: dict[int, list[str]] = {}

    @property
    def heading_path(self) -> list[str]:
        return [title for _level, title in self._stack]

    def enter(self, level: int, title: str) -> list[str]:
        self._stack[:] = [entry for entry in self._stack if entry[0] < level]
        ancestors: list[str] = self.heading_path
        self._stack.append((level, title))
        return ancestors

    def observe(self, page_no: int) -> None:
        self.page_no = page_no
        self.section_of_page.setdefault(page_no, self.heading_path)


class _ElementMapper(ABC):
    """One element kind's projection into zero or more blocks."""

    @abstractmethod
    def map(self, text: str, state: _ProjectionState) -> None: ...


class _TitleMapper(_ElementMapper):
    def map(self, text: str, state: _ProjectionState) -> None:
        ancestors: list[str] = state.enter(0, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading", level=0, text=text, page_no=state.page_no, heading_path=ancestors
            )
        )


class _HeadingMapper(_ElementMapper):
    def __init__(self, level: int = 1) -> None:
        self._level: int = level

    def map(self, text: str, state: _ProjectionState) -> None:
        ancestors: list[str] = state.enter(self._level, text)
        state.blocks.append(
            HeadingBlock(
                kind="heading",
                level=self._level,
                text=text,
                page_no=state.page_no,
                heading_path=ancestors,
            )
        )


class _ParagraphMapper(_ElementMapper):
    def map(self, text: str, state: _ProjectionState) -> None:
        state.blocks.append(
            ParagraphBlock(
                kind="paragraph", text=text, page_no=state.page_no, heading_path=state.heading_path
            )
        )


class _ListItemMapper(_ElementMapper):
    def map(self, text: str, state: _ProjectionState) -> None:
        item: str = _BULLET.sub("", text).strip()
        existing: ListBlock | None = self._open_list(state)
        if existing is not None:
            existing.items.append(item)
            return
        state.blocks.append(
            ListBlock(
                kind="list",
                items=[item],
                ordered=False,
                page_no=state.page_no,
                heading_path=state.heading_path,
            )
        )

    @staticmethod
    def _open_list(state: _ProjectionState) -> ListBlock | None:
        if not state.blocks:
            return None
        last: Block = state.blocks[-1]
        if not isinstance(last, ListBlock) or last.page_no != state.page_no:
            return None
        return last


class _NarrativeMapper(_ElementMapper):
    """Undifferentiated PDF text: a bullet is a list item, heading shape wins next.

    The other extractors are told the kind outright. Here only the text says so,
    and a bullet must be read before heading shape or a short bulleted line is
    mistaken for a section title.
    """

    def __init__(self, rule: HeadingRule) -> None:
        self._rule: HeadingRule = rule
        self._paragraph: _ParagraphMapper = _ParagraphMapper()
        self._item: _ListItemMapper = _ListItemMapper()

    def map(self, text: str, state: _ProjectionState) -> None:
        if _BULLET.match(text):
            self._item.map(text, state)
            return
        self._as_prose(text, state)

    def _as_prose(self, text: str, state: _ProjectionState) -> None:
        level: int = self._rule.level(text)
        if level == 0:
            self._paragraph.map(text, state)
            return
        _HeadingMapper(level).map(text, state)


class _SkipMapper(_ElementMapper):
    """Page furniture and element kinds the native table list already covers."""

    def map(self, text: str, state: _ProjectionState) -> None:
        return None


@dataclass(frozen=True)
class _Rect:
    """An xberg box in the shape the shared picture gate expects."""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def of(cls, box: BoxLike) -> _Rect:
        left: float = min(box.x0, box.x1)
        bottom: float = min(box.y0, box.y1)
        return cls(left, bottom, abs(box.x1 - box.x0), abs(box.y1 - box.y0))


class _PageBox:
    """The page extent in points.

    xberg reports image geometry but never page size, and a report's pages share
    one size, so the furthest corner any image reaches bounds them all.
    """

    def __init__(self, width: float, height: float) -> None:
        self.width: float = width
        self.height: float = height

    @classmethod
    def spanning(cls, images: list[ImageLike]) -> _PageBox:
        rects: list[_Rect] = [_Rect.of(box) for box in _boxes(images)]
        if not rects:
            return cls(0.0, 0.0)
        return cls(
            max(rect.x + rect.width for rect in rects),
            max(rect.y + rect.height for rect in rects),
        )


class _ImageProjector:
    """Decodes xberg's figure bitmaps, dropping whatever the gate refuses."""

    def __init__(self, gate: PictureGate) -> None:
        self._gate: PictureGate = gate

    def project(self, images: list[ImageLike], state: _ProjectionState) -> None:
        page: _PageBox = _PageBox.spanning(images)
        for image in images:
            self._project_one(image, page, state)

    def _project_one(self, image: ImageLike, page: _PageBox, state: _ProjectionState) -> None:
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

    def _admit(self, image: ImageLike, page: _PageBox) -> tuple[Image.Image, float] | None:
        box: BoxLike | None = image.bounding_box
        if box is None:
            return None
        area: float | None = self._gate.admitted_area_pct(_Rect.of(box), page.width, page.height)
        if area is None:
            return None
        bitmap: Image.Image | None = _decode(image.data)
        return None if bitmap is None else (bitmap, area)


def _boxes(images: list[ImageLike]) -> list[BoxLike]:
    return [image.bounding_box for image in images if image.bounding_box is not None]


def _decode(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as error:
        log.debug(f"[xberg] image decode failed: {error}")
        return None


class XbergProjector:
    """Turns one xberg document into the shared block contract. Pure."""

    def __init__(self, rule: HeadingRule | None = None, gate: PictureGate | None = None) -> None:
        heading_rule: HeadingRule = rule or HeadingRule()
        self._images: _ImageProjector = _ImageProjector(gate or PictureGate.from_settings())
        self._fallback: _ElementMapper = _NarrativeMapper(heading_rule)
        self._skip: _ElementMapper = _SkipMapper()
        self._mappers: dict[str, _ElementMapper] = {
            "title": _TitleMapper(),
            "heading": _HeadingMapper(),
            "narrative_text": self._fallback,
            "list_item": _ListItemMapper(),
            "page_break": self._skip,
            "table": self._skip,
            "header": self._skip,
            "footer": self._skip,
            "image": self._skip,
        }

    def project(self, document: DocumentLike) -> tuple[list[Block], list[PageInfo]]:
        """Elements in reading order, then native tables, then gated figures."""
        state: _ProjectionState = _ProjectionState()
        for element in document.elements or []:
            self._project_element(element, state)
        for table in document.tables or []:
            self._project_table(table, state)
        self._images.project(list(document.images or []), state)
        return state.blocks, self._pages(document)

    def _project_element(self, element: ElementLike, state: _ProjectionState) -> None:
        text: str = (element.text or "").strip()
        if not text:
            return
        state.observe(_page_of(element.metadata))
        mapper: _ElementMapper = self._mappers.get(_kind(element.element_type), self._fallback)
        mapper.map(text, state)

    def _project_table(self, table: TableLike, state: _ProjectionState) -> None:
        rows: list[list[str]] = [list(row) for row in (table.cells or []) if any(row)]
        if not rows:
            return
        page_no: int = int(table.page_number or 0)
        headers: list[str] = rows[0] if len(rows) > 1 else []
        body: list[list[str]] = rows[1:] if len(rows) > 1 else rows
        state.blocks.append(
            TableBlock(
                kind="table",
                headers=headers,
                rows=body,
                caption="",
                page_no=page_no,
                heading_path=state.section_of_page.get(page_no, []),
            )
        )

    @staticmethod
    def _pages(document: DocumentLike) -> list[PageInfo]:
        return [
            PageInfo(page_no=int(page.page_number or 0), width=0.0, height=0.0)
            for page in (document.pages or [])
        ]


def _kind(element_type: Any) -> str:
    return str(getattr(element_type, "value", element_type)).strip().lower()


def _page_of(metadata: MetadataLike | None) -> int:
    return int(getattr(metadata, "page_number", 0) or 0)


class XbergExtractor:
    """Adapter: one xberg call, then the pure projection."""

    name: str = "xberg"
    version: str = "1.1"

    def __init__(self, projector: XbergProjector | None = None) -> None:
        self._projector: XbergProjector = projector or XbergProjector()

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        return asyncio.run(self.extract_async(pdf_path))

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Extract one PDF, asking xberg for its element-based result format."""
        import xberg

        log.info(f"[xberg] extracting {pdf_path}")
        config: Any = xberg.ExtractionConfig(
            use_cache=False,
            result_format="element_based",
            images=xberg.ImageExtractionConfig(
                extract_images=True,
                target_dpi=get_settings().xberg.target_dpi,
                run_ocr_on_images=False,
                inject_placeholders=False,
            ),
        )
        result: Any = await xberg.extract(
            xberg.ExtractInput(kind="uri", uri=str(pdf_path)), config=config
        )
        blocks, pages = self._projector.project(result.results[0])
        pictures: int = sum(1 for block in blocks if block.kind == "picture")
        log.info(f"[xberg] blocks={len(blocks)} pages={len(pages)} pictures={pictures}")
        return ExtractedDoc(
            blocks=blocks,
            pages=pages,
            source_meta={"extractor_name": self.name, "extractor_version": self.version},
        )
