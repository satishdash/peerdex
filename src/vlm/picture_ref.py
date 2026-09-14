"""One figure handed to the vision model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PictureRef:
    """A figure cut out of a page, with where it came from.

    ``page_no`` is 1-based, ``heading_path`` runs root to leaf, and ``bbox_area_pct``
    is kept for logging only.
    """

    page_no: int
    heading_path: list[str]
    pil_image: Any
    bbox_area_pct: float
    self_ref: str = ""
    extra: dict = field(default_factory=dict)
