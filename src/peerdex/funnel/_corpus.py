"""Searchable corpus: contract blocks rendered to text with their provenance."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from peerdex.parse import (
    Block,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)


@dataclass(frozen=True)
class SearchableBlock:
    """One unit of searchable text and where it came from."""

    source: str
    page_no: int
    kind: str
    heading_path: str
    text: str


class BlockProjector:
    """Renders contract blocks into searchable text; pictures need a VLM description."""

    def __init__(self) -> None:
        self._renderers: dict[type, Callable[[Any], str]] = {
            HeadingBlock: lambda block: str(block.text),
            ParagraphBlock: lambda block: str(block.text),
            ListBlock: lambda block: "\n".join(block.items),
            TableBlock: self._table_text,
        }

    def project(self, source: str, blocks: Sequence[Block]) -> list[SearchableBlock]:
        """Text-bearing blocks with provenance; PictureBlocks are left to project_pictures."""
        return [
            self._searchable(source, block, renderer(block))
            for block in blocks
            if (renderer := self._renderers.get(type(block))) is not None
        ]

    def project_pictures(
        self,
        source: str,
        pictures: Sequence[PictureBlock],
        descriptions: Sequence[Mapping[str, Any] | None],
    ) -> list[SearchableBlock]:
        """Pictures whose VLM description exists, rendered to searchable text."""
        return [
            self._searchable(source, picture, self._picture_text(description))
            for picture, description in zip(pictures, descriptions, strict=True)
            if description is not None
        ]

    @staticmethod
    def _searchable(source: str, block: Block, text: str) -> SearchableBlock:
        return SearchableBlock(
            source=source,
            page_no=block.page_no,
            kind=block.kind,
            heading_path=" > ".join(block.heading_path),
            text=text,
        )

    @staticmethod
    def _table_text(table: TableBlock) -> str:
        rows: list[str] = [" | ".join(row) for row in [table.headers, *table.rows] if row]
        return "\n".join(part for part in [table.caption, *rows] if part)

    @staticmethod
    def _picture_text(description: Mapping[str, Any]) -> str:
        values: list[str] = [
            f"{item.get('label', '')}: {item.get('value', '')} {item.get('unit', '')}".strip()
            for item in description.get("values") or []
        ]
        parts: list[str] = [
            str(description.get("title") or ""),
            str(description.get("description") or ""),
            *values,
        ]
        return "\n".join(part for part in parts if part)
