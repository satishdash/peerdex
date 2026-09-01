"""Funnel report core: read stage JSON documents and build per-extractor funnel rows."""

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Self


class StageDocument:
    """One stage's JSON output for one extractor."""

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self._payload: Mapping[str, Any] = payload

    @property
    def stage(self) -> int:
        return int(self._payload.get("stage", -1))

    @property
    def extractor(self) -> str:
        return str(self._payload.get("extractor", ""))

    @property
    def summary(self) -> dict[str, Any]:
        return dict(self._payload.get("summary") or {})

    def reachable_questions(self) -> set[str]:
        """Questions whose value was found (exact or scaled)."""
        return {str(q["question"]) for q in self._questions() if q.get("status") != "miss"}

    def pages_for(self, question: str) -> list[int]:
        """Sorted unique pages where the question's value was recorded."""
        hits: list[dict[str, Any]] = next(
            (list(q.get("hits") or []) for q in self._questions() if q.get("question") == question),
            [],
        )
        return sorted({int(hit["page_no"]) for hit in hits})

    def summary_value(self, key: str) -> int | None:
        value: Any = self.summary.get(key)
        return None if value is None else int(value)

    def _questions(self) -> list[dict[str, Any]]:
        return list(self._payload.get("questions") or [])


@dataclass(frozen=True)
class FunnelRow:
    """Counts per funnel stage for one extractor, with the drop at each step."""

    extractor: str
    stages: list[int | None]
    drops: list[int | None]

    @classmethod
    def build(
        cls,
        extractor: str,
        stage0: Mapping[str, Any] | None,
        stage1: Mapping[str, Any] | None,
        stage2: Mapping[str, Any] | None,
        stage3: Mapping[str, Any] | None,
    ) -> Self:
        """extractable -> +vlm -> retrieved -> answered from the four stage summaries."""
        stages: list[int | None] = [
            cls._value(stage0, "reachable"),
            cls._value(stage1, "reachable"),
            cls._value(stage2, "hit"),
            cls._value(stage3, "match"),
        ]
        drops: list[int | None] = [None, *(cls._drop(prev, cur) for prev, cur in pairwise(stages))]
        return cls(extractor=extractor, stages=stages, drops=drops)

    @staticmethod
    def _value(summary: Mapping[str, Any] | None, key: str) -> int | None:
        return None if summary is None or summary.get(key) is None else int(summary[key])

    @staticmethod
    def _drop(previous: int | None, current: int | None) -> int | None:
        return None if previous is None or current is None else current - previous
