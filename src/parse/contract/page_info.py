"""One page's number and dimensions."""

from dataclasses import dataclass


@dataclass
class PageInfo:
    """One page's 1-based number and its dimensions."""

    page_no: int
    width: float
    height: float
