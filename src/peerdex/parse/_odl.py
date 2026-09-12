"""ODLExtractor: PDF -> ExtractedDoc via OpenDataLoader hybrid mode.

Uses OpenDataLoader's Java parser + docling hybrid backend for tables/figures.
Hybrid mode routes table-heavy pages through a running docling server while
prose pages are handled by the fast Java parser — giving ~3-4x speedup over
pure docling with near-identical table accuracy (0.928 vs 0.887).

Requirements:
    - Java 11+ (``java`` on PATH)
    - ``opendataloader-pdf[hybrid]`` installed
    - Hybrid server running: ``opendataloader-pdf-hybrid [--port 5002]``

Caching is owned upstream (peerdex.index.parse_cached). This module is stateless.
"""

import json
import tempfile
from pathlib import Path

from peerdex.parse._contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    TableBlock,
)
from peerdex.shared.logging import get_logger

log = get_logger("parse.odl")

# Default hybrid server URL.  Override via settings if needed later.
_DEFAULT_HYBRID_URL = "http://localhost:5002"


# ── ODL JSON → Block converters ──────────────────────────────────────


def _cell_text(cell: dict) -> str:
    """Extract text from a table cell by concatenating all nested kids."""
    parts: list[str] = []
    for kid in cell.get("kids", []):
        t = kid.get("content", "").strip()
        if t:
            parts.append(t)
    return " ".join(parts)


def _table_element_to_block(el: dict, heading_path: list[str]) -> TableBlock | None:
    """Convert an ODL ``table`` element to a TableBlock."""
    rows_raw = el.get("rows", [])
    if not rows_raw:
        return None

    num_cols = el.get("number of columns", 0)
    all_rows: list[list[str]] = []
    for row in rows_raw:
        cells = row.get("cells", [])
        # Build a row list sized to num_cols, filling by column number.
        row_data = [""] * max(num_cols, len(cells))
        for cell in cells:
            col_idx = cell.get("column number", 1) - 1  # 1-indexed → 0
            row_data[col_idx] = _cell_text(cell)
        all_rows.append(row_data)

    # First row is headers if the table has > 1 row.
    if len(all_rows) > 1:
        headers = all_rows[0]
        data_rows = all_rows[1:]
    else:
        headers = []
        data_rows = all_rows

    # Caption: look for a linked caption element upstream (caller can
    # supply it); for now we leave it empty — same as docling fallback.
    return TableBlock(
        kind="table",
        headers=headers,
        rows=data_rows,
        caption="",
        page_no=el.get("page number", 0),
        heading_path=list(heading_path),
    )


def _heading_level(el: dict) -> int:
    """Map ODL heading level string / int to our 0-based scheme."""
    raw = el.get("heading level", el.get("level", "1"))
    if isinstance(raw, int):
        return raw
    mapping = {"Title": 0, "Subtitle": 1}
    if raw in mapping:
        return mapping[raw]
    try:
        return int(raw)
    except TypeError, ValueError:
        return 1


# ── Main conversion: ODL JSON → ExtractedDoc ─────────────────────────


