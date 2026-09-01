"""Unit tests for the bounded agentic RAG workflow, all seams stubbed. No network."""

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from peerdex.agent import (
    AgentAnswer,
    AgentRAGWorkflow,
    Attempt,
    Extraction,
    Plan,
    QueryReformulator,
    QuestionPlanner,
)
from peerdex.synthesize import Citation, CitedAnswer


@dataclass
class StubRetrieval:
    nodes: list[NodeWithScore]
    reason: str = ""


class StubRetriever:
    def __init__(self, results: list[StubRetrieval]) -> None:
        self._results: list[StubRetrieval] = list(results)
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> StubRetrieval:
        self.queries.append(query)
        index: int = min(len(self.queries) - 1, len(self._results) - 1)
        return self._results[index]


class StubExtractor:
    def __init__(self, extractions: list[Extraction]) -> None:
        self._extractions: list[Extraction] = list(extractions)
        self.calls: int = 0

    async def extract(
        self, question: str, plan: Plan, nodes: Sequence[NodeWithScore]
    ) -> Extraction:
        index: int = min(self.calls, len(self._extractions) - 1)
        self.calls += 1
        return self._extractions[index]


@dataclass
class StubReformulator:
    queries: list[str] = field(default_factory=list)

    def reformulate(self, question: str, nodes: Sequence[NodeWithScore]) -> str:
        return self.queries.pop(0) if self.queries else question


class StubSynthesizer:
    def __init__(self, cited: CitedAnswer) -> None:
        self._cited: CitedAnswer = cited
        self.calls: int = 0

    async def __call__(self, query: str, nodes: list[NodeWithScore]) -> CitedAnswer:
        self.calls += 1
        return self._cited


def make_node(
    text: str = "| Total employees | 62,587 |", heading: str = "Workforce"
) -> NodeWithScore:
    metadata: dict[str, object] = {
        "company": "acme",
        "year": 2025,
        "page_no": 3,
        "heading_path": heading,
    }
    return NodeWithScore(node=TextNode(text=text, metadata=metadata), score=1.0)


def make_workflow(
    retriever: StubRetriever,
    extractor: StubExtractor,
    synthesizer: StubSynthesizer | None = None,
    reformulator: StubReformulator | None = None,
    max_retries: int = 2,
) -> AgentRAGWorkflow:
    synth: StubSynthesizer = synthesizer or StubSynthesizer(
        CitedAnswer(answer="", citations=[], refused=True)
    )
    return AgentRAGWorkflow(
        retriever=retriever,
        extractor=extractor,
        synthesizer=synth,
        reformulator=reformulator,
        max_retries=max_retries,
    )


async def test_given_figure_in_passages_when_asked_then_value_alone_with_unit() -> None:
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor([Extraction(value="62,587", unit="tCO2e")])
    result: AgentAnswer = await make_workflow(retriever, extractor).run(
        question="Total employees", kind="quantitative"
    )
    assert result.kind == "quantitative"
    assert result.value == "62,587"
    assert result.unit == "tCO2e"
    assert "tCO2e" not in result.value
    assert result.text == ""
    assert result.refused is False
    assert result.reason == ""
    assert result.attempts == [Attempt(query="Total employees", passages=1)]
    assert len(result.citations) == 1
    assert result.citations[0].page == 3
    assert result.citations[0].heading == "Workforce"
    assert result.citations[0].company == "acme"


async def test_given_absent_figure_when_asked_then_empty_value_and_refusal() -> None:
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor([Extraction(value="", unit="")])
    result: AgentAnswer = await make_workflow(
        retriever, extractor, reformulator=StubReformulator()
    ).run(question="q", kind="quantitative")
    assert result.value == ""
    assert result.unit == ""
    assert result.text == ""
    assert result.refused is True
    assert result.reason == "no_new_query"
    assert result.attempts == [Attempt(query="q", passages=1)]


async def test_given_prose_extraction_when_asked_then_treated_as_absent() -> None:
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor(
        [Extraction(value="the passages do not state it", unit="")]
    )
    result: AgentAnswer = await make_workflow(
        retriever, extractor, reformulator=StubReformulator()
    ).run(question="q", kind="quantitative")
    assert result.value == ""
    assert result.refused is True


async def test_given_first_attempt_empty_when_retry_fires_then_second_succeeds() -> None:
    retriever: StubRetriever = StubRetriever(
        [
            StubRetrieval(nodes=[make_node()]),
            StubRetrieval(nodes=[make_node("| Energy | 42 |", "Energy")]),
        ]
    )
    extractor: StubExtractor = StubExtractor(
        [Extraction(value="", unit=""), Extraction(value="42", unit="GWh")]
    )
    reformulator: StubReformulator = StubReformulator(queries=["q Energy"])
    result: AgentAnswer = await make_workflow(retriever, extractor, reformulator=reformulator).run(
        question="q", kind="quantitative"
    )
    assert result.value == "42"
    assert result.unit == "GWh"
    assert result.refused is False
    assert [attempt.query for attempt in result.attempts] == ["q", "q Energy"]
    assert retriever.queries == ["q", "q Energy"]
    assert extractor.calls == 2


