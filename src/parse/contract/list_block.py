"""A flat list of items."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class ListBlock:
    """A flat list of items, nesting collapsed."""

    kind: Literal["list"]
    items: list[str]
    ordered: bool
    page_no: int
    heading_path: list[str]
