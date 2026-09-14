"""Turns one xberg document into the shared block contract. Pure."""

from typing import Any

from parse.contract import (
    Block,
    PageInfo,
    TableBlock,
)
from parse.liteparse import PictureGate
from parse.xberg.heading_rule import HeadingRule
from parse.xberg.image_projector import ImageProjector
from parse.xberg.mappers.element_mapper import ElementMapper
from parse.xberg.mappers.heading_mapper import HeadingMapper
from parse.xberg.mappers.list_item_mapper import ListItemMapper
from parse.xberg.mappers.narrative_mapper import NarrativeMapper
from parse.xberg.mappers.skip_mapper import SkipMapper
from parse.xberg.mappers.title_mapper import TitleMapper
from parse.xberg.projection_state import ProjectionState
from parse.xberg.protocols.document_like import DocumentLike
from parse.xberg.protocols.element_like import ElementLike
from parse.xberg.protocols.metadata_like import MetadataLike
from parse.xberg.protocols.table_like import TableLike


class XbergProjector:
    """Turns one xberg document into the shared block contract. Pure."""

    def __init__(self, rule: HeadingRule | None = None, gate: PictureGate | None = None) -> None:
        """Bind one mapper to each element kind.

        Args:
            rule: Decides which elements count as headings.
            gate: Decides which pictures are worth describing.
        """
        heading_rule: HeadingRule = rule or HeadingRule()
        self._images: ImageProjector = ImageProjector(gate or PictureGate.from_settings())
        self._fallback: ElementMapper = NarrativeMapper(heading_rule)
        self._skip: ElementMapper = SkipMapper()
        self._mappers: dict[str, ElementMapper] = {
            "title": TitleMapper(),
            "heading": HeadingMapper(),
            "narrative_text": self._fallback,
            "list_item": ListItemMapper(),
            "page_break": self._skip,
            "table": self._skip,
            "header": self._skip,
            "footer": self._skip,
            "image": self._skip,
        }

    def project(self, document: DocumentLike) -> tuple[list[Block], list[PageInfo]]:
        """Elements in reading order, then native tables, then gated figures.

        Args:
            document: The parsed document.

        Returns:
            The projected blocks and the pages they came from.
        """
        state: ProjectionState = ProjectionState()
        for element in document.elements or []:
            self._project_element(element, state)
        for table in document.tables or []:
            self._project_table(table, state)
        self._images.project(list(document.images or []), state)
        return state.blocks, self._pages(document)

    def _project_element(self, element: ElementLike, state: ProjectionState) -> None:
        """Route one element to its mapper, skipping empty text.

        Args:
            element: The element being projected.
            state: The accumulator this projection is building into.
        """
        text: str = (element.text or "").strip()
        if not text:
            return
        state.observe(self._page_of(element.metadata))
        mapper: ElementMapper = self._mappers.get(self._kind(element.element_type), self._fallback)
        mapper.map(text, state)

    def _project_table(self, table: TableLike, state: ProjectionState) -> None:
        """Append a native table, dropping one with no populated rows.

        Args:
            table: The table element being projected.
            state: The accumulator this projection is building into.
        """
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
    def _kind(element_type: Any) -> str:
        """An element type normalised to a lower-case name.

        Args:
            element_type: The element's type name as the engine spells it.

        Returns:
            The element type as a lower-case name.
        """
        return str(getattr(element_type, "value", element_type)).strip().lower()

    @staticmethod
    def _page_of(metadata: MetadataLike | None) -> int:
        """The page an element's metadata reports, or 0.

        Args:
            metadata: The document's metadata.

        Returns:
            The reported page, or 0.
        """
        return int(getattr(metadata, "page_number", 0) or 0)

    @staticmethod
    def _pages(document: DocumentLike) -> list[PageInfo]:
        """One PageInfo per reported page; xberg reports no page size.

        Args:
            document: The parsed document.

        Returns:
            One entry per reported page.
        """
        return [
            PageInfo(page_no=int(page.page_number or 0), width=0.0, height=0.0)
            for page in (document.pages or [])
        ]
