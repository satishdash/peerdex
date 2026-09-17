"""Adapter over docling.rs, projected by docling's own walker."""

from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from parse.contract import ExtractedDoc
from parse.docling import DoclingExtractor
from parse.docling_rs.converter_factory import ConverterFactory
from shared.logging import Logging
from shared.package_version import PackageVersion


class DoclingRsExtractor:
    """Adapter over docling.rs, projected by docling's own walker."""

    _LOG: ClassVar[Any] = Logging.get(__name__)

    name: str = "docling-rs"
    version: str = PackageVersion.of("docling-rs")

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Convert one PDF, then restamp provenance onto the shared projection.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document, stamped with this engine's provenance.
        """
        self._LOG.info(f"extracting {pdf_path}")
        document: Any = ConverterFactory.instance().convert(str(pdf_path)).document
        projected: ExtractedDoc = DoclingExtractor.from_document(document)
        return replace(projected, source_meta=self._source_meta(projected))

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """The async half of the contract; the docling.rs converter is synchronous.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        return self.extract(pdf_path)

    def _source_meta(self, projected: ExtractedDoc) -> dict[str, Any]:
        """The projection's metadata, restamped with this engine's identity.

        Args:
            projected: The document as docling's walker produced it.

        Returns:
            The projection's metadata with this engine's name and version.
        """
        meta: dict[str, Any] = dict(projected.source_meta)
        meta["extractor_name"] = self.name
        meta["extractor_version"] = self.version
        return meta
