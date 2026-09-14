"""A table as row-major cell strings."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class TableBlock:
    """A table as row-major cell strings, with its column headers and caption."""

    kind: Literal["table"]
    headers: list[str]
    rows: list[list[str]]
    caption: str
    page_no: int
    heading_path: list[str]
