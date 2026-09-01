"""Unit tests for the pure evaluation-funnel core: matching, recall, classification, report."""

from typing import Any

import pytest

from peerdex.funnel import (
    BlockProjector,
    FunnelRow,
    OracleValue,
    ParseRecall,
    QuestionRecall,
    RetrievalOutcome,
    RetrievalRecall,
    RetrievedPassage,
    SearchableBlock,
    StageDocument,
    ValueMatcher,
)
from peerdex.parse import (
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from peerdex.scoring import AnswerScorer, Comparison, NumericParser


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Scope 1: 62,587 tCO2e and intensity 1.26", [1.0, 62587.0, 1.26]),
        ("revenue $58,739 million", [58739000000.0]),
        ("tCO2e H2O FY2025", []),
        ("(1,234) then 5", [-1234.0, 5.0]),
        ("no numbers", []),
    ],
)
def test_given_text_when_all_numbers_parsed_then_standalone_tokens_only(
    text: str, expected: list[float]
) -> None:
    assert NumericParser().parse_all(text) == expected


@pytest.mark.parametrize(
    ("expected", "actual", "category"),
    [
        (62587.0, 62587.0, "match"),
        (6.368763888888889, 6368764.0, "scale_mismatch"),
        (747.0, 90000.0, "mismatch"),
    ],
)
def test_given_numbers_when_categorised_then_category(
    expected: float, actual: float, category: str
) -> None:
    assert AnswerScorer().categorise(expected, actual).category == category


@pytest.mark.parametrize(
    ("oracle", "text", "category", "scale"),
    [
        pytest.param(62587.0, "Scope 1: 62,587 tCO2e", "match", None, id="exact"),
        pytest.param(6.368763888888889, "Energy 6,368,764 kWh", "scale_mismatch", 1e-6, id="scale"),
        pytest.param(1.26, "1,260 then 1.26", "match", None, id="exact-preferred-over-scale"),
        pytest.param(2.0, "Scope 2 market-based", "match", None, id="small-integer-ceiling"),
    ],
)
def test_given_text_when_matched_then_best_comparison(
    oracle: float, text: str, category: str, scale: float | None
) -> None:
    result: Comparison | None = ValueMatcher().match(oracle, text)
    assert result is not None
    assert result.category == category
    assert result.scale == scale


@pytest.mark.parametrize(
    ("oracle", "text"),
    [
        pytest.param(747.0, "no relevant 90,000 here", id="different-value"),
        pytest.param(2.0, "tCO2e only", id="digit-inside-word"),
        pytest.param(5.0, "no digits", id="no-numbers"),
    ],
)
def test_given_text_without_value_when_matched_then_none(oracle: float, text: str) -> None:
    assert ValueMatcher().match(oracle, text) is None


def _block(
    text: str, kind: str = "paragraph", page: int = 1, heading: str = "H"
) -> SearchableBlock:
    return SearchableBlock(source="a.pdf", page_no=page, kind=kind, heading_path=heading, text=text)


def test_given_corpus_when_recall_evaluated_then_statuses_and_provenance() -> None:
    oracle: list[OracleValue] = [
        OracleValue("Scope 1", "62587.0"),
        OracleValue("Energy", "6.368763888888889"),
        OracleValue("Employees", "747.0"),
        OracleValue("Broken", "n/a"),
    ]
    blocks: list[SearchableBlock] = [
        _block("Scope 1 emissions 62,587 tCO2e", "table", 4, "Climate > GHG"),
        _block("Total energy 6,368,764 kWh", "paragraph", 9, "Energy"),
        _block("Scope 1 emissions were 62,587 again", "paragraph", 5, "Climate"),
        _block("Headcount 90,000"),
    ]
    results: list[QuestionRecall] = ParseRecall().evaluate(oracle, blocks)
    assert [r.status for r in results] == ["exact", "scale", "miss", "miss"]
    scope1: QuestionRecall = results[0]
    assert len(scope1.hits) == 2
    assert scope1.hits[0].page_no == 4
    assert scope1.hits[0].block_kind == "table"
    assert scope1.hits[0].heading_path == "Climate > GHG"
    assert scope1.hits[0].source == "a.pdf"
    assert scope1.hits[0].hit_kind == "exact"
    assert scope1.hits[1].page_no == 5
    energy: QuestionRecall = results[1]
    assert len(energy.hits) == 1
    assert energy.hits[0].hit_kind == "scale"
    assert energy.hits[0].scale == 1e-6
    assert energy.hits[0].number == 6368764.0
    assert results[2].hits == []
    assert ParseRecall.summary(results) == {
        "population": 4,
        "exact": 1,
        "scale": 1,
        "miss": 2,
        "reachable": 2,
    }


def test_given_text_only_and_full_results_when_delta_taken_then_vlm_only_questions() -> None:
    oracle: list[OracleValue] = [OracleValue("A", "10.0"), OracleValue("B", "20.0")]
    text_blocks: list[SearchableBlock] = [_block("value 10")]
    picture_blocks: list[SearchableBlock] = [_block("figure shows 20", "picture")]
    recall: ParseRecall = ParseRecall()
    text_only: list[QuestionRecall] = recall.evaluate(oracle, text_blocks)
    full: list[QuestionRecall] = recall.evaluate(oracle, [*text_blocks, *picture_blocks])
    assert ParseRecall.vlm_only(text_only, full) == ["B"]


