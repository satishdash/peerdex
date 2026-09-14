"""One passage as Find returns it."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Passage:
    """A child chunk that came back from the search, with the parent it belongs to.

    ``score`` is normalised so higher always means better, whichever mode ranked it.
    ``parent_id`` is what the escalation fetches when the read finds no value.
    """

    id: str
    text: str
    score: float
    parent_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
