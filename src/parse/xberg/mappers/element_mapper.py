"""One element kind's projection into zero or more blocks."""

import re
from abc import ABC, abstractmethod
from typing import ClassVar

from parse.xberg.projection_state import ProjectionState


class ElementMapper(ABC):
    """One element kind's projection into zero or more blocks."""

    _BULLET: ClassVar[re.Pattern[str]] = re.compile(r"^[•‣◦\-\*·]\s*")

    @abstractmethod
    def map(self, text: str, state: ProjectionState) -> None:
        """Append this element's projection to the state.

        Args:
            text: The text being handled.
            state: The accumulator this projection is building into.
        """
