"""A figure is only trustworthy if the model can say which printed row it came from."""

from typing import Any

import pytest
from llama_index.core.schema import NodeWithScore, TextNode
from pytest_mock import MockerFixture

from peerdex.agent._agent import Extraction, Plan
from peerdex.agent._extractor import LLMQuantitativeExtractor

PLAN: Plan = Plan(kind="quantitative", period="2025", scope="global", unit="tonnes")

NODES: list[NodeWithScore] = [
    NodeWithScore(
        node=TextNode(
            id_="d1:c1",
            text="| Scope 1 | Tonnes CO2e | 62,587 |",
            metadata={"page_no": 45},
        ),
        score=1.0,
    )
]


def _extractor(mocker: MockerFixture, content: str) -> LLMQuantitativeExtractor:
    """An extractor whose single LLM call returns exactly ``content``."""
    response: Any = mocker.MagicMock()
    response.message.content = content
    llm: Any = mocker.MagicMock()
    llm.achat = mocker.AsyncMock(return_value=response)
    return LLMQuantitativeExtractor(llm=llm)


async def test_given_a_figure_with_its_label_when_extracting_then_the_label_is_kept(
    mocker: MockerFixture,
) -> None:
    """The label is the evidence that a specific row was read, not a nearby one."""
    extractor = _extractor(mocker, '{"value": "62,587", "unit": "Tonnes CO2e", "label": "Scope 1"}')

    result: Extraction = await extractor.extract("Gross global Scope 1 emissions", PLAN, NODES)

    assert result.value == "62,587"
    assert result.unit == "Tonnes CO2e"
    assert result.label == "Scope 1"


async def test_given_a_value_with_no_label_when_extracting_then_it_refuses(
    mocker: MockerFixture,
) -> None:
    """A number nobody can attribute to a printed row is how a neighbour gets returned."""
    extractor = _extractor(mocker, '{"value": "1,470,181", "unit": "MWh", "label": ""}')

    result: Extraction = await extractor.extract("Total energy consumed - Nuclear", PLAN, NODES)

    assert result.value == ""
    assert result.unit == ""
    assert result.label == ""


async def test_given_a_response_missing_the_label_key_when_extracting_then_it_refuses(
    mocker: MockerFixture,
) -> None:
    """An older or sloppy response shape must fail closed, not pass unchecked."""
    extractor = _extractor(mocker, '{"value": "1,470,181", "unit": "MWh"}')

    result: Extraction = await extractor.extract("Total energy consumed - Coal", PLAN, NODES)

    assert result.value == ""


async def test_given_an_empty_value_when_extracting_then_everything_is_empty(
    mocker: MockerFixture,
) -> None:
    """An honest abstention stays an abstention."""
    extractor = _extractor(mocker, '{"value": "", "unit": "", "label": ""}')

    result: Extraction = await extractor.extract("Total units recalled", PLAN, NODES)

    assert (result.value, result.unit, result.label) == ("", "", "")


async def test_given_unparseable_output_when_extracting_then_it_refuses(
    mocker: MockerFixture,
) -> None:
    """A malformed response must never become an answer."""
    extractor = _extractor(mocker, "I could not find it")

    result: Extraction = await extractor.extract("Total water consumption", PLAN, NODES)

    assert result.value == ""


@pytest.mark.parametrize("fragment", ["label", "exactly as printed"])
def test_given_the_prompt_when_built_then_it_demands_the_printed_label(fragment: str) -> None:
    """The instruction has to be in the prompt, not only in our intent."""
    prompt: str = LLMQuantitativeExtractor._prompt("Q", PLAN, NODES)

    assert fragment in prompt
