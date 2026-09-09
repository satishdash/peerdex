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
    "  6. Never guess, never compute, never combine figures.\n\n"
    'Return STRICT JSON: {{"value": "...", "unit": "...", "label": "..."}}'
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
        return self._parse(response.message.content or "")

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
