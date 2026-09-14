"""Stage 1 - Extractor: a PDF becomes a typed, structured ExtractedDoc."""

from parse.contract import (
    Block,
    ExtractedDoc,
    Extractor,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from parse.docling import DoclingExtractor
from parse.docling_rs import DoclingRsExtractor
from parse.liteparse import LiteParseExtractor
from parse.odl import ODLExtractor
from parse.registry import ExtractorRegistry
from parse.xberg import XbergExtractor

__all__ = [
    "Block",
    "DoclingExtractor",
    "DoclingRsExtractor",
    "ExtractedDoc",
    "Extractor",
    "ExtractorRegistry",
    "HeadingBlock",
    "ListBlock",
    "LiteParseExtractor",
    "ODLExtractor",
    "PageInfo",
    "ParagraphBlock",
    "PictureBlock",
    "TableBlock",
    "XbergExtractor",
]
