"""The port every extractor implements."""

from pathlib import Path
from typing import Protocol

from parse.contract.extracted_doc import ExtractedDoc


class Extractor(Protocol):
    """Port every extractor implements."""

    name: str
    version: str

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Parse a PDF synchronously.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        ...

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """Parse a PDF without blocking the event loop.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        ...
