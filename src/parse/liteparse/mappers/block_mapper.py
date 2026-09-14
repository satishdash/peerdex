"""Strategy mapping one layout block kind onto contract blocks."""

import re
from abc import ABC, abstractmethod
from typing import ClassVar

from parse.liteparse.projection_state import ProjectionState
from parse.liteparse.protocols.layout_block_like import LayoutBlockLike


class BlockMapper(ABC):
    """Strategy mapping one layout block kind onto contract blocks."""

    _CONTROL_CHARS: ClassVar[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

    @abstractmethod
    def map(self, block: LayoutBlockLike, state: ProjectionState) -> None:
        """Append the contract projection of ``block`` to the state, or drop it.

        Args:
            block: The layout block being mapped.
            state: The accumulator this projection is building into.
        """

    @classmethod
    def clean(cls, text: str | None) -> str:
        """Strip control characters (keeping tab/newline) and trim.

        Args:
            text: The text being handled.

        Returns:
            The text with control characters stripped and trimmed.
        """
        return cls._CONTROL_CHARS.sub("", text or "").strip()
