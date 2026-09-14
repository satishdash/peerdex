"""What the route settled before any search is paid for."""

from dataclasses import dataclass

from ask.answer_kind import AnswerKind


@dataclass(frozen=True, slots=True)
class Routing:
    """The answer's shape, and the period a column will be judged against.

    ``period`` is None when the caller asked for no single year, in which case no
    column can be refused for stating another period.
    """

    kind: AnswerKind
    period: int | None
