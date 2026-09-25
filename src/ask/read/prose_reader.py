"""Read, for a question asked as qualitative: prose over the passages found."""

from collections.abc import Sequence
from typing import Any, ClassVar

from ask.passage import Passage
from ask.question import Question
from shared.clients import Clients
from shared.document_prompts import DocumentPrompts
from shared.resilience import Resilience
from shared.settings import get_settings


class ProseReader:
    """Answers in prose, for the same question asked as qualitative.

    Route selects the answer's shape, not the question's meaning, so this reads the
    passages Find already returned rather than searching again.
    """

    _ROLE: ClassVar[str] = "system"

    @classmethod
    async def read(cls, question: Question, passages: Sequence[Passage]) -> str:
        """The prose answer the passages support.

        Args:
            question: The question being answered.
            passages: The passages Find returned, which are the only evidence.

        Returns:
            The prose, empty when Find returned nothing or the model said nothing.
        """
        if not passages:
            return ""

        @Resilience.light()
        async def call() -> str:
            return await cls._completion(question, passages)

        return await call()

    @classmethod
    async def _completion(cls, question: Question, passages: Sequence[Passage]) -> str:
        """The model's prose for this question.

        Args:
            question: The question being answered.
            passages: The passages the model may read.

        Returns:
            The reply, empty when the model returned nothing.
        """
        prompts = DocumentPrompts.current()
        response: Any = await Clients.openai_async().chat.completions.create(
            model=get_settings().llm.model,
            temperature=get_settings().llm.temperature,
            messages=[
                {"role": cls._ROLE, "content": prompts.prose_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question.text}\n\nPassages:\n{cls._evidence(passages)}"
                    ),
                },
            ],
        )
        return (response.choices[0].message.content or "").strip()

    @staticmethod
    def _evidence(passages: Sequence[Passage]) -> str:
        """The passages as the text the model reads.

        Args:
            passages: The passages Find returned.

        Returns:
            The passages, numbered so the model can be asked which one it used.
        """
        return "\n\n".join(f"[{n}] {p.text}" for n, p in enumerate(passages, 1))
