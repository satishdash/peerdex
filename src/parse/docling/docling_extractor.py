"""Extractor adapter backed by Docling's DocumentConverter."""

from pathlib import Path
from typing import Any, ClassVar

from parse.contract import (
    ExtractedDoc,
)
from parse.docling.converter_factory import ConverterFactory
from parse.docling.document_projection import DocumentProjection
from parse.docling.engine_identity import EngineIdentity
from shared.logging import Logging


class DoclingExtractor:
    """Extractor adapter backed by Docling's DocumentConverter."""

    _LOG: ClassVar[Any] = Logging.get("parse.docling")

    name: str = EngineIdentity.NAME
    version: str = EngineIdentity.VERSION

    @classmethod
    def from_document(cls, doc: Any) -> ExtractedDoc:
        """Re-project a cached DoclingDocument without re-running the converter.

        Args:
            doc: The already converted document.

        Returns:
            The projected document.
        """
        return DocumentProjection(doc).run()

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Convert a PDF and project it onto the contract.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        self._LOG.info(f"extracting {pdf_path}")
        document: Any = ConverterFactory.instance().convert(str(pdf_path)).document
        return self.from_document(document)

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """The async half of the contract; Docling's converter is synchronous.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        return self.extract(pdf_path)
