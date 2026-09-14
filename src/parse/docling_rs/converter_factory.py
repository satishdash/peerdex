"""The docling.rs converter, built once with pdfium located first."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from shared.logging import Logging
from shared.settings import get_settings


class ConverterFactory:
    """Builds the docling.rs converter once, with pdfium located first."""

    _LOG: ClassVar[Any] = Logging.get(__name__)

    PDFIUM_ENV: ClassVar[str] = "PDFIUM_DYNAMIC_LIB_PATH"

    @staticmethod
    @lru_cache(maxsize=1)
    def instance() -> Any:
        """The process-wide docling.rs DocumentConverter.

        Returns:
            The process-wide docling.rs converter.
        """
        ConverterFactory._bake_pdfium()
        from docling_rs import DocumentConverter

        settings: Any = get_settings()
        ConverterFactory._LOG.info(
            f"{ConverterFactory.PDFIUM_ENV}={ConverterFactory._pdfium_path()}"
        )
        return DocumentConverter(
            do_ocr=settings.docling.do_ocr,
            do_table_structure=settings.docling.do_table_structure,
            heading_hierarchy=settings.docling_rs.heading_hierarchy,
            no_text_panels=settings.docling_rs.no_text_panels,
            artifacts_path=ConverterFactory._artifacts(settings.docling_rs.artifacts_path),
        )

    @classmethod
    def _bake_pdfium(cls) -> None:
        """Publish the configured pdfium path, unless the environment already names one."""
        configured: str = get_settings().docling.pdfium_lib_path
        if configured and not os.environ.get(cls.PDFIUM_ENV):
            os.environ[cls.PDFIUM_ENV] = str(Path(configured).expanduser().resolve())

    @classmethod
    def _pdfium_path(cls) -> str:
        """Where pdfium will be loaded from.

        Returns:
            The pdfium library path, or ``<unset>``.
        """
        return os.environ.get(cls.PDFIUM_ENV, "<unset>")

    @staticmethod
    def _artifacts(configured: str) -> str | None:
        """Override the model cache directory only when one is named.

        Args:
            configured: The configured directory, empty to leave it alone.

        Returns:
            The resolved model directory, or None to use upstream's default.
        """
        if not configured:
            return None
        return str(Path(configured).expanduser().resolve())
