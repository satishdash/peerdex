"""DoclingRsExtractor: a PDF becomes an ExtractedDoc via docling.rs, the Rust port.

The engine returns a real DoclingDocument, so docling's projection is reused and only
provenance is restamped. Conversion needs a pdfium shared library, named by
``docling.pdfium_lib_path``.
"""

from parse.docling_rs.converter_factory import ConverterFactory
from parse.docling_rs.docling_rs_extractor import DoclingRsExtractor

__all__ = ["ConverterFactory", "DoclingRsExtractor"]
