"""Extractor adapter backed by OpenDataLoader's Java parser and docling hybrid backend."""

import json
import tempfile
from pathlib import Path
from typing import Any, ClassVar, Final

from parse.contract import (
    ExtractedDoc,
)
from parse.odl.document_projection import DocumentProjection
from parse.odl.engine_identity import EngineIdentity
from shared.logging import Logging


class ODLExtractor:
    """Extractor adapter backed by OpenDataLoader's Java parser and docling hybrid backend."""

    _LOG: ClassVar[Any] = Logging.get("parse.odl")

    name: str = EngineIdentity.NAME
    version: str = EngineIdentity.VERSION
    DEFAULT_HYBRID_URL: Final[str] = "http://localhost:5002"

    def __init__(self, hybrid_url: str | None = None) -> None:
        """Point the adapter at a hybrid server, defaulting to localhost.

        Args:
            hybrid_url: Where the hybrid service runs.
        """
        self.hybrid_url: str = hybrid_url or self.DEFAULT_HYBRID_URL

    def extract(self, pdf_path: str | Path) -> ExtractedDoc:
        """Run the ODL converter and project its JSON onto the contract.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        resolved: Path = Path(pdf_path).resolve()
        self._LOG.info(f"extracting {resolved} (hybrid → {self.hybrid_url})")
        return DocumentProjection(self._convert(resolved)).run()

    async def extract_async(self, pdf_path: str | Path) -> ExtractedDoc:
        """The async half of the contract; the ODL converter is synchronous.

        Args:
            pdf_path: The document to parse.

        Returns:
            The parsed document.
        """
        return self.extract(pdf_path)

    def _convert(self, pdf_path: Path) -> dict:
        """Convert to JSON in a temporary directory and read the result back.

        Args:
            pdf_path: The document to parse.

        Returns:
            The converter's JSON output, parsed.
        """
        from opendataloader_pdf import convert

        with tempfile.TemporaryDirectory(prefix="odl_") as tmp:
            convert(
                input_path=str(pdf_path),
                output_dir=tmp,
                format="json",
                quiet=True,
                hybrid="docling-fast",
                hybrid_url=self.hybrid_url,
            )
            return self._read_json(Path(tmp), pdf_path)

    @staticmethod
    def _read_json(tmp: Path, pdf_path: Path) -> dict:
        """The single JSON file ODL writes into the output directory.

        Args:
            tmp: The directory holding the engine's output.
            pdf_path: The document to parse.

        Returns:
            The parsed JSON document.

        Raises:
            RuntimeError: If the converter wrote no JSON file.
        """
        files: list[Path] = list(tmp.glob("*.json"))
        if not files:
            raise RuntimeError(f"ODL produced no JSON output for {pdf_path}")
        return json.loads(files[0].read_text())
