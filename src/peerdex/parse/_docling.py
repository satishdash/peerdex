"""DoclingExtractor: PDF -> ExtractedDoc.

Wraps Docling's DocumentConverter (singleton) and walks the parsed
DoclingDocument once, producing typed Block instances. Heading stack
is maintained as we walk so every block inherits its section ancestry.

PictureBlocks are pre-filtered by bbox-area % and header/footer-band %
here -- so downstream consumers see only "interesting" pictures.
This keeps extractor responsibilities clean: the chunker / VLM never
needs to know about Docling-specific bbox math.

Caching is owned upstream (peerdex.index.parse_cached). This module is
stateless beyond the @lru_cache'd converter.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from peerdex.parse._contract import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    PageInfo,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger("parse.docling")


# ---------- converter (singleton, model-cache aware) ----------
def _bake_env() -> str:
    s = get_settings()
    path = str(Path(s.docling.artifacts_path).resolve())
    Path(path).mkdir(parents=True, exist_ok=True)
    os.environ["DOCLING_ARTIFACTS_PATH"] = path
    return path


@lru_cache(maxsize=1)
def _converter():
    artifacts = _bake_env()
    has_models = any(Path(artifacts).iterdir())
    log.info(f"DOCLING_ARTIFACTS_PATH={artifacts} (cached={has_models})")

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    s = get_settings()
    opts = PdfPipelineOptions()
    opts.do_ocr = s.docling.do_ocr
    opts.do_table_structure = s.docling.do_table_structure
    opts.generate_page_images = s.docling.generate_page_images
    opts.generate_picture_images = s.docling.generate_picture_images
    opts.images_scale = s.docling.picture_image_scale
    # Tiny-bitmap filtering is done downstream via vlm.min_bbox_area_pct;
    # Docling's own bitmap_area_threshold is an OCR-only knob and we run
    # with do_ocr=False, so we don't set it here.
    if has_models:
        opts.artifacts_path = artifacts
    else:
        log.warning(f"no models in {artifacts}; Docling will auto-download on first parse")
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


# ---------- bbox / page helpers ----------
def _page_no(item: Any) -> int:
    return int(item.prov[0].page_no) if getattr(item, "prov", None) else 0


def _bbox_area_pct(item: Any, doc: Any) -> float | None:
    if not getattr(item, "prov", None):
        return None
    prov = item.prov[0]
    page = doc.pages.get(prov.page_no)
    if page is None or page.size is None:
        return None
    page_area = page.size.width * page.size.height
    if page_area <= 0:
        return None
    bb = prov.bbox
    pic_area = abs((bb.r - bb.l) * (bb.t - bb.b))
    return 100.0 * pic_area / page_area


def _in_header_footer_band(item: Any, doc: Any, band_pct: float) -> bool:
    if not getattr(item, "prov", None):
        return False
    prov = item.prov[0]
    page = doc.pages.get(prov.page_no)
    if page is None or page.size is None:
        return False
    h = page.size.height
    band = h * band_pct / 100.0
    bb = prov.bbox
    top = max(bb.t, bb.b)
    bot = min(bb.t, bb.b)
    return bot >= h - band or top <= band


def _table_to_block(item: Any, doc: Any, heading_path: list[str]) -> TableBlock | None:
    try:
        df = item.export_to_dataframe(doc=doc)
    except Exception as e:  # pragma: no cover - defensive
        log.debug(f"[docling] table export failed: {e}")
        return None
    headers = [str(c) for c in df.columns]
    rows = [[str(v) for v in row] for row in df.itertuples(index=False, name=None)]
    caption = ""
    if hasattr(item, "caption_text"):
        try:
            caption = (item.caption_text(doc) or "").strip()
        except Exception:
            caption = ""
    return TableBlock(
        kind="table",
        headers=headers,
        rows=rows,
        caption=caption,
        page_no=_page_no(item),
        heading_path=list(heading_path),
    )


# ---------- the extractor ----------
class DoclingExtractor:
    name = "docling"
    version = "2.90"  # bump when behaviour changes; goes into cache key

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        log.info(f"extracting {pdf_path}")
        doc = _converter().convert(str(pdf_path)).document
        return _to_extracted_doc(doc)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """The async half of the contract. Docling's converter is synchronous."""
        return self.extract(pdf_path)


def from_docling_document(doc: Any) -> ExtractedDoc:
    """Public hook so cached `DoclingDocument` pickles can be re-projected
    without re-running the converter. Used by the cache layer."""
    return _to_extracted_doc(doc)


