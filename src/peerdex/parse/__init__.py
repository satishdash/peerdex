"""Stage 1 - Extractor: PDF -> ExtractedDoc (typed, structured).

Provides a registry so callers can request an extractor by name
(``get_extractor("docling")``). New extractors just implement the
``Extractor`` protocol and register via ``register_extractor()``.
"""

from peerdex.parse._contract import (
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
from peerdex.parse._docling import DoclingExtractor, from_docling_document
from peerdex.parse._docling_rs import DoclingRsExtractor
from peerdex.parse._liteparse import LiteParseExtractor
from peerdex.parse._odl import ODLExtractor
from peerdex.parse._xberg import XbergExtractor

# ---------- registry ----------

_REGISTRY: dict[str, type[Extractor]] = {}


def register_extractor(name: str, cls: type[Extractor]) -> None:
    _REGISTRY[name] = cls


def get_extractor(name: str | None = None) -> Extractor:
    """Return an extractor instance by name. Default is ``docling``."""
    name = name or "docling"
    if name not in _REGISTRY:
        raise ValueError(f"unknown extractor '{name}'. available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def available_extractors() -> list[str]:
    return sorted(_REGISTRY)


# Register built-in extractors
register_extractor("docling", DoclingExtractor)
register_extractor("docling-rs", DoclingRsExtractor)
register_extractor("liteparse", LiteParseExtractor)
register_extractor("odl", ODLExtractor)
register_extractor("xberg", XbergExtractor)


__all__ = [
    "Block",
    "DoclingExtractor",
    "DoclingRsExtractor",
    "ExtractedDoc",
    "Extractor",
    "HeadingBlock",
    "ListBlock",
    "LiteParseExtractor",
    "ODLExtractor",
    "PageInfo",
    "ParagraphBlock",
    "PictureBlock",
    "TableBlock",
    "XbergExtractor",
    "available_extractors",
    "from_docling_document",
    "get_extractor",
    "register_extractor",
]
