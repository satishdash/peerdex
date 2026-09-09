"""Canonical id derivation. Single source of truth used by every stage."""

import hashlib
from pathlib import Path
from typing import Final, Literal

_READ_CHUNK: Final[int] = 1 << 20
_DOC_ID_LEN: Final[int] = 16

NodeKind = Literal["p", "c"]


def doc_id(company: str, source_path: str | Path, extractor: str) -> str:
    """Stable hash of company, extractor and file content, so extractor variants coexist."""
    digest = hashlib.sha256(f"{company.strip().lower()}:{extractor.strip().lower()}".encode())
    with Path(source_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()[:_DOC_ID_LEN]


def node_id(doc_id_: str, idx: int, kind: NodeKind) -> str:
    """Node id tagged with the kind that minted it.

    Parents are numbered by section and children by a running counter, so both
    sequences start at zero and would otherwise hand the same id to a parent and a
    child, leaving that child as its own parent.
    """
    return f"{doc_id_}:{kind}{idx}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
