"""The two terminal boxes: an answer, or a refusal carrying its reason."""

from dataclasses import dataclass, field

from ask.answer_kind import AnswerKind
from ask.citation import Citation


@dataclass(frozen=True, slots=True)
class Answer:
    """What the ask flow ends with.

    A quantitative answer is the value alone, never a hedge and never prose wrapped
    around a number; a qualitative one is prose. A refusal carries its reason.

    Citations ride alongside rather than inside, so the value stays bare while the
    answer still traces back to the chunks it was read from.
    """

    kind: AnswerKind
    value: str = ""
    unit: str = ""
    text: str = ""
    refused: bool = False
    reason: str = ""
    attempts: int = 1
    citations: tuple[Citation, ...] = field(default_factory=tuple)
