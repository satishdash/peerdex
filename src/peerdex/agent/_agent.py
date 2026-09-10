"""Bounded, inspectable agentic RAG: plan -> retrieve -> answer -> reflect/retry -> emit.

An explicit five-step state machine, not an open-ended agent loop. Each step is
a named method exchanging typed payloads, every retrieval attempt is recorded,
and the retry loop is bounded by ``max_retries``.

The payloads and ports live in ``_model`` and the two pure planning steps in
``_planner``; this module is only the state machine that drives them.
"""

from collections.abc import Mapping
from dataclasses import replace

from llama_index.core.schema import NodeWithScore

from peerdex.agent._model import (
    AgentAnswer,
    Attempt,
    Extraction,
    Plan,
    PlannerPort,
    QuantitativeExtractorPort,
    QuestionKind,
    ReformulatorPort,
    RetrievalLike,
    RetrievedStep,
    RetrieverPort,
    SynthesizerPort,
)
from peerdex.agent._planner import QueryReformulator, QuestionPlanner
from peerdex.quantity import (
    Derivation,
    DerivationEngine,
    Quantity,
    QuantityParser,
    Unit,
    UnitRegistry,
)
from peerdex.scoring import NumericParser
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import Scalars
from peerdex.synthesize import Citation, CitedAnswer

log = get_logger("agent")

_PERIOD_FILTER: str = "year"


class AgentRAGWorkflow:
    """Explicit bounded agent: five named steps, every attempt recorded in the result."""

    def __init__(
        self,
        *,
        retriever: RetrieverPort,
        extractor: QuantitativeExtractorPort,
        synthesizer: SynthesizerPort,
        planner: PlannerPort | None = None,
        reformulator: ReformulatorPort | None = None,
        quantities: QuantityParser | None = None,
        units: UnitRegistry | None = None,
        engine: DerivationEngine | None = None,
        max_retries: int = 2,
    ) -> None:
        self._retriever: RetrieverPort = retriever
        self._extractor: QuantitativeExtractorPort = extractor
        self._synthesizer: SynthesizerPort = synthesizer
        self._planner: PlannerPort = planner or QuestionPlanner()
        self._reformulator: ReformulatorPort = reformulator or QueryReformulator()
        self._quantities: QuantityParser = quantities or QuantityParser()
        self._units: UnitRegistry = units or UnitRegistry()
        self._engine: DerivationEngine = engine or DerivationEngine()
        self._max_retries: int = max_retries
        self._number_parser: NumericParser = NumericParser()

    async def run(
        self, question: str, kind: QuestionKind | None = None, period: str = ""
    ) -> AgentAnswer:
        """Plan the question, then drive it through the bounded answer loop."""
        plan: Plan = self._planner.plan(question, kind, period)
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
        derived: Quantity | None = await self._derived(retrieved)
        if derived is None:
            return await self._extracted(retrieved)
        log.info(f"[agent:derive] value={derived.rendered} unit={derived.unit.symbol}")
        return self._quantitative_answer(retrieved, derived.rendered, derived.unit.symbol)

    async def _derived(self, retrieved: RetrievedStep) -> Quantity | None:
        """The figure the question's own arithmetic asks for, or None when it asks for none.

        Each operand is extracted from the passages already retrieved, so a derivation
        costs extractions and no further retrieval.
        """
        derivation: Derivation | None = retrieved.plan.derivation
        if derivation is None or not retrieved.nodes:
            return None
        parts: list[Quantity | None] = [
            await self._operand(retrieved, operand) for operand in derivation.operands
        ]
        return self._engine.combine(derivation, parts)

    async def _operand(self, retrieved: RetrievedStep, operand: str) -> Quantity | None:
        plan: Plan = replace(retrieved.plan, unit="", derivation=None)
        extraction: Extraction = await self._extractor.extract(operand, plan, retrieved.nodes)
        return self._quantities.parse(extraction.value, extraction.unit)

    async def _extracted(self, retrieved: RetrievedStep) -> AgentAnswer:
        extraction: Extraction | None = await self._extraction(retrieved)
        if extraction is not None:
            log.info(
                f"[agent:extract] value={extraction.value} unit={extraction.unit} "
                f"label={extraction.label!r}"
            )
            return self._extracted_answer(retrieved, extraction)
        retry: RetrievedStep | None = await self._reflect(retrieved)
        return (
            self._quantitative_refusal(retrieved) if retry is None else await self._extracted(retry)
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

    def _extracted_answer(self, retrieved: RetrievedStep, extraction: Extraction) -> AgentAnswer:
        """The extracted figure, in the unit the question asked for where that is possible."""
        value, unit = self._as_asked(retrieved.plan, extraction)
        return self._quantitative_answer(retrieved, value, unit)

    def _as_asked(self, plan: Plan, extraction: Extraction) -> tuple[str, str]:
        """The figure converted to the unit the question states, or exactly as extracted."""
        quantity: Quantity | None = self._quantities.parse(extraction.value, extraction.unit)
        target: Unit | None = self._units.resolve(plan.unit) if plan.unit else None
        if quantity is None or target is None:
            return extraction.value, extraction.unit
        return self._in_unit(quantity, target, extraction)

    @staticmethod
    def _in_unit(quantity: Quantity, target: Unit, extraction: Extraction) -> tuple[str, str]:
        if target.dimension != quantity.unit.dimension:
            return extraction.value, extraction.unit
        converted: Quantity = quantity.to(target)
        return converted.rendered, converted.unit.symbol

    def _quantitative_answer(self, retrieved: RetrievedStep, value: str, unit: str) -> AgentAnswer:
        return AgentAnswer(
            kind=retrieved.plan.kind,
            value=value,
            unit=unit,
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


def _filtered_period(filters: Mapping[str, Scalars] | None) -> str:
    """The single period the corpus is narrowed to, or nothing when it is not a single one.

    The asked-for period is normally a filter rather than words in the question, and
    the extractor needs it to tell this period's column from its neighbours.
    """
    value: Scalars | None = (filters or {}).get(_PERIOD_FILTER)
    if value is None or isinstance(value, list | tuple | set):
        return ""
    return str(value)


async def answer(
    question: str,
    *,
    company: str,
    domain: str,
    filters: Mapping[str, Scalars] | None = None,
    kind: QuestionKind | None = None,
) -> AgentAnswer:
    """One-shot agentic answer over one domain's index, for one company."""
    from peerdex.agent._extractor import LLMQuantitativeExtractor
    from peerdex.retrieve import PassageRetriever
    from peerdex.synthesize import synthesize

    workflow: AgentRAGWorkflow = AgentRAGWorkflow(
        retriever=PassageRetriever(company=company, domain=domain, attributes=filters),
        extractor=LLMQuantitativeExtractor(),
        synthesizer=synthesize,
    )
    return await workflow.run(question, kind=kind, period=_filtered_period(filters))
