"""Extractor contract: PDF -> ExtractedDoc (extractor-agnostic structured form).

Every extractor (Docling today, LlamaParse/Marker/etc. tomorrow) must
emit the same `ExtractedDoc`. Downstream chunker / index code depends
only on this contract -- never on Docling internals.

Block types are intentionally minimal: heading, paragraph, table, list,
picture. That covers what RAG over annual + sustainability reports
actually needs. Blocks carry `page_no` and `heading_path` so the
chunker can group, render Markdown, and tag nodes without re-walking.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol


BlockKind = Literal["heading", "paragraph", "table", "list", "picture"]


@dataclass
class HeadingBlock:
    kind: Literal["heading"]
    level: int                  # 0=title, 1+=section depth
    text: str
    page_no: int                # 1-based
    heading_path: list[str]     # ancestors (excluding self)


@dataclass
class ParagraphBlock:
    kind: Literal["paragraph"]
    text: str
    page_no: int
    heading_path: list[str]


@dataclass
class TableBlock:
    kind: Literal["table"]
    headers: list[str]          # column headers (empty if none detected)
    rows: list[list[str]]       # cell strings, row-major
    caption: str                # caption / table title if any
    page_no: int
    heading_path: list[str]


@dataclass
class ListBlock:
    kind: Literal["list"]
    items: list[str]            # flat list, nesting collapsed
    ordered: bool
    page_no: int
    heading_path: list[str]


@dataclass
class PictureBlock:
    """Carries the rendered PIL image so the VLM stage can describe it.
    `bbox_area_pct` is for downstream filtering / logging only.
    """
    kind: Literal["picture"]
    pil_image: Any              # PIL.Image.Image (RGB)
    bbox_area_pct: float
    page_no: int
    heading_path: list[str]
    self_ref: str = ""          # extractor-specific id, debugging only


Block = (
    HeadingBlock | ParagraphBlock | TableBlock | ListBlock | PictureBlock
)


@dataclass
class PageInfo:
    page_no: int
    width: float
    height: float


@dataclass
class ExtractedDoc:
    blocks: list[Block]
    pages: list[PageInfo]
    source_meta: dict[str, Any] = field(default_factory=dict)
    """source_meta: at minimum {extractor_name, extractor_version, options}.
    Goes into the cache key + node metadata so swapping extractors
    invalidates cleanly and is auditable per-chunk."""


class Extractor(Protocol):
    name: str
    version: str

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        ...
