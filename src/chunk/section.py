"""One heading and the blocks beneath it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Section:
    """One heading and the blocks beneath it, the unit a parent node is built from."""

    heading_path: list[str]
    page_no: int
    blocks: list
