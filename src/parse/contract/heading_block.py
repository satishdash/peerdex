"""A section title."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class HeadingBlock:
    """A section title; level 0 is the document title, 1 and above are section depths."""

    kind: Literal["heading"]
    level: int
    text: str
    page_no: int
    heading_path: list[str]
