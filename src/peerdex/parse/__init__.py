"""Stage 1 - Extractor: PDF -> ExtractedDoc (typed, structured).

Provides a registry so callers can request an extractor by name
(``get_extractor("docling")``). New extractors just implement the
``Extractor`` protocol and register via ``register_extractor()``.
"""
from peerdex.parse._contract import (
    Block,
    Extractor,
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from peerdex.parse._docling import DoclingExtractor, from_docling_document
from peerdex.parse._liteparse import LiteParseExtractor
from peerdex.parse._odl import ODLExtractor

# ---------- registry ----------

_REGISTRY: dict[str, type[Extractor]] = {}


def register_extractor(name: str, cls: type[Extractor]) -> None:
    _REGISTRY[name] = cls


def get_extractor(name: str | None = None) -> Extractor:
    """Return an extractor instance by name. Default is ``docling``."""
    name = name or "docling"
    if name not in _REGISTRY:
        raise ValueError(
            f"unknown extractor '{name}'. available: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]()


def available_extractors() -> list[str]:
    return sorted(_REGISTRY)


# Register built-in extractors
register_extractor("docling", DoclingExtractor)
register_extractor("liteparse", LiteParseExtractor)
register_extractor("odl", ODLExtractor)


__all__ = [
    "Extractor", "ExtractedDoc",
    "Block", "HeadingBlock", "ParagraphBlock", "TableBlock",
    "ListBlock", "PictureBlock", "PageInfo",
    "DoclingExtractor", "from_docling_document",
    "LiteParseExtractor",
    "ODLExtractor",
    "get_extractor", "register_extractor", "available_extractors",
]
