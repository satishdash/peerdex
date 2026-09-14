"""Extractor port: a PDF becomes an extractor-agnostic ExtractedDoc."""

from parse.contract.extracted_doc import Block, ExtractedDoc
from parse.contract.extractor import Extractor
from parse.contract.heading_block import HeadingBlock
from parse.contract.list_block import ListBlock
from parse.contract.page_info import PageInfo
from parse.contract.paragraph_block import ParagraphBlock
from parse.contract.picture_block import PictureBlock
from parse.contract.table_block import TableBlock

__all__ = [
    "Block",
    "ExtractedDoc",
    "Extractor",
    "HeadingBlock",
    "ListBlock",
    "PageInfo",
    "ParagraphBlock",
    "PictureBlock",
    "TableBlock",
]
