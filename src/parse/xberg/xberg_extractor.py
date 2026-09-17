"""Adapter: one xberg call, then the pure projection."""

import asyncio
from pathlib import Path
from typing import Any, ClassVar

from parse.contract import (
    ExtractedDoc,
)
from parse.xberg.xberg_projector import XbergProjector
from shared.logging import Logging
from shared.package_version import PackageVersion
from shared.settings import get_settings


class XbergExtractor:
    """Adapter: one xberg call, then the pure projection."""

    _LOG: ClassVar[Any] = Logging.get(__name__)

    name: str = "xberg"
    version: str = PackageVersion.of("xberg")

    def __init__(self, projector: XbergProjector | None = None) -> None:
        """Hold the projector, building a default one when none is given.

        Args:
            projector: Projects a parsed document onto the contract.
        """
        self._projector: XbergProjector = projector or XbergProjector()

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Parse a PDF by running the async path to completion.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        return asyncio.run(self.extract_async(pdf_path))

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Extract one PDF, asking xberg for its element-based result format.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        import xberg

        self._LOG.info(f"[xberg] extracting {pdf_path}")
        config: Any = xberg.ExtractionConfig(
            use_cache=False,
            result_format="element_based",
            images=xberg.ImageExtractionConfig(
                extract_images=True,
                target_dpi=get_settings().xberg.target_dpi,
                run_ocr_on_images=False,
                inject_placeholders=False,
            ),
        )
        result: Any = await xberg.extract(
            xberg.ExtractInput(kind="uri", uri=str(pdf_path)), config=config
        )
        blocks, pages = self._projector.project(result.results[0])
        pictures: int = sum(1 for block in blocks if block.kind == "picture")
        self._LOG.info(f"[xberg] blocks={len(blocks)} pages={len(pages)} pictures={pictures}")
        return ExtractedDoc(
            blocks=blocks,
            pages=pages,
            source_meta={"extractor_name": self.name, "extractor_version": self.version},
        )
