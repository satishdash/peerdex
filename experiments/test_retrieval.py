"""Stage 1 — Retrieval evaluation.

Metrics:
  - retrieval_page_precision:  Did we retrieve from expected pages? (deterministic)
  - ContextualPrecision:       Are top-ranked passages the right ones? (LLM judge)
  - ContextualRelevancy:       Are returned passages relevant to the query? (LLM judge)

Run:
    pytest experiments/test_retrieval.py -v --company suncor --year 2025
"""
from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.metrics import ContextualPrecisionMetric, ContextualRelevancyMetric
from deepeval.test_case import LLMTestCase

from experiments.conftest import EvalCase, load_qa_cases, run_retrieve_only

from peerdex.shared.settings import get_settings

_JUDGE = get_settings().llm.judge_model or get_settings().llm.model
_CTX_PRECISION = ContextualPrecisionMetric(threshold=0.5, model=_JUDGE)
_CTX_RELEVANCY = ContextualRelevancyMetric(threshold=0.5, model=_JUDGE)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parametrize based on --company/--year CLI options."""
    if "case" not in metafunc.fixturenames:
        return
    company = metafunc.config.getoption("--company")
    year = metafunc.config.getoption("--year")

    if metafunc.function is test_retrieval_page_precision:
        cases = [c for c in load_qa_cases(company=company, year=year) if c.expected_pages]
    else:
        cases = load_qa_cases(company=company, year=year, require_answer=True)

    metafunc.parametrize("case", cases, ids=[c.id for c in cases])


async def test_retrieval_page_precision(case: EvalCase) -> None:
    """At least one retrieved passage comes from an expected page."""
    result = await run_retrieve_only(case.q, company=case.company, year=case.year)
    expected = set(case.expected_pages)
    actual = set(result.pages)
    hits = expected & actual
    assert hits, (
        f"Retrieval missed all expected pages. "
        f"Expected: {sorted(expected)}, got: {sorted(actual)}"
    )


async def test_contextual_precision(case: EvalCase) -> None:
    result = await run_retrieve_only(case.q, company=case.company, year=case.year)
    tc = LLMTestCase(
        input=case.q,
        actual_output=case.expected_answer or "",
        expected_output=case.expected_answer or "",
        retrieval_context=result.contexts,
    )
    assert_test(tc, [_CTX_PRECISION])


async def test_contextual_relevancy(case: EvalCase) -> None:
    result = await run_retrieve_only(case.q, company=case.company, year=case.year)
    tc = LLMTestCase(
        input=case.q,
        actual_output=case.expected_answer or "",
        retrieval_context=result.contexts,
    )
    assert_test(tc, [_CTX_RELEVANCY])
