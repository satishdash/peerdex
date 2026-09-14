"""One question, as the caller asks it."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from ask.answer_kind import AnswerKind
from shared.metadata import Scalars


@dataclass(frozen=True, slots=True)
class Question:
    """A question with the shape its answer must take and the slice it may look in."""

    text: str
    kind: AnswerKind
    company: str
    domain: str
    filters: Mapping[str, Scalars] = field(default_factory=dict)
