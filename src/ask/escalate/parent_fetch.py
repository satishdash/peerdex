"""Escalation when the passages were found but no value was read: fetch their parents."""

from collections.abc import Sequence

from ask.passage import Passage
from index import ParentRow, ParentStore


class ParentFetch:
    """Widens refused passages to the sections they came from, by id and without searching.

    A row group carries its caption and header but only its own rows, so a figure the
    question asks for may sit in the same section and never in the passage itself. The
    parent is the whole section, fetched by the id the passage already carries.
    """

    @classmethod
    def widen(cls, domain: str, passages: Sequence[Passage]) -> list[Passage]:
        """The parent sections behind these passages.

        Args:
            domain: The domain whose parent table holds them.
            passages: The passages that were found but yielded no value.

        Returns:
            One passage per parent that exists, in the order the ids were first seen.
        """
        if not passages:
            return []
        wanted: list[str] = cls._ids(passages)
        found: dict[str, ParentRow] = ParentStore(domain).get(wanted)
        return [cls._passage(found[pid]) for pid in wanted if pid in found]

    @staticmethod
    def _ids(passages: Sequence[Passage]) -> list[str]:
        """The parent ids these passages point at, each once and in order.

        Args:
            passages: The passages that were refused.

        Returns:
            The distinct parent ids, skipping passages that have no parent.
        """
        seen: dict[str, None] = {p.parent_id: None for p in passages if p.parent_id}
        return list(seen)

    @staticmethod
    def _passage(row: ParentRow) -> Passage:
        """One parent section as a passage the reader can take.

        Args:
            row: The parent as the store returned it.

        Returns:
            The passage, carrying no parent of its own.
        """
        return Passage(id=row.id, text=row.text, score=0.0, metadata=dict(row.metadata))
