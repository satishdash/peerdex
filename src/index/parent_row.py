"""One parent as the escalation reads it back."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParentRow:
    """A parent fetched by id: the section text a refused passage came from."""

    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
