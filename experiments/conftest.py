"""Shared fixtures and helpers for the peerdex eval harness.

All test files in experiments/ import from here. The pipeline is run
once per question and cached in-process so multiple metrics don't
re-invoke retrieval+synthesis.

Company and year are passed via pytest CLI:
    pytest experiments/ --company acme --year 2025
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from peerdex.agent import AgentAnswer, QuestionKind
from peerdex.agent import answer as agent_answer
from peerdex.funnel import StageDocument
from peerdex.retrieve import retrieve as do_retrieve
from peerdex.shared.metadata import Scalar
from peerdex.shared.settings import CONFIG_PATH
from peerdex.synthesize import synthesize as do_synth

SUITES_PATH = CONFIG_PATH.parent / "suites.yaml"
SUITE_NAME = "default"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--company", required=True, help="Company identifier to evaluate")
    parser.addoption("--year", required=True, type=int, help="Report year (e.g. 2025)")
    parser.addoption("--extractor", default=None, help="Restrict retrieval to one extractor")
    parser.addoption("--stage0", default=None, help="Path to a stage0_<extractor>.json")


@pytest.fixture(scope="session")
def company(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption("--company"))


@pytest.fixture(scope="session")
def year(request: pytest.FixtureRequest) -> int:
    return int(request.config.getoption("--year"))


@pytest.fixture(scope="session")
def extractor(request: pytest.FixtureRequest) -> str | None:
    value: Any = request.config.getoption("--extractor")
    return None if value is None else str(value)


@pytest.fixture(scope="session")
def stage0_pages(request: pytest.FixtureRequest) -> dict[str, list[int]]:
    """Question -> pages recorded by stage 0; empty when no readable --stage0 was given."""
    raw: Any = request.config.getoption("--stage0")
    path: Path | None = None if raw is None else Path(str(raw))
    if path is None or not path.exists():
        return {}
    document: StageDocument = StageDocument(json.loads(path.read_text()))
    return {q: document.pages_for(q) for q in document.reachable_questions()}


@dataclass(frozen=True)
class EvalCase:
    suite: str
    q: str
    kind: str
    expected_answer: str | None
    expected_pages: list[int]
    company: str
    year: int

    @property
    def id(self) -> str:
        return f"{self.company}:{self.year}::{self.suite}::{self.q[:50]}"


@dataclass
class PipelineResult:
    answer: str
    contexts: list[str]
    pages: list[int]
    refused: bool


def load_qa_cases(
    *,
    company: str,
    year: int,
    require_answer: bool = False,
) -> list[EvalCase]:
    """Load eval cases for a specific company/year from suites.yaml."""
    cfg = yaml.safe_load(SUITES_PATH.read_text()) or {}
    cases: list[EvalCase] = []
    for suite_name, block in (cfg.get("suites") or {}).items():
        for entry in block.get("questions") or []:
            if not isinstance(entry, dict):
                continue
            gt = (entry.get("ground_truth") or {}).get(company, {}).get(year, {})
            expected_answer = gt.get("expected_answer")
            expected_pages = gt.get("expected_pages") or []

            if require_answer and not expected_answer:
                continue
            cases.append(
                EvalCase(
                    suite=suite_name,
                    q=entry["q"],
                    kind=entry.get("kind") or "quantitative",
                    expected_answer=expected_answer,
                    expected_pages=expected_pages,
                    company=company,
                    year=year,
                )
            )
    return cases


def valued_cases(*, company: str, year: int) -> list[EvalCase]:
    """The scoreable population: quantitative default questions carrying a value."""
    return [
        case
        for case in load_qa_cases(company=company, year=year, require_answer=True)
        if case.suite == SUITE_NAME and case.kind == "quantitative"
    ]


def load_vlm_golden() -> list[dict[str, Any]]:
    cfg = yaml.safe_load(SUITES_PATH.read_text()) or {}
    return list(cfg.get("vlm_golden") or [])


def _filters(year: int, extractor: str | None) -> dict[str, Scalar]:
    filters: dict[str, Scalar] = {"year": year}
    if extractor is not None:
        filters["extractor"] = extractor
    return filters


_cache: dict[str, PipelineResult] = {}


async def run_pipeline(
    q: str,
    *,
    company: str,
    year: int,
    extractor: str | None = None,
) -> PipelineResult:
    """Run retrieve+synth, cached in-process to avoid duplicate LLM calls."""
    cache_key = f"{company}:{year}:{extractor}:{q}"
    if cache_key in _cache:
        return _cache[cache_key]

    result = await do_retrieve(q, company=company, filters=_filters(year, extractor))
    nodes = result.nodes
    contexts = [n.node.get_content() for n in nodes]
    pages = [int(n.node.metadata.get("page_no", 0) or 0) for n in nodes]

    if not nodes:
        out = PipelineResult(answer="", contexts=contexts, pages=pages, refused=True)
        _cache[cache_key] = out
        return out

    answer = await do_synth(q, nodes)
    out = PipelineResult(
        answer=answer.answer if not answer.refused else "",
        contexts=contexts,
        pages=pages,
        refused=answer.refused,
    )
    _cache[cache_key] = out
    return out


async def run_retrieve_only(
    q: str,
    *,
    company: str,
    year: int,
    extractor: str | None = None,
) -> PipelineResult:
    """Run retrieval only (no synthesis)."""
    result = await do_retrieve(q, company=company, filters=_filters(year, extractor))
    nodes = result.nodes
    contexts = [n.node.get_content() for n in nodes]
    pages = [int(n.node.metadata.get("page_no", 0) or 0) for n in nodes]
    return PipelineResult(answer="", contexts=contexts, pages=pages, refused=not nodes)


_agent_cache: dict[str, AgentAnswer] = {}


async def run_agent(
    q: str,
    *,
    company: str,
    year: int,
    extractor: str | None = None,
    kind: QuestionKind | None = None,
) -> AgentAnswer:
    """Run the agent once per question, cached in-process across metrics."""
    cache_key = f"{company}:{year}:{extractor}:{kind}:{q}"
    if cache_key in _agent_cache:
        return _agent_cache[cache_key]
    result: AgentAnswer = await agent_answer(
        q, company=company, filters=_filters(year, extractor), kind=kind
    )
    _agent_cache[cache_key] = result
    return result
