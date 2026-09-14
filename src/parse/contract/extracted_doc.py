"""A parsed document, as every stage after parsing sees it."""

from dataclasses import dataclass, field
from typing import Any

from parse.contract.heading_block import HeadingBlock
from parse.contract.list_block import ListBlock
from parse.contract.page_info import PageInfo
from parse.contract.paragraph_block import ParagraphBlock
from parse.contract.picture_block import PictureBlock
from parse.contract.table_block import TableBlock

type Block = HeadingBlock | ParagraphBlock | TableBlock | ListBlock | PictureBlock


@dataclass
class ExtractedDoc:
    """A parsed document; source_meta names the extractor and feeds the cache key."""

    blocks: list[Block]
    pages: list[PageInfo]
    source_meta: dict[str, Any] = field(default_factory=dict)
