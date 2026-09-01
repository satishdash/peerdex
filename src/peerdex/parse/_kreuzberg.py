"""KreuzbergExtractor: PDF -> ExtractedDoc via kreuzberg 4.9 (element-based)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kreuzberg import ExtractionConfig, extract_file

from peerdex.parse._contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    TableBlock,
)
from peerdex.shared.logging import get_logger

log = get_logger("parse.kreuzberg")


def _is_heading(text: str) -> tuple[bool, int]:
    """Check if text looks like a heading.

    Returns (True, level) if heading criteria met, else (False, 0).

    Criteria (ALL must hold):
    - Single line after strip (no newlines or only whitespace after first)
    - Length 2-120 chars
    - Does not end with . , ; or :
    - No sentence-ending period mid-text (no '. ' followed by capital)
    - Digit ratio < 0.30 (avoids numeric-heavy lines)

    Level assignment:
    - All-uppercase ratio > 0.60 → level 1
    - Otherwise → level 2
    """
    stripped = text.strip()

    # Single line check
    lines = stripped.split("\n")
    if len(lines) > 1 and not all(not line.strip() for line in lines[1:]):
        return (False, 0)

    # Length check
    if not (2 <= len(stripped) <= 120):
        return (False, 0)

    # Ending punctuation check
    if stripped and stripped[-1] in ".,:;":
        return (False, 0)

    # Sentence-ending period check: no ". " followed by capital
    if re.search(r"\.\s+[A-Z]", stripped):
        return (False, 0)

    # Digit ratio check
    digits = sum(1 for c in stripped if c.isdigit())
    if len(stripped) > 0 and digits / len(stripped) >= 0.30:
        return (False, 0)

    # Passed all checks
    # Determine level: uppercase ratio > 0.60 → level 1
    uppercase = sum(1 for c in stripped if c.isupper())
    letters = sum(1 for c in stripped if c.isalpha())

    level = 1 if letters > 0 and uppercase / letters > 0.60 else 2
    return (True, level)


def _is_tabular(lines: list[str]) -> bool:
    """Check if lines look like a table (space-aligned columns).

    Returns True if ALL of:
    - len(lines) >= 3
    - Median cell count >= 2
    - Numeric cell ratio >= 0.25
    """
    if len(lines) < 3:
        return False

    # Split by multiple spaces and count cells
    cell_counts = []
    for line in lines:
        cells = [c.strip() for c in re.split(r"  +", line.strip())]
        cells = [c for c in cells if c]  # Remove empty
        cell_counts.append(len(cells))

    if not cell_counts:
        return False

    # Median cell count
    sorted_counts = sorted(cell_counts)
    median = sorted_counts[len(sorted_counts) // 2]
    if median < 2:
        return False

    # Numeric cell ratio
    numeric_pattern = r"^-?[\d,\.]+%?$|^(MEUR|EUR|Mt|%|x)$"
    all_cells = []
    for line in lines:
        cells = [c.strip() for c in re.split(r"  +", line.strip())]
        cells = [c for c in cells if c]
        all_cells.extend(cells)

    if not all_cells:
        return False

    numeric_count = sum(1 for cell in all_cells if re.match(numeric_pattern, cell))

    ratio = numeric_count / len(all_cells)
    return ratio >= 0.25


def _parse_table(
    lines: list[str],
    heading_path: list[str],
    page_no: int,
) -> TableBlock:
    """Parse space-aligned table into TableBlock.

    - Split by multiple spaces → cells
    - Skip separator rows (all cells are - or :)
    - Detect header row if first row has 0 numeric cells and others have >=1
    """
    rows: list[list[str]] = []

    for line in lines:
        cells = [c.strip() for c in re.split(r"  +", line.strip())]
        cells = [c for c in cells if c]

        # Skip separator rows
        if all(re.match(r"^[-:]+$", c) for c in cells):
            continue

        rows.append(cells)

    return TableBlock(
        kind="table",
        rows=rows,
        caption="",
        headers=[],
        page_no=page_no,
        heading_path=heading_path,
    )


def _elements_to_blocks(elements: list[Any] | None) -> list[Any]:  # type: ignore
    """Convert kreuzberg element-based format to Block list.

    Handles:
    - page_break: track current page
    - list_item: accumulate into ListBlock
    - narrative_text: heading detection, table heuristic, paragraph fallback
    """
    blocks: list[Any] = []
    current_page_no = 0
    heading_path: list[str] = []
    pending_list_items: list[str] = []

    if not elements:
        return blocks

    def flush_list() -> None:
        nonlocal pending_list_items
        if pending_list_items:
            blocks.append(
                ListBlock(
                    kind="list",
                    items=pending_list_items,
                    ordered=False,
                    page_no=current_page_no,
                    heading_path=list(heading_path),
                )
            )
            pending_list_items = []

    for element in elements:
        etype = element.get("element_type")
        page = element.get("metadata", {}).get("page_number", current_page_no)
        text = element.get("text", "").strip()

        # page_break: track page number
        if etype == "page_break":
            current_page_no = page
            flush_list()
            continue

        # list_item: accumulate
        if etype == "list_item":
            # Strip bullet prefix
            item_text = re.sub(r"^[•\-\*]\s*", "", text)
            pending_list_items.append(item_text)
            continue

        # narrative_text: main logic
        if etype == "narrative_text" and text:
            # Flush any pending list first
            flush_list()

            # Heading check
            is_h, level = _is_heading(text)
            if is_h:
                # Update heading_path
                heading_path = [*heading_path[: level - 1], text]
                blocks.append(
                    HeadingBlock(
                        kind="heading",
                        text=text,
                        level=level,
                        page_no=page,
                        heading_path=heading_path[:-1],
                    )
                )
                continue

            # Table check: split on newlines
            lines = [line for line in re.split(r"\r?\n", text) if line.strip()]
            if lines and _is_tabular(lines):
                blocks.append(_parse_table(lines, list(heading_path), page))
                continue

            # Paragraph fallback
            blocks.append(
                ParagraphBlock(
                    kind="paragraph",
                    text=text,
                    page_no=page,
                    heading_path=list(heading_path),
                )
            )

    # Flush remaining list
    flush_list()

    return blocks


class KreuzbergExtractor:
    name: str = "kreuzberg"
    version: str = "4.9"

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Extract PDF via kreuzberg (element-based format).

        Tier 1: native table objects (if result.tables is non-empty)
        Tier 2: element-based parsing for headings, heuristic tables, prose, lists
        """
        log.info(f"[kreuzberg] extracting {pdf_path}")

        # Use element_based format for real page numbers and typed elements
        config = ExtractionConfig(use_cache=False, result_format="element_based")
        result = await extract_file(pdf_path, config=config)

        blocks: list[Any] = []

        # Tier 1: native table objects (for Excel/HTML/simple PDFs)
        if result.tables:
            for t in result.tables:  # type: ignore
                # t.cells: list[list[str]]
                rows = [list(row) for row in t.cells]
                if rows:
                    blocks.append(
                        TableBlock(
                            kind="table",
                            rows=rows,
                            caption="",
                            headers=[],
                            page_no=0,
                            heading_path=[],
                        )
                    )

        # Tier 2: element-based parsing (headings, heuristic tables, prose, lists)
        elements = result.elements or []
        element_blocks = _elements_to_blocks(elements)
        blocks.extend(element_blocks)

        log.info(
            f"[kreuzberg] elements={len(elements)} blocks={len(blocks)} "
            f"tables={sum(1 for b in blocks if b.kind == 'table')} "
            f"headings={sum(1 for b in blocks if b.kind == 'heading')}"
        )

        return ExtractedDoc(
            blocks=blocks,  # type: ignore
            pages=[PageInfo(page_no=0, width=0.0, height=0.0)],
            source_meta={
                "extractor_name": "kreuzberg",
                "extractor_version": "4.9",
            },
        )
