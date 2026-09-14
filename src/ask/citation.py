"""One chunk an answer was read from."""

from dataclasses import dataclass
from typing import Any

from ask.passage import Passage


@dataclass(frozen=True, slots=True)
class Citation:
    """Where one piece of an answer came from: one chunk, on one page of one document."""

    chunk_id: str
    company: str
    year: int
    page_no: int
    heading_path: str
    source_doc_id: str

    @classmethod
    def of(cls, passage: Passage) -> Citation:
        """The citation for one passage.

        Args:
            passage: The passage the answer was read from.

        Returns:
            The citation, its fields empty or zero where the chunk carries none.
        """
        meta: dict[str, Any] = passage.metadata
        return cls(
            chunk_id=passage.id,
            company=str(meta.get("company") or ""),
            year=int(meta.get("year") or 0),
            page_no=int(meta.get("page_no") or 0),
            heading_path=str(meta.get("heading_path") or ""),
            source_doc_id=str(meta.get("source_doc_id") or ""),
        )
