"""Canonical types shared across the pipeline.

Heavy node/chunk schemas live in LlamaIndex (TextNode) post-Phase 1.
This module is intentionally minimal: just the ReportType enum used
to look up per-report-type prompts and tag nodes.
"""

from enum import StrEnum


class ReportType(StrEnum):
    ANNUAL_REPORT = "annual_report"
    SUSTAINABILITY_REPORT = "sustainability_report"