def test_given_contract_blocks_when_projected_then_searchable_text_with_kinds() -> None:
    blocks: list[Any] = [
        HeadingBlock(kind="heading", level=1, text="Climate", page_no=2, heading_path=[]),
        ParagraphBlock(
            kind="paragraph", text="Scope 1 was 62,587.", page_no=2, heading_path=["Climate"]
        ),
        ListBlock(
            kind="list", items=["a 1", "b 2"], ordered=False, page_no=3, heading_path=["Climate"]
        ),
        TableBlock(
            kind="table",
            headers=["metric", "2025"],
            rows=[["water", "22.15"]],
            caption="Water",
            page_no=4,
            heading_path=["Climate", "Water"],
        ),
        PictureBlock(kind="picture", pil_image=None, bbox_area_pct=5.0, page_no=5, heading_path=[]),
    ]
    projected: list[SearchableBlock] = BlockProjector().project("a.pdf", blocks)
    assert [b.kind for b in projected] == ["heading", "paragraph", "list", "table"]
    assert projected[0].text == "Climate"
    assert projected[2].text == "a 1\nb 2"
    assert projected[3].text == "Water\nmetric | 2025\nwater | 22.15"
    assert projected[3].heading_path == "Climate > Water"
    assert projected[3].page_no == 4
    assert all(b.source == "a.pdf" for b in projected)


def test_given_picture_descriptions_when_projected_then_only_described_pictures() -> None:
    pictures: list[PictureBlock] = [
        PictureBlock(
            kind="picture", pil_image=None, bbox_area_pct=5.0, page_no=5, heading_path=["F"]
        ),
        PictureBlock(kind="picture", pil_image=None, bbox_area_pct=5.0, page_no=6, heading_path=[]),
    ]
    descriptions: list[dict[str, Any] | None] = [
        {
            "title": "Emissions by scope",
            "description": "Bar chart",
            "values": [{"label": "Scope 3", "value": "6,197,690", "unit": "tCO2e"}],
        },
        None,
    ]
    projected: list[SearchableBlock] = BlockProjector().project_pictures(
        "a.pdf", pictures, descriptions
    )
    assert len(projected) == 1
    assert projected[0].kind == "picture"
    assert projected[0].page_no == 5
    assert projected[0].heading_path == "F"
    assert projected[0].text == "Emissions by scope\nBar chart\nScope 3: 6,197,690 tCO2e"


@pytest.mark.parametrize(
    ("passage_text", "extractable", "status"),
    [
        pytest.param("Scope 1 62,587 tCO2e", False, "hit", id="hit-wins-over-extractable-flag"),
        pytest.param("unrelated 5", False, "not_extractable", id="absent-from-corpus"),
        pytest.param("unrelated 5", True, "not_retrieved", id="present-but-not-surfaced"),
    ],
)
def test_given_retrieved_passages_when_classified_then_miss_attributed(
    passage_text: str, extractable: bool, status: str
) -> None:
    outcome: RetrievalOutcome = RetrievalRecall().classify(
        OracleValue("Scope 1", "62587.0"),
        [RetrievedPassage(text=passage_text, page_no=4)],
        extractable=extractable,
        expected_pages=[4, 9],
    )
    assert outcome.status == status
    assert outcome.page_hit is True
    assert outcome.retrieved_pages == [4]
    assert outcome.expected_pages == [4, 9]


def test_given_outcomes_when_summarised_then_counts_and_page_hit_rate() -> None:
    recall: RetrievalRecall = RetrievalRecall()
    outcomes: list[RetrievalOutcome] = [
        recall.classify(OracleValue("A", "1.0"), [RetrievedPassage("1", 3)], True, [3]),
        recall.classify(OracleValue("B", "2.0"), [RetrievedPassage("x", 7)], True, [3]),
        recall.classify(OracleValue("C", "3.0"), [RetrievedPassage("x", 7)], False, []),
    ]
    assert RetrievalRecall.summary(outcomes) == {
        "population": 3,
        "hit": 1,
        "not_retrieved": 1,
        "not_extractable": 1,
        "page_hit_rate": 0.5,
    }


def test_given_stage_json_when_read_then_reachable_and_pages() -> None:
    document: StageDocument = StageDocument(
        {
            "stage": 0,
            "extractor": "liteparse",
            "summary": {"reachable": 2},
            "questions": [
                {"question": "A", "status": "exact", "hits": [{"page_no": 4}, {"page_no": 2}]},
                {"question": "B", "status": "scale", "hits": [{"page_no": 4}]},
                {"question": "C", "status": "miss", "hits": []},
            ],
        }
    )
    assert document.extractor == "liteparse"
    assert document.reachable_questions() == {"A", "B"}
    assert document.pages_for("A") == [2, 4]
    assert document.pages_for("C") == []
    assert document.pages_for("missing") == []
    assert document.summary_value("reachable") == 2
    assert document.summary_value("absent") is None


def test_given_stage_summaries_when_row_built_then_counts_and_drops() -> None:
    row: FunnelRow = FunnelRow.build(
        "liteparse",
        {"reachable": 20},
        {"reachable": 22},
        {"hit": 15},
        {"match": 12},
    )
    assert row.extractor == "liteparse"
    assert row.stages == [20, 22, 15, 12]
    assert row.drops == [None, 2, -7, -3]


def test_given_missing_stages_when_row_built_then_none_cells() -> None:
    row: FunnelRow = FunnelRow.build("odl", {"reachable": 9}, None, None, None)
    assert row.stages == [9, None, None, None]
    assert row.drops == [None, None, None, None]
