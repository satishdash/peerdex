"""LLM answer step: extract the single asked-for figure from passages, or nothing."""

import json
import re
from collections.abc import Sequence
from typing import Any

from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.schema import NodeWithScore

from peerdex.agent._agent import Extraction, Plan
from peerdex.shared.llm_llama import CachedLIOpenAI
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger("agent.extract")

_JSON_OBJECT: re.Pattern[str] = re.compile(r"\{.*\}", re.DOTALL)
_COLUMN_PERIOD: re.Pattern[str] = re.compile(r"\b(?:19|20)\d{2}\b")

_PROMPT: str = (
    "You extract ONE numeric figure from report passages.\n"
    "Question: {question}\n"
    "Qualifiers: period={period} scope={scope} unit={unit}\n\n"
    "Passages:\n{passages}\n\n"
    "Rules:\n"
    '  1. Use ONLY the passages. If they do not state the exact figure asked for, value is "".\n'
    "  2. value is the bare number exactly as printed (digits, separators, sign) - "
    "no unit, no words.\n"
    '  3. unit is the unit printed next to the number, or "".\n'
    "  4. label is the row or line label printed beside that number, copied exactly as "
    "printed.\n"
    "  5. If you cannot name that label, the passages do not state the figure asked for: "
    'return value "" and label "".\n'
    "  6. column is the column header printed above that number, copied exactly as "
    'printed, or "" when the number sits in no column.\n'
    "  7. When a period is given above, the column you read must be that period. "
    "A table usually prints several periods side by side, and any other column is a "
    'different figure: return value "" rather than the wrong period.\n'
    "  8. Never guess, never compute, never combine figures.\n\n"
    'Return STRICT JSON: {{"value": "...", "unit": "...", "label": "...", "column": "..."}}'
)


class LLMQuantitativeExtractor:
    """One deterministic LLM call that returns the figure and its unit, or empty strings."""

    def __init__(self, llm: CachedLIOpenAI | None = None) -> None:
        settings = get_settings()
        self._llm: CachedLIOpenAI = llm or CachedLIOpenAI(
            model=settings.llm.synth_model or settings.llm.model,
            temperature=0.0,
            additional_kwargs={"seed": 7},
        )

    async def extract(
        self, question: str, plan: Plan, nodes: Sequence[NodeWithScore]
    ) -> Extraction:
        """Ask the LLM for the figure; empty strings when the passages do not state it."""
        prompt: str = self._prompt(question, plan, nodes)
        response = await self._llm.achat([ChatMessage(role="user", content=prompt)])
        return self._in_period(self._parse(response.message.content or ""), plan.period)

    @staticmethod
    def _in_period(extraction: Extraction, period: str) -> Extraction:
        """A figure read from some *other* period's column is not the figure asked for.

        The prompt already asks for the right column; this refuses the answer when it
        came back naming the wrong one, which is how `298,498` from a `Baseline 2015`
        column was once returned for a 2025 question under a correct row label.

        Only a column that states a period is judged. Plenty of tables break a figure
        down by something else entirely - a `Female` column holding a board count -
        and demanding a period of those columns cost two correct answers when measured.
        """
        if not period or not extraction.column:
            return extraction
        stated: list[str] = _COLUMN_PERIOD.findall(extraction.column)
        if not stated or period in stated:
            return extraction
        log.info(f"[extract] refused: column {extraction.column!r} is not period {period!r}")
        return Extraction(value="", unit="", label="", column="")

    @staticmethod
    def _prompt(question: str, plan: Plan, nodes: Sequence[NodeWithScore]) -> str:
        passages: str = "\n\n".join(
            f"[#{index}] {node.node.get_content()}" for index, node in enumerate(nodes, 1)
        )
        return _PROMPT.format(
            question=question,
            period=plan.period,
            scope=plan.scope,
            unit=plan.unit,
            passages=passages,
        )

    @classmethod
    def _parse(cls, content: str) -> Extraction:
        payload: Any = cls._payload(content)
        if not isinstance(payload, dict):
            return Extraction(value="", unit="", label="")
        label: str = str(payload.get("label") or "").strip()
        if not label:
            return Extraction(value="", unit="", label="")
        return Extraction(
            value=str(payload.get("value") or "").strip(),
            unit=str(payload.get("unit") or "").strip(),
            label=label,
            column=str(payload.get("column") or "").strip(),
        )

    @staticmethod
    def _payload(content: str) -> Any:
        match: re.Match[str] | None = _JSON_OBJECT.search(content)
        if match is None:
            return None
        try:
            return json.loads(match[0])
        except json.JSONDecodeError:
            return None
