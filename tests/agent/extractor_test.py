"""A figure is only trustworthy if the model can say which printed row and column it came from."""

from typing import Any

import pytest
from llama_index.core.schema import NodeWithScore, TextNode
from pytest_mock import MockerFixture

from peerdex.agent._agent import Extraction, Plan
from peerdex.agent._extractor import LLMQuantitativeExtractor

PLAN: Plan = Plan(kind="quantitative", period="2025", scope="global", unit="tonnes")

NO_PERIOD: Plan = Plan(kind="quantitative", period="", scope="", unit="")

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


async def test_given_a_column_matching_the_period_when_extracting_then_the_value_is_kept(
    mocker: MockerFixture,
) -> None:
    """Naming the column is what distinguishes this period's figure from its neighbours."""
    extractor = _extractor(
        mocker,
        '{"value": "62,587", "unit": "Tonnes CO2e", "label": "Scope 1", "column": "2025"}',
    )

    result: Extraction = await extractor.extract("Gross global Scope 1 emissions", PLAN, NODES)

    assert result.value == "62,587"
    assert result.column == "2025"


async def test_given_a_column_from_another_period_when_extracting_then_it_refuses(
    mocker: MockerFixture,
) -> None:
    """Measured: `298,498` from the `Baseline 2015` column was returned for a 2025 question.

    A row label alone cannot catch this - the label was correct and the figure was
    still the wrong one, because the period column went unchecked.
    """
    extractor = _extractor(
        mocker,
        '{"value": "298,498", "unit": "Tonnes CO2e", "label": "Scope 1", '
        '"column": "Baseline 2015"}',
    )

    result: Extraction = await extractor.extract("Gross global Scope 1 emissions", PLAN, NODES)

    assert result.value == ""
    assert result.column == ""


async def test_given_a_figure_in_no_column_when_extracting_then_it_survives(
    mocker: MockerFixture,
) -> None:
    """Prose, and any document that prints one value per label, has no columns to check."""
    extractor = _extractor(
        mocker,
        '{"value": "8,388", "unit": "Tonnes", "label": "Total hazardous waste", "column": ""}',
    )

    result: Extraction = await extractor.extract("Total hazardous waste", PLAN, NODES)

    assert result.value == "8,388"


async def test_given_no_asked_for_period_when_extracting_then_the_column_is_not_policed(
    mocker: MockerFixture,
) -> None:
    """With no period to check against, the column is information rather than a constraint."""
    extractor = _extractor(
        mocker,
        '{"value": "298,498", "unit": "Tonnes CO2e", "label": "Scope 1", '
        '"column": "Baseline 2015"}',
    )

    result: Extraction = await extractor.extract("Scope 1 emissions", NO_PERIOD, NODES)

    assert result.value == "298,498"


async def test_given_a_column_naming_no_period_when_extracting_then_it_is_not_policed(
    mocker: MockerFixture,
) -> None:
    """Measured: policing every column cost two correct board-member counts.

    A table may break a figure down by something that is not a period at all, and
    such a column is evidence about the row, not a period to be checked.
    """
    extractor = _extractor(
        mocker,
        '{"value": "7", "unit": "", "label": "Board members", "column": "Female"}',
    )

    result: Extraction = await extractor.extract("Number of Female Board members", PLAN, NODES)

    assert result.value == "7"
    assert result.column == "Female"


@pytest.mark.parametrize("fragment", ["column header", "must be that period"])
def test_given_the_prompt_when_built_then_it_demands_the_period_column(fragment: str) -> None:
    """Recall improving is not enough; the prompt has to name the column discipline."""
    prompt: str = LLMQuantitativeExtractor._prompt("Q", PLAN, NODES)

    assert fragment in prompt
