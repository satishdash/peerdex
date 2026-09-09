"""Answer evaluation over the default suite through the agent: oracle match plus LLM-judged quality.

Parameterised over the quantitative questions that carry a value for the requested
company/year. A refusal on a valued question is a failure, never a skip.

Run:
    pytest experiments/test_synthesis.py -v --company acme --year 2025 --extractor liteparse
"""

import pytest
from conftest import EvalCase, run_agent, run_retrieve_only, valued_cases
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.test_case import LLMTestCase

from peerdex.agent import AgentAnswer
from peerdex.scoring import AnswerScorer, Comparison
from peerdex.shared.settings import get_settings

_JUDGE = get_settings().llm.judge_model or get_settings().llm.model
_FAITHFULNESS = FaithfulnessMetric(threshold=0.7, model=_JUDGE)
_ANSWER_RELEVANCY = AnswerRelevancyMetric(threshold=0.7, model=_JUDGE)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "case" not in metafunc.fixturenames:
        return
    cases: list[EvalCase] = valued_cases(
        company=metafunc.config.getoption("--company"),
        year=metafunc.config.getoption("--year"),
    )
    metafunc.parametrize("case", cases, ids=[c.id for c in cases])


async def _answer(case: EvalCase, extractor: str | None) -> AgentAnswer:
    result: AgentAnswer = await run_agent(
        case.q, company=case.company, year=case.year, extractor=extractor, kind="quantitative"
    )
    assert not result.refused, (
        f"agent refused: {result.reason} after {len(result.attempts)} attempts"
    )
    return result


async def test_answer_matches_oracle(case: EvalCase, extractor: str | None) -> None:
    result: AgentAnswer = await _answer(case, extractor)
    comparison: Comparison = AnswerScorer().score(case.expected_answer or "", result.value)
    assert comparison.category == "match", (
        f"{comparison.category}: expected {case.expected_answer!r}, got {result.value!r} "
        f"{result.unit} (scale {comparison.scale})"
    )


async def test_faithfulness(case: EvalCase, extractor: str | None) -> None:
    result: AgentAnswer = await _answer(case, extractor)
    retrieval = await run_retrieve_only(
        case.q, company=case.company, year=case.year, extractor=extractor
    )
    tc = LLMTestCase(
        input=case.q,
        actual_output=f"{result.value} {result.unit}".strip(),
        retrieval_context=retrieval.contexts,
    )
    assert_test(tc, [_FAITHFULNESS])


async def test_answer_relevancy(case: EvalCase, extractor: str | None) -> None:
    result: AgentAnswer = await _answer(case, extractor)
    tc = LLMTestCase(input=case.q, actual_output=f"{result.value} {result.unit}".strip())
    assert_test(tc, [_ANSWER_RELEVANCY])
