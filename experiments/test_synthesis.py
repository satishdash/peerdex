"""Stage 2 — Synthesis evaluation.

Metrics:
  - Faithfulness:      Is the answer grounded in the retrieved passages?
  - AnswerRelevancy:   Does the answer address the question asked?

Run:
    pytest experiments/test_synthesis.py -v --company suncor --year 2025
"""
from __future__ import annotations

import pytest
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase

from experiments.conftest import EvalCase, load_qa_cases, run_pipeline

from peerdex.shared.settings import get_settings

_JUDGE = get_settings().llm.judge_model or get_settings().llm.model
_FAITHFULNESS = FaithfulnessMetric(threshold=0.7, model=_JUDGE)
_ANSWER_RELEVANCY = AnswerRelevancyMetric(threshold=0.7, model=_JUDGE)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case" not in metafunc.fixturenames:
        return
    company = metafunc.config.getoption("--company")
    year = metafunc.config.getoption("--year")
    cases = load_qa_cases(company=company, year=year, require_answer=True)
    metafunc.parametrize("case", cases, ids=[c.id for c in cases])


async def test_faithfulness(case: EvalCase) -> None:
    result = await run_pipeline(case.q, company=case.company, year=case.year)
    if result.refused:
        pytest.skip("pipeline refused — no answer to evaluate")
    tc = LLMTestCase(
        input=case.q,
        actual_output=result.answer,
        retrieval_context=result.contexts,
    )
    assert_test(tc, [_FAITHFULNESS])


async def test_answer_relevancy(case: EvalCase) -> None:
    result = await run_pipeline(case.q, company=case.company, year=case.year)
    if result.refused:
        pytest.skip("pipeline refused — no answer to evaluate")
    tc = LLMTestCase(
        input=case.q,
        actual_output=result.answer,
    )
    assert_test(tc, [_ANSWER_RELEVANCY])
