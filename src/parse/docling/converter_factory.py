"""Builds the Docling converter once, with the on-disk model cache primed."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from shared.logging import Logging
from shared.settings import get_settings


class ConverterFactory:
    """Builds the Docling converter once, with the on-disk model cache primed."""

    _LOG: ClassVar[Any] = Logging.get("parse.docling")

    @staticmethod
    @lru_cache(maxsize=1)
    def instance() -> Any:
        """The process-wide DocumentConverter.

        Returns:
            The process-wide DocumentConverter.
        """
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, PdfFormatOption

        artifacts: str = ConverterFactory._artifacts_path()
        has_models: bool = any(Path(artifacts).iterdir())
        ConverterFactory._LOG.info(f"DOCLING_ARTIFACTS_PATH={artifacts} (cached={has_models})")
        if not has_models:
            ConverterFactory._LOG.warning(
                f"no models in {artifacts}; Docling will auto-download on first parse"
            )
        options: Any = ConverterFactory._pipeline_options(artifacts, has_models)
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )

    @staticmethod
    def _artifacts_path() -> str:
        """Resolve the model directory and publish it to Docling through the environment.

        Returns:
            The resolved model directory.
        """
        path: str = str(Path(get_settings().docling.artifacts_path).resolve())
        Path(path).mkdir(parents=True, exist_ok=True)
        os.environ["DOCLING_ARTIFACTS_PATH"] = path
        return path

    @staticmethod
    def _pipeline_options(artifacts: str, has_models: bool) -> Any:
        """Pipeline knobs, taken from settings.

        Args:
            artifacts: The resolved model directory.
            has_models: Whether that directory already holds the models.

        Returns:
            Pipeline options built from settings.
        """
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        docling_settings: Any = get_settings().docling
        options: Any = PdfPipelineOptions()
        options.do_ocr = docling_settings.do_ocr
        options.do_table_structure = docling_settings.do_table_structure
        options.generate_page_images = docling_settings.generate_page_images
        options.generate_picture_images = docling_settings.generate_picture_images
        options.images_scale = docling_settings.picture_image_scale
        if has_models:
            options.artifacts_path = artifacts
        return options
