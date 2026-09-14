"""Smoke run: liteparse extractor against PEERDEX_SMOKE_PDF, with gate accounting."""

import os
from collections import Counter
from pathlib import Path

from liteparse import LiteParse

from parse.liteparse import LiteParseExtractor, PictureGate

PDF = Path(os.environ["PEERDEX_SMOKE_PDF"]).expanduser()


def main() -> None:
    extractor: LiteParseExtractor = LiteParseExtractor()
    doc = extractor.extract(PDF)
    print("pages:", len(doc.pages))
    print("block counts:", dict(Counter(block.kind for block in doc.blocks)))
    for block in doc.blocks:
        if block.kind == "picture":
            print(
                f"  kept picture id={block.self_ref} page={block.page_no} "
                f"area={block.bbox_area_pct:.2f}% size={block.pil_image.size} "
                f"mode={block.pil_image.mode}"
            )
        if block.kind == "table":
            print(
                f"  table page={block.page_no} headers={len(block.headers)} "
                f"rows={len(block.rows)}"
            )
        if block.kind == "list":
            print(f"  list page={block.page_no} items={len(block.items)} ordered={block.ordered}")

    gate: PictureGate = PictureGate.from_settings()
    with LiteParse(extract_blocks=True, extract_images=True, ocr_enabled=True, quiet=True) as p:
        result = p.parse(str(PDF))
    image_ids: set[str] = {image.id for image in result.images or []}
    raw_kinds: Counter[str] = Counter()
    for page_num in range(1, result.num_pages + 1):
        page = result.get_page(page_num)
        if page is None:
            continue
        for blk in page.blocks or []:
            raw_kinds[blk.kind] += 1
            if blk.kind != "figure" or blk.bbox is None:
                continue
            area: float = gate.area_pct(blk.bbox, page.width, page.height)
            admitted: float | None = gate.admitted_area_pct(blk.bbox, page.width, page.height)
            reason: str = "kept"
            if blk.id not in image_ids:
                reason = "dropped: no matching image"
            elif area < gate.min_bbox_area_pct:
                reason = f"dropped: area {area:.2f}% < {gate.min_bbox_area_pct}%"
            elif admitted is None:
                reason = "dropped: header/footer band"
            print(
                f"  figure id={blk.id} page={page_num} area={area:.2f}% "
                f"y={blk.bbox.y:.0f} h={blk.bbox.height:.0f} -> {reason}"
            )
    print("raw layout kinds:", dict(raw_kinds))
    print("raw images:", len(result.images or []))


if __name__ == "__main__":
    main()
