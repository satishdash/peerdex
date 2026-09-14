"""Projects an ODL JSON document onto typed Blocks, one element at a time."""

from collections.abc import Callable
from typing import Any, ClassVar

from parse.contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    TableBlock,
)
from parse.heading import HeadingStack
from parse.odl.captions import Captions
from parse.odl.engine_identity import EngineIdentity
from parse.odl.heading_level import HeadingLevel
from parse.odl.table import Table
from parse.odl.tally import Tally
from shared.logging import Logging


class DocumentProjection:
    """Projects an ODL JSON document onto typed Blocks, one element at a time."""

    _LOG: ClassVar[Any] = Logging.get("parse.odl")

    def __init__(self, data: dict) -> None:
        """Prepare the walk over one ODL JSON document.

        Args:
            data: The encoded image bytes.
        """
        self._kids: list[dict] = data.get("kids", [])
        self._captions: Captions = Captions(self._kids)
        self._heading: HeadingStack = HeadingStack()
        self._tally: Tally = Tally()
        self._blocks: list[Any] = []
        self._handlers: dict[str, Callable[[dict], None]] = {
            "heading": self._on_heading,
            "paragraph": self._on_paragraph,
            "table": self._on_table,
            "list": self._on_list,
            "image": self._on_image,
            "text block": self._on_text_block,
        }

    def run(self) -> ExtractedDoc:
        """Walk every element, then report what was produced.

        Returns:
            The projected document.
        """
        for el in self._kids:
            self._dispatch(el)
        pages: list[PageInfo] = self._pages()
        self._log(pages)
        return ExtractedDoc(blocks=self._blocks, pages=pages, source_meta=self._meta())

    def _dispatch(self, el: dict) -> None:
        """Route one element to its handler; captions, headers and footers have none.

        Args:
            el: The element being read.
        """
        handler: Callable[[dict], None] | None = self._handlers.get(el.get("type", ""))
        if handler is not None:
            handler(el)

    def _on_heading(self, el: dict) -> None:
        """A heading is recorded under its parents, then becomes a parent itself.

        Args:
            el: The element being read.
        """
        text: str = self._content(el)
        if not text:
            return
        level: int = HeadingLevel.of(el)
        parent: list[str] = self._heading.open_section(level, text)
        self._blocks.append(
            HeadingBlock(
                kind="heading",
                level=level,
                text=text,
                page_no=self._page_no(el),
                heading_path=parent,
            )
        )

    def _on_paragraph(self, el: dict) -> None:
        """Body text under the open heading path.

        Args:
            el: The element being read.
        """
        text: str = self._content(el)
        if not text:
            return
        self._blocks.append(
            ParagraphBlock(
                kind="paragraph",
                text=text,
                page_no=self._page_no(el),
                heading_path=self._heading.path,
            )
        )

    def _on_table(self, el: dict) -> None:
        """A table with no rows is dropped and counted.

        Args:
            el: The element being read.
        """
        self._tally.table_seen += 1
        block: TableBlock | None = Table.block(el, self._heading.path)
        if block is None:
            self._tally.table_drop += 1
            return
        self._apply_caption(block, el)
        self._blocks.append(block)

    def _apply_caption(self, block: TableBlock, el: dict) -> None:
        """Attach the pre-scanned caption when one links to this table.

        Args:
            block: The layout block being mapped.
            el: The element being read.
        """
        caption: str | None = self._captions.of(el)
        if caption is not None:
            block.caption = caption

    def _on_list(self, el: dict) -> None:
        """A list with no readable items produces nothing.

        Args:
            el: The element being read.
        """
        items: list[str] = self._items(el)
        if not items:
            return
        self._blocks.append(
            ListBlock(
                kind="list",
                items=items,
                ordered=el.get("numbering style", "") == "ordered",
                page_no=self._page_no(el),
                heading_path=self._heading.path,
            )
        )

    def _on_image(self, el: dict) -> None:
        """Images are counted but not carried; ODL embeds them as base64.

        Args:
            el: The element being read.
        """
        self._tally.pic_seen += 1

    def _on_text_block(self, el: dict) -> None:
        """A container whose kids are paragraphs in their own right.

        Args:
            el: The element being read.
        """
        for kid in el.get("kids", []):
            self._append_kid(kid, self._page_no(el))

    def _append_kid(self, kid: dict, fallback_page: int) -> None:
        """One paragraph from inside a text block.

        Args:
            kid: The child element to append.
            fallback_page: The page to use when the element carries none.
        """
        text: str = self._content(kid)
        if not text:
            return
        self._blocks.append(
            ParagraphBlock(
                kind="paragraph",
                text=text,
                page_no=kid.get("page number", fallback_page),
                heading_path=self._heading.path,
            )
        )

    def _pages(self) -> list[PageInfo]:
        """ODL has no pages section, so pages are inferred from the elements.

        Returns:
            One entry per page an element reports.
        """
        return [PageInfo(page_no=number, width=0.0, height=0.0) for number in self._page_numbers()]

    def _page_numbers(self) -> list[int]:
        """Every page number an element reports, sorted.

        Returns:
            Every reported page number, sorted.
        """
        return sorted({el.get("page number", 0) for el in self._kids if el.get("page number")})

    def _meta(self) -> dict[str, Any]:
        """Extractor identity and the options that shaped this parse.

        Returns:
            Extractor identity and the options used.
        """
        return {
            "extractor_name": EngineIdentity.NAME,
            "extractor_version": EngineIdentity.VERSION,
            "options": {"hybrid": "docling-fast"},
        }

    def _log(self, pages: list[PageInfo]) -> None:
        """One line describing what the walk produced.

        Args:
            pages: The pages that were projected.
        """
        tally: Tally = self._tally
        self._LOG.info(
            f"[extract] blocks={len(self._blocks)} pages={len(pages)} "
            f"tables(seen={tally.table_seen} kept={tally.table_seen - tally.table_drop} "
            f"dropped={tally.table_drop}) "
            f"pictures(seen={tally.pic_seen} kept={tally.pic_kept})"
        )

    @staticmethod
    def _items(el: dict) -> list[str]:
        """Every non-empty list item.

        Args:
            el: The element being read.

        Returns:
            Every non-empty list item.
        """
        texts: list[str] = [li.get("content", "").strip() for li in el.get("list items", [])]
        return [text for text in texts if text]

    @staticmethod
    def _content(el: dict) -> str:
        """An element's trimmed text.

        Args:
            el: The element being read.

        Returns:
            The element's trimmed text.
        """
        return el.get("content", "").strip()

    @staticmethod
    def _page_no(el: dict) -> int:
        """The page an element sits on, or 0.

        Args:
            el: The element being read.

        Returns:
            The reported page, or 0.
        """
        return el.get("page number", 0)
