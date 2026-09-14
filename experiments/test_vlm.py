"""Stage 0 — VLM extraction evaluation.

Tests whether the vision model correctly extracts structured data from
figures and tables during ingestion.

Currently a placeholder — requires manually verified golden data in
config/suites.yaml under ``vlm_golden``. Add entries as you QA VLM
output, then implement the cache lookup in ``_find_cached_vlm_output``.

Run:
    pytest experiments/test_vlm.py -v
"""

from __future__ import annotations

import pytest
from conftest import load_vlm_golden
from deepeval.metrics import FaithfulnessMetric

from shared.settings import get_settings

_GOLDEN = load_vlm_golden()
_JUDGE = get_settings().llm.judge_model or get_settings().llm.model
_FAITHFULNESS = FaithfulnessMetric(threshold=0.7, model=_JUDGE)


@pytest.mark.parametrize(
    "entry",
    _GOLDEN or [pytest.param(None, marks=pytest.mark.skip("no vlm_golden entries"))],
    ids=[f"{e.get('doc_id', '?')}::p{e.get('page', '?')}" for e in _GOLDEN] or ["empty"],
)
def test_vlm_extraction_faithfulness(entry: dict | None) -> None:
    """Check that VLM output is faithful to the expected fields."""
    if entry is None:
        pytest.skip("no vlm_golden entries defined")

    expected = entry.get("expected_fields") or {}
    if not expected:
        pytest.skip("no expected_fields for this entry")

    # TODO: implement VLM cache lookup by doc_id + page.
    # VLM cache keys are sha256(image_bytes + model + prompt_version),
    # so reverse-lookup requires a secondary index. Build this when
    # the first golden entries are added.
    pytest.skip(
        f"VLM cache lookup not yet implemented — "
        f"add index for {entry.get('doc_id')} p.{entry.get('page')}"
    )
