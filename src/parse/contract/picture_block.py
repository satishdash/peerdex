"""A rendered figure, awaiting description by the vision model."""

from dataclasses import dataclass
from typing import Literal

from PIL.Image import Image


@dataclass
class PictureBlock:
    """A rendered figure for the VLM stage; bbox_area_pct drives filtering only."""

    kind: Literal["picture"]
    pil_image: Image
    bbox_area_pct: float
    page_no: int
    heading_path: list[str]
    self_ref: str = ""
