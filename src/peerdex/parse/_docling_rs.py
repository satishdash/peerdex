"""DoclingRsExtractor: PDF -> ExtractedDoc via docling.rs, the Rust port of docling.

The engine returns docling-core's wire format, so ``result.document`` is a real
``DoclingDocument`` and the existing ``from_docling_document`` projection is
reused untouched. Only the provenance in ``source_meta`` is restamped, so a
chunk can be traced to the engine that produced it.

PDF conversion needs a pdfium shared library, which upstream ships for Linux
only. ``docling.pdfium_lib_path`` names a local one; without it the engine
raises at conversion time rather than degrading silently.
"""

import os
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from peerdex.parse._contract import ExtractedDoc
from peerdex.parse._docling import from_docling_document
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger(__name__)

_PDFIUM_ENV: str = "PDFIUM_DYNAMIC_LIB_PATH"


def _bake_pdfium() -> None:
    configured: str = get_settings().docling.pdfium_lib_path
    if configured and not os.environ.get(_PDFIUM_ENV):
        os.environ[_PDFIUM_ENV] = str(Path(configured).expanduser().resolve())


@lru_cache(maxsize=1)
def _converter() -> Any:
    _bake_pdfium()
    from docling_rs import DocumentConverter

    settings: Any = get_settings()
    log.info(f"{_PDFIUM_ENV}={os.environ.get(_PDFIUM_ENV, '<unset>')}")
    return DocumentConverter(
        do_ocr=settings.docling.do_ocr,
        do_table_structure=settings.docling.do_table_structure,
        heading_hierarchy=settings.docling_rs.heading_hierarchy,
        no_text_panels=settings.docling_rs.no_text_panels,
        artifacts_path=_artifacts(settings.docling_rs.artifacts_path),
    )


def _artifacts(configured: str) -> str | None:
    """Override the model cache dir only when one is named, else upstream's default."""
    if not configured:
        return None
    return str(Path(configured).expanduser().resolve())


class DoclingRsExtractor:
    """Adapter over docling.rs, projected by docling's own walker."""

    name: str = "docling-rs"
    version: str = "1.43"

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Convert one PDF, then restamp provenance onto the shared projection."""
        log.info(f"extracting {pdf_path}")
        document: Any = _converter().convert(str(pdf_path)).document
        projected: ExtractedDoc = from_docling_document(document)
        return replace(projected, source_meta=self._source_meta(projected))

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        return self.extract(pdf_path)

    def _source_meta(self, projected: ExtractedDoc) -> dict[str, Any]:
        meta: dict[str, Any] = dict(projected.source_meta)
        meta["extractor_name"] = self.name
        meta["extractor_version"] = self.version
        return meta
