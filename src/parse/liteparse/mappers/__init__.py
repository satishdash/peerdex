"""Mappers."""

from parse.liteparse.mappers.block_mapper import BlockMapper
from parse.liteparse.mappers.figure_mapper import FigureMapper
from parse.liteparse.mappers.heading_mapper import HeadingMapper
from parse.liteparse.mappers.list_item_mapper import ListItemMapper
from parse.liteparse.mappers.paragraph_mapper import ParagraphMapper
from parse.liteparse.mappers.table_mapper import TableMapper

__all__ = [
    "BlockMapper",
    "FigureMapper",
    "HeadingMapper",
    "ListItemMapper",
    "ParagraphMapper",
    "TableMapper",
]
