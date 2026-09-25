"""Read: one call returns the value and the evidence for it."""

import json
from collections.abc import Sequence
from typing import Any, ClassVar

from ask.passage import Passage
from ask.question import Question
from ask.reading import Reading
from quantity import ArithmeticQuestion, Derivation
from shared.clients import Clients
from shared.document_prompts import DocumentPrompts
from shared.logging import Logging
from shared.resilience import Resilience
from shared.settings import get_settings


class Reader:
    """Extracts one figure per question, or one per operand when the question names arithmetic.

    Where the question names arithmetic, each operand is extracted separately from the
    passages already in hand. That costs one call per operand and no further search.
    """

    _LOG: ClassVar[Any] = Logging.get("ask.read")
    _FIELDS: ClassVar[tuple[str, ...]] = ("value", "unit", "label", "column")

    @classmethod
    async def read(cls, question: Question, passages: Sequence[Passage]) -> list[Reading]:
        """The figure the question asks for, read out of the passages.

        Args:
            question: The question being answered.
            passages: The passages Find returned, which are the only evidence.

        Returns:
            One reading, or one per operand when the question names arithmetic, and
            nothing at all when Find returned nothing.
        """
        if not passages:
            return []
        evidence: str = cls._evidence(passages)
        derivation: Derivation | None = ArithmeticQuestion().read(question.text)
        if derivation is None:
            return [await cls._one(question.text, evidence)]
        return [await cls._one(operand, evidence) for operand in derivation.operands]

    @classmethod
    async def _one(cls, asked: str, evidence: str) -> Reading:
        """One figure, read in a single call.

        Args:
            asked: The question, or the operand being extracted.
            evidence: The passages the model may read.

        Returns:
            The reading, its fields empty when the passages do not state the figure.
        """

        @Resilience.light()
        async def call() -> str:
            return await cls._completion(asked, evidence)

        return cls._parsed(await call())

    @classmethod
    async def _completion(cls, asked: str, evidence: str) -> str:
        """The model's reply for one figure.

        Args:
            asked: The question, or the operand being extracted.
            evidence: The passages the model may read.

        Returns:
            The raw JSON body.
        """
        response: Any = await Clients.openai_async().chat.completions.create(
            model=get_settings().llm.model,
            temperature=get_settings().llm.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": DocumentPrompts.current().read_prompt},
                {"role": "user", "content": f"Question: {asked}\n\nPassages:\n{evidence}"},
            ],
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _evidence(passages: Sequence[Passage]) -> str:
        """The passages as the text the model reads.

        Args:
            passages: The passages Find returned.

        Returns:
            The passages, numbered so the model can be asked which one it read.
        """
        return "\n\n".join(f"[{n}] {p.text}" for n, p in enumerate(passages, 1))

    @classmethod
    def _parsed(cls, raw: str) -> Reading:
        """The model's reply, coerced to the shape the next stage gates on.

        Args:
            raw: The raw JSON body.

        Returns:
            The reading, every field present even when the model omitted it.
        """
        data: dict[str, Any] = cls._json(raw)
        fields: dict[str, str] = {f: str(data.get(f) or "").strip() for f in cls._FIELDS}
        return Reading(**fields)

    @classmethod
    def _json(cls, raw: str) -> dict[str, Any]:
        """The reply as an object, empty when it is not one.

        Args:
            raw: The raw JSON body.

        Returns:
            The decoded object, or an empty one when the model did not answer in shape.
        """
        try:
            data: Any = json.loads(raw or "{}")
        except ValueError as exc:
            cls._LOG.info(f"[read] reply was not JSON, reading empty: {exc}")
            return {}
        return data if isinstance(data, dict) else {}
