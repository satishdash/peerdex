"""PDF -> ExtractedDoc adapter around the native liteparse parser."""

import asyncio
from pathlib import Path
from typing import Any, ClassVar

from liteparse import LiteParse, ParseResult

from parse.contract import (
    ExtractedDoc,
)
from parse.liteparse.lite_parse_projector import LiteParseProjector
from parse.liteparse.picture_gate import PictureGate
from parse.liteparse.protocols.parse_result_like import ParseResultLike
from shared.logging import Logging
from shared.package_version import PackageVersion


class LiteParseExtractor:
    """PDF -> ExtractedDoc adapter around the native liteparse parser."""

    _LOG: ClassVar[Any] = Logging.get("parse.liteparse")

    name: str = "liteparse"
    version: str = PackageVersion.of("liteparse")

    def __init__(self, gate: PictureGate | None = None) -> None:
        """Build the figure gate and the projector that uses it.

        Args:
            gate: Decides which pictures are worth describing.
        """
        self._gate: PictureGate = gate if gate is not None else PictureGate.from_settings()
        self._projector: LiteParseProjector = LiteParseProjector(self._gate)

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Parse the PDF with blocks + images enabled and project the result.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        self._LOG.info(f"extracting {pdf_path} via liteparse")
        with LiteParse(
            extract_blocks=True, extract_images=True, ocr_enabled=True, quiet=True
        ) as parser:
            result: ParseResult = parser.parse(str(pdf_path))
        return self.project(result)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Run ``extract`` in a worker thread to keep the event loop free.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        return await asyncio.to_thread(self.extract, pdf_path)

    def project(self, result: ParseResultLike) -> ExtractedDoc:
        """Public seam: project any parse-result-shaped object onto the contract.

        Args:
            result: The parser's raw result.

        Returns:
            The projected document.
        """
        blocks, pages = self._projector.project(result)
        self._LOG.info(f"[liteparse] blocks={len(blocks)} pages={len(pages)}")
        return ExtractedDoc(blocks=blocks, pages=pages, source_meta=self._source_meta())

    def _source_meta(self) -> dict[str, Any]:
        """Extractor identity and the options that shaped this parse.

        Returns:
            Extractor identity and the options used.
        """
        return {
            "extractor_name": self.name,
            "extractor_version": self.version,
            "options": {
                "extract_blocks": True,
                "extract_images": True,
                "ocr_enabled": True,
                "min_bbox_area_pct": self._gate.min_bbox_area_pct,
                "skip_header_footer_band_pct": self._gate.skip_header_footer_band_pct,
            },
        }
