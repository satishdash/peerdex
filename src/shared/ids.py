"""Canonical id derivation. Single source of truth used by every stage."""

import hashlib
from pathlib import Path
from typing import ClassVar, Literal

type NodeKind = Literal["p", "c"]


class Ids:
    """Derives the ids every stage agrees on, from content rather than from order."""

    _READ_CHUNK: ClassVar[int] = 1 << 20
    _DOC_ID_LEN: ClassVar[int] = 16

    @classmethod
    def document(cls, company: str, source_path: str | Path, extractor: str) -> str:
        """Stable hash of company, extractor and file content, so extractor variants coexist.

        Args:
            company: The company the document belongs to.
            source_path: The document itself.
            extractor: The extractor that will parse it.

        Returns:
            The document id.
        """
        digest = hashlib.sha256(f"{company.strip().lower()}:{extractor.strip().lower()}".encode())
        with Path(source_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(cls._READ_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()[: cls._DOC_ID_LEN]

    @staticmethod
    def node(doc_id: str, idx: int, kind: NodeKind) -> str:
        """Node id tagged with the kind that minted it.

        Parents are numbered by section and children by a running counter, so both
        sequences start at zero and would otherwise hand the same id to a parent and a
        child, leaving that child as its own parent.

        Args:
            doc_id: The document the node belongs to.
            idx: Position among nodes of that kind.
            kind: Whether the node is a parent or a child.

        Returns:
            The node id.
        """
        return f"{doc_id}:{kind}{idx}"

    @staticmethod
    def content(text: str) -> str:
        """Hash of a piece of text, for keying anything derived from it.

        Args:
            text: The text to hash.

        Returns:
            The hex digest.
        """
        return hashlib.sha256(text.encode()).hexdigest()
