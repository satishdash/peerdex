"""Canonical id derivation. Single source of truth used by every stage."""

import hashlib
from pathlib import Path
from typing import Final

_READ_CHUNK: Final[int] = 1 << 20
_DOC_ID_LEN: Final[int] = 16


def doc_id(company: str, source_path: str | Path, extractor: str) -> str:
    """Stable hash of company, extractor and file content, so extractor variants coexist."""
    digest = hashlib.sha256(f"{company.strip().lower()}:{extractor.strip().lower()}".encode())
    with Path(source_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()[:_DOC_ID_LEN]


def node_id(doc_id_: str, idx: int) -> str:
    return f"{doc_id_}:{idx}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
