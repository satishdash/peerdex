"""A run of body text."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class ParagraphBlock:
    """A run of body text under its heading path."""

    kind: Literal["paragraph"]
    text: str
    page_no: int
    heading_path: list[str]