def _json_to_extracted_doc(data: dict) -> ExtractedDoc:
    """Walk the top-level ``kids`` array and produce typed Blocks."""
    blocks: list = []
    heading_stack: list[tuple[int, str]] = []
    captions: dict[int, str] = {}  # linked_content_id → caption text

    # Pre-scan for captions so tables/images can pick them up.
    for el in data.get("kids", []):
        if el.get("type") == "caption":
            linked_id = el.get("linked content id")
            if linked_id is not None:
                captions[linked_id] = el.get("content", "").strip()

    table_count = table_drop = 0
    pic_seen = pic_kept = 0

    for el in data.get("kids", []):
        etype = el.get("type", "")
        page_no = el.get("page number", 0)
        heading_path = [t for _, t in heading_stack if t]

        # ── headings ──
        if etype == "heading":
            txt = el.get("content", "").strip()
            if not txt:
                continue
            lvl = _heading_level(el)
            heading_stack[:] = [h for h in heading_stack if h[0] < lvl]
            blocks.append(
                HeadingBlock(
                    kind="heading",
                    level=lvl,
                    text=txt,
                    page_no=page_no,
                    heading_path=[t for _, t in heading_stack if t],
                )
            )
            heading_stack.append((lvl, txt))
            continue

        # ── paragraphs ──
        if etype == "paragraph":
            txt = el.get("content", "").strip()
            if not txt:
                continue
            blocks.append(
                ParagraphBlock(
                    kind="paragraph",
                    text=txt,
                    page_no=page_no,
                    heading_path=heading_path,
                )
            )
            continue

        # ── tables ──
        if etype == "table":
            table_count += 1
            tb = _table_element_to_block(el, heading_path)
            if tb is None:
                table_drop += 1
                continue
            # Attach caption if available.
            el_id = el.get("id")
            if el_id is not None and el_id in captions:
                tb.caption = captions[el_id]
            blocks.append(tb)
            continue

        # ── lists ──
        if etype == "list":
            items: list[str] = []
            ordered = el.get("numbering style", "") == "ordered"
            for li in el.get("list items", []):
                txt = li.get("content", "").strip()
                if txt:
                    items.append(txt)
            if items:
                blocks.append(
                    ListBlock(
                        kind="list",
                        items=items,
                        ordered=ordered,
                        page_no=page_no,
                        heading_path=heading_path,
                    )
                )
            continue

        # ── images ──
        if etype == "image":
            pic_seen += 1
            # ODL can embed base64 images; for now we skip them (same as
            # docling pre-filter).  VLM support can be added later by
            # decoding el["data"] into a PIL image.
            # TODO: decode base64 data URI → PictureBlock when VLM is needed.
            continue

        # ── captions / headers / footers / text blocks — skip ──
        if etype in ("caption", "header", "footer"):
            continue

        # ── text block (container) — recurse into kids ──
        if etype == "text block":
            for kid in el.get("kids", []):
                txt = kid.get("content", "").strip()
                if txt:
                    blocks.append(
                        ParagraphBlock(
                            kind="paragraph",
                            text=txt,
                            page_no=kid.get("page number", page_no),
                            heading_path=heading_path,
                        )
                    )
            continue

    # ── pages ──
    # ODL doesn't have a dedicated pages section; infer from elements.
    page_nos = sorted(
        {el.get("page number", 0) for el in data.get("kids", []) if el.get("page number")}
    )
    pages = [PageInfo(page_no=p, width=0.0, height=0.0) for p in page_nos]

    log.info(
        f"[extract] blocks={len(blocks)} pages={len(pages)} "
        f"tables(seen={table_count} kept={table_count - table_drop} "
        f"dropped={table_drop}) "
        f"pictures(seen={pic_seen} kept={pic_kept})"
    )

    return ExtractedDoc(
        blocks=blocks,
        pages=pages,
        source_meta={
            "extractor_name": "odl",
            "extractor_version": ODLExtractor.version,
            "options": {"hybrid": "docling-fast"},
        },
    )


# ── The extractor ────────────────────────────────────────────────────


class ODLExtractor:
    name = "odl"
    version = "1.0"  # bump when behaviour changes; goes into cache key

    def __init__(
        self,
        hybrid_url: str = _DEFAULT_HYBRID_URL,
    ) -> None:
        self.hybrid_url = hybrid_url

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        from opendataloader_pdf import convert

        pdf_path = Path(pdf_path).resolve()
        log.info(f"extracting {pdf_path} (hybrid → {self.hybrid_url})")

        with tempfile.TemporaryDirectory(prefix="odl_") as tmp:
            convert(
                input_path=str(pdf_path),
                output_dir=tmp,
                format="json",
                quiet=True,
                hybrid="docling-fast",
                hybrid_url=self.hybrid_url,
            )
            # ODL writes <stem>.json in output_dir.
            json_files = list(Path(tmp).glob("*.json"))
            if not json_files:
                raise RuntimeError(f"ODL produced no JSON output for {pdf_path}")
            data = json.loads(json_files[0].read_text())

        return _json_to_extracted_doc(data)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """The async half of the contract. The ODL converter is synchronous."""
        return self.extract(pdf_path)
