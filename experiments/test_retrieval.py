"""Retrieval evaluation over ref_bench01: value recall, page precision and LLM-judged context.

Parameterised over the quantitative questions that carry a value for the requested
company/year (28 for globex 2025). Page precision uses the pages stage 0
recorded when ``--stage0`` points at its JSON; without it only value recall is judged.

Run:
    pytest experiments/test_retrieval.py -v --company globex --year 2025 \
        --extractor liteparse --stage0 results/funnel/stage0_liteparse.json
"""

import pytest
from conftest import EvalCase, run_retrieve_only, valued_cases
from deepeval import assert_test
from deepeval.metrics import ContextualPrecisionMetric, ContextualRelevancyMetric
from deepeval.test_case import LLMTestCase

from peerdex.funnel import OracleValue, RetrievalOutcome, RetrievalRecall, RetrievedPassage
from peerdex.shared.settings import get_settings

_JUDGE = get_settings().llm.judge_model or get_settings().llm.model
_CTX_PRECISION = ContextualPrecisionMetric(threshold=0.5, model=_JUDGE)
_CTX_RELEVANCY = ContextualRelevancyMetric(threshold=0.5, model=_JUDGE)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case" not in metafunc.fixturenames:
        return
    cases: list[EvalCase] = valued_cases(
        company=metafunc.config.getoption("--company"),
        year=metafunc.config.getoption("--year"),
    )
    metafunc.parametrize("case", cases, ids=[c.id for c in cases])


async def test_retrieval_surfaces_value_on_recorded_pages(
    case: EvalCase, extractor: str | None, stage0_pages: dict[str, list[int]]
) -> None:
    result = await run_retrieve_only(
        case.q, company=case.company, year=case.year, extractor=extractor
    )
    passages: list[RetrievedPassage] = [
        RetrievedPassage(text=text, page_no=page)
        for text, page in zip(result.contexts, result.pages, strict=True)
    ]
    outcome: RetrievalOutcome = RetrievalRecall().classify(
        OracleValue(case.q, case.expected_answer or ""),
        passages,
        extractable=True,
        expected_pages=stage0_pages.get(case.q, []),
    )
    assert outcome.status == "hit", (
        f"value {case.expected_answer!r} absent from retrieved pages {outcome.retrieved_pages}"
    )
    assert outcome.page_hit or not outcome.expected_pages, (
        f"retrieved pages {outcome.retrieved_pages} miss recorded pages {outcome.expected_pages}"
    )


async def test_contextual_precision(case: EvalCase, extractor: str | None) -> None:
    result = await run_retrieve_only(
        case.q, company=case.company, year=case.year, extractor=extractor
    )
    tc = LLMTestCase(
        input=case.q,
        actual_output=case.expected_answer or "",
        expected_output=case.expected_answer or "",
        retrieval_context=result.contexts,
    )
    assert_test(tc, [_CTX_PRECISION])


async def test_contextual_relevancy(case: EvalCase, extractor: str | None) -> None:
    result = await run_retrieve_only(
        case.q, company=case.company, year=case.year, extractor=extractor
    )
    tc = LLMTestCase(
        input=case.q,
        actual_output=case.expected_answer or "",
        retrieval_context=result.contexts,
    )
    assert_test(tc, [_CTX_RELEVANCY])
