"""Protocols."""

from parse.xberg.protocols.box_like import BoxLike
from parse.xberg.protocols.document_like import DocumentLike
from parse.xberg.protocols.element_like import ElementLike
from parse.xberg.protocols.image_like import ImageLike
from parse.xberg.protocols.metadata_like import MetadataLike
from parse.xberg.protocols.page_like import PageLike
from parse.xberg.protocols.table_like import TableLike

__all__ = [
    "BoxLike",
    "DocumentLike",
    "ElementLike",
    "ImageLike",
    "MetadataLike",
    "PageLike",
    "TableLike",
]
