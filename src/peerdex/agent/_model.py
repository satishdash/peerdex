"""What the agent's steps exchange, and the ports they exchange it through.

Payloads and ports, no behaviour: the state machine in ``_agent`` and the planning
strategies in ``_planner`` both depend on these, and neither on the other.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from llama_index.core.schema import NodeWithScore

from peerdex.quantity import Derivation
from peerdex.synthesize import Citation, CitedAnswer

type QuestionKind = Literal["quantitative", "qualitative"]


@dataclass(frozen=True)
class Plan:
    """Named plan for one question: its kind, the qualifiers it carries, and its arithmetic.

    ``derivation`` is present only when the question spells arithmetic out itself, which
    is the only mandate to compute rather than read a printed figure.
    """

    kind: QuestionKind
    period: str
    scope: str
    unit: str
    derivation: Derivation | None = None


@dataclass(frozen=True)
class Attempt:
    """One retrieval attempt: the query used and how many passages came back."""

    query: str
    passages: int


@dataclass(frozen=True)
class Extraction:
    """A quantitative extraction: the bare value, its unit, and where it was printed.

    ``label`` is the evidence that a specific printed row was read. Without it a
    plausible neighbouring figure is indistinguishable from the asked-for one, so
    an extraction that cannot name its label is treated as a refusal.

    ``column`` is the same evidence along the other axis. A correct row label still
    leaves one figure per period to choose from, and `298,498` was once returned
    from a `Baseline 2015` column for a 2025 question. It is empty for a figure
    that sits in no column at all, which is the normal case in prose.
    """

    value: str
    unit: str
    label: str = ""
    column: str = ""


@dataclass(frozen=True)
class AgentAnswer:
    """Everything the agent decided, inspectable per step."""

    kind: QuestionKind
    value: str
    unit: str
    text: str
    citations: list[Citation]
    attempts: list[Attempt]
    refused: bool
    reason: str


@dataclass(frozen=True)
class RetrievedStep:
    """Output of one retrieve step: the passages plus the attempt trail so far."""

    question: str
    plan: Plan
    nodes: list[NodeWithScore]
    attempts: list[Attempt]
    reason: str


class RetrievalLike(Protocol):
    """The slice of a retrieval result the agent reads."""

    @property
    def nodes(self) -> list[NodeWithScore]: ...

    @property
    def reason(self) -> str: ...


class RetrieverPort(Protocol):
    """Port: retrieval over the persisted index."""

    async def retrieve(self, query: str) -> RetrievalLike: ...


class QuantitativeExtractorPort(Protocol):
    """Port: pull the single asked-for figure from passages."""

    async def extract(
        self, question: str, plan: Plan, nodes: Sequence[NodeWithScore]
    ) -> Extraction: ...


class SynthesizerPort(Protocol):
    """Port: cited prose synthesis for qualitative questions."""

    async def __call__(self, query: str, nodes: list[NodeWithScore]) -> CitedAnswer: ...


class ReformulatorPort(Protocol):
    """Port: rewrite a failed query from the retrieved passages."""

    def reformulate(self, question: str, nodes: Sequence[NodeWithScore]) -> str: ...


class PlannerPort(Protocol):
    """Port: resolve a question's kind and qualifiers without an LLM call."""

    def plan(self, question: str, kind: QuestionKind | None = None, period: str = "") -> Plan: ...