async def test_given_budget_exhausted_when_all_attempts_fail_then_refusal() -> None:
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor([Extraction(value="", unit="")])
    reformulator: StubReformulator = StubReformulator(queries=["q1", "q2", "q3", "q4"])
    result: AgentAnswer = await make_workflow(
        retriever, extractor, reformulator=reformulator, max_retries=2
    ).run(question="q", kind="quantitative")
    assert result.refused is True
    assert result.value == ""
    assert result.reason == "retry_budget_exhausted"
    assert [attempt.query for attempt in result.attempts] == ["q", "q1", "q2"]
    assert extractor.calls == 3


async def test_given_no_passages_when_asked_then_extractor_never_called() -> None:
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[])])
    extractor: StubExtractor = StubExtractor([Extraction(value="62,587", unit="t")])
    result: AgentAnswer = await make_workflow(retriever, extractor).run(
        question="q", kind="quantitative"
    )
    assert result.refused is True
    assert result.value == ""
    assert extractor.calls == 0
    assert result.attempts == [Attempt(query="q", passages=0)]


async def test_given_qualitative_question_when_asked_then_prose_with_citations() -> None:
    citation: Citation = Citation(
        n=1, node_id="n1", company="acme", year=2025, page=3, heading="H", quote="quoted"
    )
    cited: CitedAnswer = CitedAnswer(
        answer="The approach is risk-based [#1].", citations=[citation], refused=False
    )
    synthesizer: StubSynthesizer = StubSynthesizer(cited)
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor([Extraction(value="", unit="")])
    result: AgentAnswer = await make_workflow(retriever, extractor, synthesizer=synthesizer).run(
        question="Describe the approach", kind=None
    )
    assert result.kind == "qualitative"
    assert result.text == "The approach is risk-based [#1]."
    assert result.value == ""
    assert result.unit == ""
    assert result.refused is False
    assert result.citations == [citation]
    assert synthesizer.calls == 1
    assert extractor.calls == 0


async def test_given_caller_kind_when_supplied_then_classification_skipped() -> None:
    synthesizer: StubSynthesizer = StubSynthesizer(
        CitedAnswer(answer="prose", citations=[], refused=False)
    )
    retriever: StubRetriever = StubRetriever([StubRetrieval(nodes=[make_node()])])
    extractor: StubExtractor = StubExtractor([Extraction(value="5", unit="")])
    result: AgentAnswer = await make_workflow(retriever, extractor, synthesizer=synthesizer).run(
        question="Describe the approach", kind="quantitative"
    )
    assert result.kind == "quantitative"
    assert result.value == "5"
    assert synthesizer.calls == 0
    assert extractor.calls == 1


async def test_given_qualitative_with_no_passages_when_asked_then_refusal_with_reason() -> None:
    synthesizer: StubSynthesizer = StubSynthesizer(
        CitedAnswer(answer="prose", citations=[], refused=False)
    )
    retriever: StubRetriever = StubRetriever(
        [StubRetrieval(nodes=[], reason="no_candidates_from_fusion")]
    )
    extractor: StubExtractor = StubExtractor([Extraction(value="", unit="")])
    result: AgentAnswer = await make_workflow(retriever, extractor, synthesizer=synthesizer).run(
        question="Describe x", kind="qualitative"
    )
    assert result.refused is True
    assert result.reason == "no_candidates_from_fusion"
    assert result.text == ""
    assert synthesizer.calls == 0


@pytest.mark.parametrize(
    ("question", "expected_kind"),
    [
        ("Total energy consumption (GWh)", "quantitative"),
        ("Scope 2 emissions market-based 2024", "quantitative"),
        ("Describe the company's climate governance approach", "qualitative"),
        ("Explain how emissions are calculated", "qualitative"),
    ],
)
def test_given_question_when_planned_then_kind_classified(
    question: str, expected_kind: str
) -> None:
    assert QuestionPlanner().plan(question, None).kind == expected_kind


def test_given_caller_kind_when_planned_then_it_wins() -> None:
    plan: Plan = QuestionPlanner().plan("Describe the approach", "quantitative")
    assert plan.kind == "quantitative"


def test_given_qualifiers_when_planned_then_extracted() -> None:
    plan: Plan = QuestionPlanner().plan("Scope 2 emissions market-based 2024 (tCO2e)", None)
    assert plan.period == "2024"
    assert plan.scope == "market-based"
    assert plan.unit == "tCO2e"


def test_given_headings_and_row_labels_when_reformulated_then_vocabulary_appended() -> None:
    nodes: list[NodeWithScore] = [
        make_node(
            text="| Total employees | 62,587 |\n| --- | --- |\n| Contractors | 1,000 |",
            heading="Workforce > Headcount",
        )
    ]
    query: str = QueryReformulator().reformulate("How many people", nodes)
    assert query == "How many people Workforce Headcount Total employees Contractors"


def test_given_no_nodes_when_reformulated_then_question_unchanged() -> None:
    assert QueryReformulator().reformulate("q", []) == "q"
