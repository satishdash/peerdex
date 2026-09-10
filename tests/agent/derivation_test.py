"""The agent computes a figure only where the question spelled the arithmetic out."""

from collections.abc import Mapping, Sequence

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from peerdex.agent import AgentAnswer, AgentRAGWorkflow, Extraction, Plan
from peerdex.synthesize import CitedAnswer

TOTAL_GHG: str = "Total GHG emissions (Scope 1 + Scope 2 + Scope 3)"
PLAIN: str = "Total weight of hazardous waste generated"
SCOPES: dict[str, Extraction] = {
    "Scope 1": Extraction(value="62,587", unit="Tonnes CO₂e", label="Scope 1"),
    "Scope 2": Extraction(value="108,000", unit="Tonnes CO₂e", label="Scope 2"),
    "Scope 3": Extraction(value="6,100,000", unit="Tonnes CO₂e", label="Scope 3"),
}
PRINTED_TOTAL: dict[str, Extraction] = {
    TOTAL_GHG: Extraction(value="6,197,690", unit="Tonnes CO₂e", label="Total GHG emissions")
}


class StubRetrieval:
    """One retrieval result: the passages, and no reason to refuse."""

    def __init__(self, nodes: list[NodeWithScore]) -> None:
        self.nodes: list[NodeWithScore] = nodes
        self.reason: str = ""


class StubRetriever:
    """Returns the same passages for every query, so extraction is what is measured."""

    def __init__(self, nodes: list[NodeWithScore]) -> None:
        self._nodes: list[NodeWithScore] = nodes

    async def retrieve(self, query: str) -> StubRetrieval:
        return StubRetrieval(self._nodes)


class KeyedExtractor:
    """Answers each question it is asked, recording them so the fan-out is visible."""

    def __init__(self, answers: Mapping[str, Extraction]) -> None:
        self._answers: dict[str, Extraction] = dict(answers)
        self.questions: list[str] = []

    async def extract(
        self, question: str, plan: Plan, nodes: Sequence[NodeWithScore]
    ) -> Extraction:
        self.questions.append(question)
        return self._answers.get(question, Extraction(value="", unit="", label=""))


async def _refuse(query: str, nodes: list[NodeWithScore]) -> CitedAnswer:
    return CitedAnswer(answer="", citations=[], refused=True, reason="not_asked")


def _node() -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(text="| Scope 1 | 62,587 |", metadata={"company": "acme", "year": 2025}),
        score=1.0,
    )


async def _answer(
    question: str, answers: Mapping[str, Extraction]
) -> tuple[AgentAnswer, list[str]]:
    extractor: KeyedExtractor = KeyedExtractor(answers)
    workflow: AgentRAGWorkflow = AgentRAGWorkflow(
        retriever=StubRetriever([_node()]), extractor=extractor, synthesizer=_refuse
    )
    return await workflow.run(question), extractor.questions


async def test_given_a_spelled_out_sum_when_answered_then_the_operands_are_added() -> None:
    """The reference for a total printed nowhere is a sum, and the question names its parts."""
    answer, asked = await _answer(TOTAL_GHG, SCOPES)

    assert asked == ["Scope 1", "Scope 2", "Scope 3"]
    assert answer.value == "6,270,587"
    assert answer.unit == "t"
    assert answer.refused is False


async def test_given_an_operand_not_stated_when_answered_then_the_printed_figure_wins() -> None:
    """A partial sum is worse than the printed total, so a missing operand ends the attempt."""
    answers: dict[str, Extraction] = {"Scope 1": SCOPES["Scope 1"], **PRINTED_TOTAL}

    answer, asked = await _answer(TOTAL_GHG, answers)

    assert asked == ["Scope 1", "Scope 2", "Scope 3", TOTAL_GHG]
    assert answer.value == "6,197,690"
    assert answer.unit == "Tonnes CO₂e"


async def test_given_a_question_without_arithmetic_when_answered_then_it_is_extracted_once() -> (
    None
):
    """Every other question must cost exactly what it cost before derivation existed."""
    answers: dict[str, Extraction] = {
        PLAIN: Extraction(value="8,388", unit="Tonnes", label="Total hazardous waste")
    }

    answer, asked = await _answer(PLAIN, answers)

    assert asked == [PLAIN]
    assert answer.value == "8,388"
    assert answer.unit == "Tonnes"


@pytest.mark.parametrize(
    ("question", "unit", "value", "expected_value", "expected_unit"),
    [
        pytest.param(
            "Total energy consumption (MWh)", "GJ", "3.6", "1", "MWh", id="converted-to-the-ask"
        ),
        pytest.param(
            "Total energy consumption (MWh)", "MWh", "3.6", "3.6", "MWh", id="already-asked-for"
        ),
        pytest.param(
            "Total emissions (t)", "MWh", "3.6", "3.6", "MWh", id="another-dimension-left-alone"
        ),
        pytest.param("Total energy consumption (MWh)", "", "3.6", "3.6", "", id="unit-not-printed"),
    ],
)
async def test_given_a_question_that_states_a_unit_when_answered_then_the_figure_is_converted(
    question: str, unit: str, value: str, expected_value: str, expected_unit: str
) -> None:
    """A figure in the wrong unit is scored wrong, and the question states which is wanted."""
    answers: dict[str, Extraction] = {
        question: Extraction(value=value, unit=unit, label="Total energy consumption")
    }

    answer, _ = await _answer(question, answers)

    assert answer.value == expected_value
    assert answer.unit == expected_unit
