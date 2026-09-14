"""Projects a DoclingDocument onto typed Blocks, one item at a time."""

from collections.abc import Callable
from typing import Any, ClassVar

from parse.contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from parse.docling.engine_identity import EngineIdentity
from parse.docling.geometry import Geometry
from parse.docling.tally import Tally
from parse.heading import HeadingStack
from shared.logging import Logging
from shared.settings import get_settings


class DocumentProjection:
    """Projects a DoclingDocument onto typed Blocks, one item at a time."""

    _LOG: ClassVar[Any] = Logging.get("parse.docling")

    def __init__(self, doc: Any) -> None:
        """Prepare the walk over one DoclingDocument.

        Args:
            doc: The document to project.
        """
        settings: Any = get_settings()
        self._doc: Any = doc
        self._geometry: Geometry = Geometry(doc)
        self._heading: HeadingStack = HeadingStack()
        self._tally: Tally = Tally()
        self._blocks: list[Any] = []
        self._pages: list[PageInfo] = self._geometry.pages()
        self._min_area_pct: float = settings.vlm.min_bbox_area_pct
        self._band_pct: float = settings.vlm.skip_header_footer_band_pct
        self._handlers: dict[str, Callable[[Any], None]] = {
            "TitleItem": self._on_title,
            "SectionHeaderItem": self._on_section,
            "TextItem": self._on_paragraph,
            "ListItem": self._on_list_item,
            "TableItem": self._on_table,
            "PictureItem": self._on_picture,
        }

    def run(self) -> ExtractedDoc:
        """Walk every item, then report what was produced.

        Returns:
            The projected document.
        """
        for item, _level in self._doc.iterate_items():
            self._dispatch(item)
        self._log()
        return ExtractedDoc(blocks=self._blocks, pages=self._pages, source_meta=self._meta())

    def _dispatch(self, item: Any) -> None:
        """Route one item to its handler; unknown kinds are ignored.

        Args:
            item: The document item being projected.
        """
        handler: Callable[[Any], None] | None = self._handlers.get(type(item).__name__)
        if handler is not None:
            handler(item)

    def _on_title(self, item: Any) -> None:
        """A document title resets the whole heading ancestry.

        Args:
            item: The document item being projected.
        """
        text: str = self._text(item)
        if not text:
            return
        self._heading.reset_to_title(text)
        self._blocks.append(
            HeadingBlock(
                kind="heading",
                level=0,
                text=text,
                page_no=self._geometry.page_no(item),
                heading_path=[],
            )
        )

    def _on_section(self, item: Any) -> None:
        """A section header is recorded under its parents, then becomes a parent itself.

        Args:
            item: The document item being projected.
        """
        text: str = self._text(item)
        if not text:
            return
        level: int = self._level(item)
        parent: list[str] = self._heading.open_section(level, text)
        self._blocks.append(
            HeadingBlock(
                kind="heading",
                level=level,
                text=text,
                page_no=self._geometry.page_no(item),
                heading_path=parent,
            )
        )

    def _on_paragraph(self, item: Any) -> None:
        """Body text under the open heading path.

        Args:
            item: The document item being projected.
        """
        text: str = self._text(item)
        if not text:
            return
        self._blocks.append(
            ParagraphBlock(
                kind="paragraph",
                text=text,
                page_no=self._geometry.page_no(item),
                heading_path=self._heading.path,
            )
        )

    def _on_list_item(self, item: Any) -> None:
        """List items coalesce into the previous list when they belong to it.

        Args:
            item: The document item being projected.
        """
        text: str = self._text(item)
        if not text:
            return
        ordered: bool = bool(getattr(item, "enumerated", False))
        if self._extends_last_list(item, ordered):
            self._blocks[-1].items.append(text)
            return
        self._blocks.append(
            ListBlock(
                kind="list",
                items=[text],
                ordered=ordered,
                page_no=self._geometry.page_no(item),
                heading_path=self._heading.path,
            )
        )

    def _extends_last_list(self, item: Any, ordered: bool) -> bool:
        """Whether this item continues the list block just emitted.

        Args:
            item: The document item being projected.
            ordered: Whether the list is numbered.

        Returns:
            True when the item continues the list just emitted.
        """
        last: Any = self._blocks[-1] if self._blocks else None
        if not isinstance(last, ListBlock):
            return False
        return (last.page_no, last.heading_path, last.ordered) == (
            self._geometry.page_no(item),
            self._heading.path,
            ordered,
        )

    def _on_table(self, item: Any) -> None:
        """A table that will not export is dropped and counted.

        Args:
            item: The document item being projected.
        """
        frame: Any = self._dataframe(item)
        if frame is None:
            self._tally.table_drop += 1
            return
        self._blocks.append(self._table_block(item, frame))

    def _table_block(self, item: Any, frame: Any) -> TableBlock:
        """Build a table block from an exported dataframe.

        Args:
            item: The document item being projected.
            frame: The table exported as a dataframe.

        Returns:
            The table block built from the dataframe.
        """
        return TableBlock(
            kind="table",
            headers=[str(column) for column in frame.columns],
            rows=self._rows(frame),
            caption=self._caption(item),
            page_no=self._geometry.page_no(item),
            heading_path=self._heading.path,
        )

    @staticmethod
    def _rows(frame: Any) -> list[list[str]]:
        """Table cells as strings, row-major.

        Args:
            frame: The table exported as a dataframe.

        Returns:
            Table cells as strings, row-major.
        """
        return [[str(value) for value in row] for row in frame.itertuples(index=False, name=None)]

    def _dataframe(self, item: Any) -> Any:
        """Docling's dataframe export, or None when it fails.

        Args:
            item: The document item being projected.

        Returns:
            The exported dataframe, or None when the export fails.
        """
        try:
            return item.export_to_dataframe(doc=self._doc)
        except Exception as exc:
            self._LOG.debug(f"[docling] table export failed: {exc}")
            return None

    def _caption(self, item: Any) -> str:
        """A table's caption, empty when absent or unreadable.

        Args:
            item: The document item being projected.

        Returns:
            The caption, empty when absent or unreadable.
        """
        if not hasattr(item, "caption_text"):
            return ""
        return self._caption_text(item)

    def _caption_text(self, item: Any) -> str:
        """Read the caption defensively.

        Args:
            item: The document item being projected.

        Returns:
            The trimmed caption, empty when it cannot be read.
        """
        try:
            text: Any = item.caption_text(self._doc)
        except Exception:
            return ""
        return (text or "").strip()

    def _on_picture(self, item: Any) -> None:
        """Pictures are filtered by area and page band before they are kept.

        Args:
            item: The document item being projected.
        """
        self._tally.pic_seen += 1
        block: PictureBlock | None = self._picture(item)
        if block is None:
            return
        self._blocks.append(block)
        self._tally.pic_kept += 1

    def _picture(self, item: Any) -> PictureBlock | None:
        """Reject pictures too small to carry meaning.

        Args:
            item: The document item being projected.

        Returns:
            The picture block, or None when it is too small.
        """
        area: float | None = self._geometry.area_pct(item)
        if not self._area_ok(area):
            self._tally.pic_drop_area += 1
            return None
        return self._picture_outside_band(item, float(area))

    def _area_ok(self, area: float | None) -> bool:
        """Whether a picture is large enough to describe.

        Args:
            area: The picture's share of its page, as a percentage.

        Returns:
            True when the picture is large enough to describe.
        """
        return area is not None and area >= self._min_area_pct

    def _picture_outside_band(self, item: Any, area: float) -> PictureBlock | None:
        """Reject pictures living in the header or footer band.

        Args:
            item: The document item being projected.
            area: The picture's share of its page, as a percentage.

        Returns:
            The picture block, or None when it sits in a page band.
        """
        if self._geometry.in_band(item, self._band_pct):
            self._tally.pic_drop_band += 1
            return None
        return self._picture_with_image(item, area)

    def _picture_with_image(self, item: Any, area: float) -> PictureBlock | None:
        """Reject pictures that will not render.

        Args:
            item: The document item being projected.
            area: The picture's share of its page, as a percentage.

        Returns:
            The picture block, or None when it will not render.
        """
        image: Any = self._image(item)
        if image is None:
            self._tally.pic_drop_noimg += 1
            return None
        return PictureBlock(
            kind="picture",
            pil_image=image,
            bbox_area_pct=area,
            page_no=self._geometry.page_no(item),
            heading_path=self._heading.path,
            self_ref=getattr(item, "self_ref", "") or "",
        )

    def _image(self, item: Any) -> Any:
        """Render a picture, or None when Docling cannot.

        Args:
            item: The document item being projected.

        Returns:
            The rendered image, or None when Docling cannot render it.
        """
        try:
            return item.get_image(self._doc)
        except Exception as exc:
            self._LOG.debug(f"[docling] get_image failed: {exc}")
            return None

    def _meta(self) -> dict[str, Any]:
        """Extractor identity and the options that shaped this parse.

        Returns:
            Extractor identity and the options used.
        """
        settings: Any = get_settings()
        return {
            "extractor_name": EngineIdentity.NAME,
            "extractor_version": EngineIdentity.VERSION,
            "options": {
                "do_ocr": settings.docling.do_ocr,
                "do_table_structure": settings.docling.do_table_structure,
                "picture_image_scale": settings.docling.picture_image_scale,
                "min_bbox_area_pct": settings.vlm.min_bbox_area_pct,
                "skip_header_footer_band_pct": settings.vlm.skip_header_footer_band_pct,
            },
        }

    def _log(self) -> None:
        """One line describing what the walk produced."""
        tally: Tally = self._tally
        self._LOG.info(
            f"[extract] blocks={len(self._blocks)} pages={len(self._pages)} "
            f"pictures(seen={tally.pic_seen} kept={tally.pic_kept} "
            f"drop_area={tally.pic_drop_area} drop_band={tally.pic_drop_band} "
            f"drop_noimg={tally.pic_drop_noimg}) "
            f"tables_dropped={tally.table_drop}"
        )

    @staticmethod
    def _text(item: Any) -> str:
        """An item's trimmed text.

        Args:
            item: The document item being projected.

        Returns:
            The item's trimmed text.
        """
        return (item.text or "").strip()

    @staticmethod
    def _level(item: Any) -> int:
        """A section header's depth, defaulting to 1.

        Args:
            item: The document item being projected.

        Returns:
            The header depth, defaulting to 1.
        """
        return int(getattr(item, "level", 1) or 1)
