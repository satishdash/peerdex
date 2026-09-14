"""The shape the caller asked the answer to take."""

from enum import StrEnum


class AnswerKind(StrEnum):
    """The shape of the answer, declared by the caller rather than inferred.

    It selects the answer's shape, not the question's meaning: the same question asked
    as quantitative returns a bare value, as qualitative returns prose. Only the former
    is scoreable.
    """

    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
