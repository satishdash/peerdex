"""LiteParseExtractor: PDF -> ExtractedDoc via LiteParse CLI.

LiteParse (https://github.com/run-llama/liteparse) is a fast, local PDF
text parser built on PDF.js + optional Tesseract OCR. It outputs spatial
text with bounding boxes but **no table structure detection** — every page
becomes a single ParagraphBlock of raw text.

This is intentionally a minimal/baseline extractor to benchmark parsing
speed against docling. Table-heavy downstream tasks (peer report QA)
will produce worse retrieval quality than docling, but the speed
difference is the point of this extractor.

Requirements:
    - Node.js 18+
    - ``npm i -g @llamaindex/liteparse`` (provides the ``lit`` CLI)
"""
import json
import subprocess
from pathlib import Path

from peerdex.parse._contract import (
    ExtractedDoc,
    HeadingBlock,
    PageInfo,
    ParagraphBlock,
)
from peerdex.shared.logging import get_logger

log = get_logger("parse.liteparse")

# Heuristic: lines in ALL-CAPS or very short bold-looking lines at the
# top of a page are likely headings.  We keep it simple — first non-empty
# line per page if <=80 chars and >50% uppercase is treated as a heading.
_HEADING_MAX_LEN = 80
_HEADING_UPPER_RATIO = 0.50


def _looks_like_heading(line: str) -> bool:
    if not line or len(line) > _HEADING_MAX_LEN:
        return False
    alpha = [c for c in line if c.isalpha()]
    if not alpha:
        return False
    return sum(1 for c in alpha if c.isupper()) / len(alpha) >= _HEADING_UPPER_RATIO


def _json_to_extracted_doc(data: dict) -> ExtractedDoc:
    """Convert liteparse JSON (pages with text + textItems) to ExtractedDoc."""
    blocks: list = []
    pages: list[PageInfo] = []
    heading_stack: list[tuple[int, str]] = []

    for page in data.get("pages", []):
        page_no: int = page.get("page", 0)
        width: float = float(page.get("width", 0))
        height: float = float(page.get("height", 0))
        pages.append(PageInfo(page_no=page_no, width=width, height=height))

        text: str = (page.get("text") or "").strip()
        if not text:
            continue

        lines = text.split("\n")
        heading_path = [t for _, t in heading_stack if t]

        # Check if first non-empty line is a heading.
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if _looks_like_heading(line):
                heading_stack[:] = [(0, line)]
                blocks.append(HeadingBlock(
                    kind="heading", level=0, text=line,
                    page_no=page_no, heading_path=[],
                ))
                heading_path = [line]
                # Remove heading from body text.
                text = text.replace(line, "", 1).strip()
            break  # only check first non-empty line

        if text:
            blocks.append(ParagraphBlock(
                kind="paragraph", text=text,
                page_no=page_no, heading_path=heading_path,
            ))

    log.info(
        f"[extract] blocks={len(blocks)} pages={len(pages)}"
    )

    return ExtractedDoc(
        blocks=blocks,
        pages=pages,
        source_meta={
            "extractor_name": "liteparse",
            "extractor_version": LiteParseExtractor.version,
            "options": {"ocr": True, "format": "json"},
        },
    )


class LiteParseExtractor:
    name = "liteparse"
    version = "1.0"  # bump when behaviour changes; goes into cache key

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        pdf_path = Path(pdf_path).resolve()
        log.info(f"extracting {pdf_path} via liteparse CLI")

        result = subprocess.run(
            ["lit", "parse", str(pdf_path), "--format", "json", "-q"],
            capture_output=True,
            text=True,
            timeout=600,  # 10 min ceiling
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"liteparse failed (rc={result.returncode}): {result.stderr[:500]}"
            )

        data = json.loads(result.stdout)
        return _json_to_extracted_doc(data)
