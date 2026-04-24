"""Canonical id derivation. Single source of truth used by every stage."""

import hashlib

from peerdex.shared.schema import ReportType


def doc_id(company: str, year: int, report_type: ReportType) -> str:
    """Stable hash of (company, year, report_type). Re-ingest yields same id."""
    key = f"{company.strip().lower()}|{int(year)}|{ReportType(report_type).value}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def node_id(doc_id_: str, idx: int) -> str:
    return f"{doc_id_}:{idx}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