def _to_extracted_doc(doc: Any) -> ExtractedDoc:
    s = get_settings()
    min_pic_area = s.vlm.min_bbox_area_pct
    band_pct = s.vlm.skip_header_footer_band_pct

    pages: list[PageInfo] = []
    for page_no, page in doc.pages.items():
        if page.size is None:
            continue
        pages.append(
            PageInfo(
                page_no=int(page_no), width=float(page.size.width), height=float(page.size.height)
            )
        )

    blocks: list = []
    heading_stack: list[tuple[int, str]] = []  # (level, title)

    pic_seen = pic_kept = pic_drop_area = pic_drop_band = pic_drop_noimg = 0
    table_drop = 0

    for item, _level in doc.iterate_items():
        cls = type(item).__name__
        heading_path = [t for _, t in heading_stack if t]

        if cls == "TitleItem":
            txt = (item.text or "").strip()
            if not txt:
                continue
            heading_stack[:] = [(0, txt)]
            blocks.append(
                HeadingBlock(
                    kind="heading",
                    level=0,
                    text=txt,
                    page_no=_page_no(item),
                    heading_path=[],
                )
            )
            continue

        if cls == "SectionHeaderItem":
            lvl = int(getattr(item, "level", 1) or 1)
            txt = (item.text or "").strip()
            if not txt:
                continue
            heading_stack[:] = [h for h in heading_stack if h[0] < lvl]
            blocks.append(
                HeadingBlock(
                    kind="heading",
                    level=lvl,
                    text=txt,
                    page_no=_page_no(item),
                    heading_path=[t for _, t in heading_stack if t],
                )
            )
            heading_stack.append((lvl, txt))
            continue

        if cls == "TextItem":
            txt = (item.text or "").strip()
            if not txt:
                continue
            blocks.append(
                ParagraphBlock(
                    kind="paragraph",
                    text=txt,
                    page_no=_page_no(item),
                    heading_path=heading_path,
                )
            )
            continue

        if cls == "ListItem":
            txt = (item.text or "").strip()
            if not txt:
                continue
            # Coalesce adjacent ListItems into one ListBlock when possible.
            ordered = bool(getattr(item, "enumerated", False))
            if (
                blocks
                and isinstance(blocks[-1], ListBlock)
                and blocks[-1].page_no == _page_no(item)
                and blocks[-1].heading_path == heading_path
                and blocks[-1].ordered == ordered
            ):
                blocks[-1].items.append(txt)
            else:
                blocks.append(
                    ListBlock(
                        kind="list",
                        items=[txt],
                        ordered=ordered,
                        page_no=_page_no(item),
                        heading_path=heading_path,
                    )
                )
            continue

        if cls == "TableItem":
            tb = _table_to_block(item, doc, heading_path)
            if tb is None:
                table_drop += 1
                continue
            blocks.append(tb)
            continue

        if cls == "PictureItem":
            pic_seen += 1
            area = _bbox_area_pct(item, doc)
            if area is None or area < min_pic_area:
                pic_drop_area += 1
                continue
            if _in_header_footer_band(item, doc, band_pct):
                pic_drop_band += 1
                continue
            try:
                img = item.get_image(doc)
            except Exception as e:  # pragma: no cover
                log.debug(f"[docling] get_image failed: {e}")
                img = None
            if img is None:
                pic_drop_noimg += 1
                continue
            blocks.append(
                PictureBlock(
                    kind="picture",
                    pil_image=img,
                    bbox_area_pct=float(area),
                    page_no=_page_no(item),
                    heading_path=heading_path,
                    self_ref=getattr(item, "self_ref", "") or "",
                )
            )
            pic_kept += 1
            continue

        # Unknown / skipped item types: silently ignore.

    log.info(
        f"[extract] blocks={len(blocks)} pages={len(pages)} "
        f"pictures(seen={pic_seen} kept={pic_kept} "
        f"drop_area={pic_drop_area} drop_band={pic_drop_band} "
        f"drop_noimg={pic_drop_noimg}) "
        f"tables_dropped={table_drop}"
    )

    s = get_settings()
    return ExtractedDoc(
        blocks=blocks,
        pages=pages,
        source_meta={
            "extractor_name": "docling",
            "extractor_version": DoclingExtractor.version,
            "options": {
                "do_ocr": s.docling.do_ocr,
                "do_table_structure": s.docling.do_table_structure,
                "picture_image_scale": s.docling.picture_image_scale,
                "min_bbox_area_pct": s.vlm.min_bbox_area_pct,
                "skip_header_footer_band_pct": s.vlm.skip_header_footer_band_pct,
            },
        },
    )
