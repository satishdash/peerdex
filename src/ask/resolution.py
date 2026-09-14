"""What Resolve settled: a value, or a refusal carrying its reason."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome of the gates.

    A quantitative answer is the value alone, never a hedge and never prose wrapped
    around a number. A refusal carries its reason.
    """

    value: str = ""
    unit: str = ""
    refused: bool = False
    reason: str = ""
