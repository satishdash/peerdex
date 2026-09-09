"""Bounded, inspectable agentic RAG: plan -> retrieve -> answer -> reflect/retry -> emit.

An explicit five-step state machine, not an open-ended agent loop. Each step is
a named method exchanging typed payloads, every retrieval attempt is recorded,
and the retry loop is bounded by ``max_retries``.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from llama_index.core.schema import NodeWithScore

from peerdex.scoring import NumericParser
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import Scalars
from peerdex.synthesize import Citation, CitedAnswer

log = get_logger("agent")

type QuestionKind = Literal["quantitative", "qualitative"]

_PERIOD: re.Pattern[str] = re.compile(r"\b(?:19|20)\d{2}\b")
_SCOPE: re.Pattern[str] = re.compile(r"\b(market-based|location-based)\b", re.IGNORECASE)
_TRAILING_UNIT: re.Pattern[str] = re.compile(r"\(([^()\s][^()]{0,14})\)\s*$")


@dataclass(frozen=True)
class Plan:
    """Named plan for one question: its kind and the qualifiers it carries."""

    kind: QuestionKind
    period: str
    scope: str
    unit: str


@dataclass(frozen=True)
class Attempt:
    """One retrieval attempt: the query used and how many passages came back."""

    query: str
    passages: int


@dataclass(frozen=True)
class Extraction:
    """A quantitative extraction: the bare value, its unit, and the row label it came from.

    ``label`` is the evidence that a specific printed row was read. Without it a
    plausible neighbouring figure is indistinguishable from the asked-for one, so
    an extraction that cannot name its label is treated as a refusal.
    """

    value: str
    unit: str
    label: str = ""


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
    """Port: hybrid retrieval over the persisted index."""

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


class QuestionPlanner:
    """Plan step: resolve the kind (caller wins) and extract qualifiers, no LLM call."""

    _QUALITATIVE_MARKERS: tuple[str, ...] = (
        "describe",
        "explain",
        "why ",
        "how does",
        "how is",
        "policy",
        "approach",
        "strategy",
        "governance",
        "process",
    )

    def plan(self, question: str, kind: QuestionKind | None = None) -> Plan:
        """Resolve kind and qualifiers; a caller-supplied kind skips classification."""
        resolved: QuestionKind = kind if kind is not None else self._classify(question)
        return Plan(
            kind=resolved,
            period=self._first(_PERIOD, question),
            scope=self._first(_SCOPE, question).lower(),
            unit=self._trailing_unit(question),
        )

    def _classify(self, question: str) -> QuestionKind:
        lowered: str = question.lower()
        qualitative: bool = any(marker in lowered for marker in self._QUALITATIVE_MARKERS)
        return "qualitative" if qualitative else "quantitative"

    @staticmethod
    def _first(pattern: re.Pattern[str], question: str) -> str:
        match: re.Match[str] | None = pattern.search(question)
        return match[0] if match else ""

    @staticmethod
    def _trailing_unit(question: str) -> str:
        match: re.Match[str] | None = _TRAILING_UNIT.search(question.strip())
        return match[1] if match else ""


class QueryReformulator:
    """Reflect step: rewrite a failed query with headings and table row labels seen so far."""

    def __init__(self, max_terms: int = 8) -> None:
        self._max_terms: int = max_terms

    def reformulate(self, question: str, nodes: Sequence[NodeWithScore]) -> str:
        """The question enriched with passage vocabulary; unchanged when there is none."""
        vocabulary: list[str] = self._vocabulary(nodes)[: self._max_terms]
        return question if not vocabulary else f"{question} {' '.join(vocabulary)}"

    def _vocabulary(self, nodes: Sequence[NodeWithScore]) -> list[str]:
        terms: dict[str, None] = {}
        for node in nodes:
            for term in [*self._headings(node), *self._row_labels(node)]:
                terms.setdefault(term, None)
        return list(terms)

    @staticmethod
    def _headings(node: NodeWithScore) -> list[str]:
        heading_path: str = str(node.node.metadata.get("heading_path") or "")
        return [part.strip() for part in heading_path.split(" > ") if part.strip()]

    @staticmethod
    def _row_labels(node: NodeWithScore) -> list[str]:
        lines: list[str] = node.node.get_content().splitlines()
        raw: list[str] = [line.split("|")[1].strip() for line in lines if line.startswith("|")]
        return [label for label in raw if label.strip("- ")]


class AgentRAGWorkflow:
    """Explicit bounded agent: five named steps, every attempt recorded in the result."""

    def __init__(
        self,
        *,
        retriever: RetrieverPort,
        extractor: QuantitativeExtractorPort,
        synthesizer: SynthesizerPort,
        planner: QuestionPlanner | None = None,
        reformulator: ReformulatorPort | None = None,
        max_retries: int = 2,
    ) -> None:
        self._retriever: RetrieverPort = retriever
        self._extractor: QuantitativeExtractorPort = extractor
        self._synthesizer: SynthesizerPort = synthesizer
        self._planner: QuestionPlanner = planner or QuestionPlanner()
        self._reformulator: ReformulatorPort = reformulator or QueryReformulator()
        self._max_retries: int = max_retries
        self._number_parser: NumericParser = NumericParser()

    async def run(self, question: str, kind: QuestionKind | None = None) -> AgentAnswer:
        """Plan the question, then drive it through the bounded answer loop."""
        plan: Plan = self._planner.plan(question, kind)
        log.info(f"[agent:plan] kind={plan.kind} question={question[:80]}")
        retrieved: RetrievedStep = await self._retrieve(question, question, plan, [])
        if plan.kind == "qualitative":
            return await self._synthesize(retrieved)
        return await self._answer_quantitative(retrieved)

    async def _retrieve(
        self, question: str, query: str, plan: Plan, attempts: list[Attempt]
    ) -> RetrievedStep:
        result: RetrievalLike = await self._retriever.retrieve(query)
        log.info(f"[agent:retrieve] query={query[:80]} passages={len(result.nodes)}")
        return RetrievedStep(
            question=question,
            plan=plan,
            nodes=result.nodes,
            attempts=[*attempts, Attempt(query=query, passages=len(result.nodes))],
            reason=result.reason,
        )

    async def _answer_quantitative(self, retrieved: RetrievedStep) -> AgentAnswer:
        extraction: Extraction | None = await self._extraction(retrieved)
        if extraction is not None:
            log.info(
                f"[agent:extract] value={extraction.value} unit={extraction.unit} "
                f"label={extraction.label!r}"
            )
            return self._quantitative_answer(retrieved, extraction)
        retry: RetrievedStep | None = await self._reflect(retrieved)
        return (
            self._quantitative_refusal(retrieved)
            if retry is None
            else await self._answer_quantitative(retry)
        )

    async def _reflect(self, retrieved: RetrievedStep) -> RetrievedStep | None:
        query: str | None = self._next_query(retrieved)
        if query is None:
            return None
        log.info(f"[agent:reflect] retry query={query[:80]}")
        return await self._retrieve(retrieved.question, query, retrieved.plan, retrieved.attempts)

    async def _synthesize(self, retrieved: RetrievedStep) -> AgentAnswer:
        if not retrieved.nodes:
            return self._qualitative_refusal(retrieved)
        cited: CitedAnswer = await self._synthesizer(retrieved.question, retrieved.nodes)
        log.info(f"[agent:synthesize] refused={cited.refused} citations={len(cited.citations)}")
        return self._qualitative_answer(retrieved, cited)

    async def _extraction(self, retrieved: RetrievedStep) -> Extraction | None:
        if not retrieved.nodes:
            return None
        extraction: Extraction = await self._extractor.extract(
            retrieved.question, retrieved.plan, retrieved.nodes
        )
        return extraction if self._is_bare_value(extraction.value) else None

    def _is_bare_value(self, value: str) -> bool:
        has_number: bool = self._number_parser.parse(value) is not None
        return has_number and not any(char.isalpha() for char in value)

    def _next_query(self, retrieved: RetrievedStep) -> str | None:
        if len(retrieved.attempts) > self._max_retries:
            return None
        candidate: str = self._reformulator.reformulate(retrieved.question, retrieved.nodes)
        tried: set[str] = {attempt.query for attempt in retrieved.attempts}
        return None if candidate in tried else candidate

    def _quantitative_answer(self, retrieved: RetrievedStep, extraction: Extraction) -> AgentAnswer:
        return AgentAnswer(
            kind=retrieved.plan.kind,
            value=extraction.value,
            unit=extraction.unit,
            text="",
            citations=self._citations(retrieved.nodes),
            attempts=retrieved.attempts,
            refused=False,
            reason="",
        )

    def _quantitative_refusal(self, retrieved: RetrievedStep) -> AgentAnswer:
        exhausted: bool = len(retrieved.attempts) > self._max_retries
        return AgentAnswer(
            kind=retrieved.plan.kind,
            value="",
            unit="",
            text="",
            citations=[],
            attempts=retrieved.attempts,
            refused=True,
            reason="retry_budget_exhausted" if exhausted else "no_new_query",
        )

    @staticmethod
    def _qualitative_refusal(retrieved: RetrievedStep) -> AgentAnswer:
        return AgentAnswer(
            kind=retrieved.plan.kind,
            value="",
            unit="",
            text="",
            citations=[],
            attempts=retrieved.attempts,
            refused=True,
            reason=retrieved.reason or "no_passages",
        )

    @staticmethod
    def _qualitative_answer(retrieved: RetrievedStep, cited: CitedAnswer) -> AgentAnswer:
        return AgentAnswer(
            kind=retrieved.plan.kind,
            value="",
            unit="",
            text="" if cited.refused else cited.answer,
            citations=list(cited.citations),
            attempts=retrieved.attempts,
            refused=cited.refused,
            reason=cited.reason,
        )

    @staticmethod
    def _citations(nodes: list[NodeWithScore]) -> list[Citation]:
        return [
            Citation(
                n=index,
                node_id=node.node.node_id,
                company=str(node.node.metadata.get("company", "")),
                year=int(node.node.metadata.get("year", 0) or 0),
                page=int(node.node.metadata.get("page_no", 0) or 0),
                heading=str(node.node.metadata.get("heading_path", "") or ""),
                quote=node.node.get_content()[:100],
            )
            for index, node in enumerate(nodes, 1)
        ]


async def answer(
    question: str,
    *,
    company: str,
    filters: Mapping[str, Scalars] | None = None,
    kind: QuestionKind | None = None,
) -> AgentAnswer:
    """One-shot agentic answer over the persisted index for one company."""
    from peerdex.agent._extractor import LLMQuantitativeExtractor
    from peerdex.retrieve import LexicalRetriever
    from peerdex.synthesize import synthesize

    workflow: AgentRAGWorkflow = AgentRAGWorkflow(
        retriever=LexicalRetriever(company=company, attributes=filters),
        extractor=LLMQuantitativeExtractor(),
        synthesizer=synthesize,
    )
    return await workflow.run(question, kind=kind)
