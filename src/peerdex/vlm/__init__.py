"""VLM picture describer.

Docling layout gives us bounding boxes + a rendered PIL image per
picture. We pre-filter pictures (bbox area, header/footer band) inside
the extractor, then send each surviving picture to OpenAI Vision in a
single JSON-mode call. Per-image results cache to disk; failures go to
a per-doc DLQ. The chunker stitches the resulting picture descriptions
into the node stream.
"""
from peerdex.vlm._describer import OpenAIPictureDescriber, PictureRef

__all__ = ["OpenAIPictureDescriber", "PictureRef"]
