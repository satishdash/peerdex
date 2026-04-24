"""Shared fixtures and helpers for the peerdex eval harness.

All test files in experiments/ import from here. The pipeline is run
once per question and cached in-process so multiple metrics don't
re-invoke retrieval+synthesis.

Company and year are passed via pytest CLI:
    pytest experiments/ --company suncor --year 2025
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
import yaml

from peerdex.retrieve import retrieve as do_retrieve
from peerdex.shared.settings import CONFIG_PATH
from peerdex.synthesize import synthesize as do_synth

SUITES_PATH = CONFIG_PATH.parent / "suites.yaml"


# ---------- pytest CLI options ----------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--company", required=True, help="Company to evaluate (e.g. suncor)")
    parser.addoption("--year", required=True, type=int, help="Report year (e.g. 2025)")


@pytest.fixture(scope="session")
def company(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--company")


@pytest.fixture(scope="session")
def year(request: pytest.FixtureRequest) -> int:
    return request.config.getoption("--year")


# ---------- data models ----------

@dataclass(frozen=True)
class EvalCase:
    suite: str
    q: str
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


# ---------- loaders ----------

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
            # Look up ground truth for this company/year
            gt = (entry.get("ground_truth") or {}).get(company, {}).get(year, {})
            expected_answer = gt.get("expected_answer")
            expected_pages = gt.get("expected_pages") or []

            if require_answer and not expected_answer:
                continue
            cases.append(EvalCase(
                suite=suite_name,
                q=entry["q"],
                expected_answer=expected_answer,
                expected_pages=expected_pages,
                company=company,
                year=year,
            ))
    return cases


def load_vlm_golden() -> list[dict]:
    cfg = yaml.safe_load(SUITES_PATH.read_text()) or {}
    return cfg.get("vlm_golden") or []


# ---------- pipeline runners (async, cached) ----------

_cache: dict[str, PipelineResult] = {}


async def run_pipeline(
    q: str,
    *,
    company: str,
    year: int,
) -> PipelineResult:
    """Run retrieve+synth, cached in-process to avoid duplicate LLM calls."""
    cache_key = f"{company}:{year}:{q}"
    if cache_key in _cache:
        return _cache[cache_key]

    result = await do_retrieve(q, company=company, year=year)
    nodes = result.nodes
    contexts = [n.node.get_content() for n in nodes]
    pages = [int(n.node.metadata.get("page_no", 0) or 0) for n in nodes]

    if not nodes:
        out = PipelineResult(answer="", contexts=contexts, pages=pages, refused=True)
        _cache[cache_key] = out
        return out

    answer = await do_synth(q, nodes, report_type=result.report_type)
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
) -> PipelineResult:
    """Run retrieval only (no synthesis)."""
    result = await do_retrieve(q, company=company, year=year)
    nodes = result.nodes
    contexts = [n.node.get_content() for n in nodes]
    pages = [int(n.node.metadata.get("page_no", 0) or 0) for n in nodes]
    return PipelineResult(answer="", contexts=contexts, pages=pages, refused=not nodes)
