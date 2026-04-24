"""LlamaIndex-compatible LLM that routes through the shared disk cache.

Overrides only ``achat`` — the async path used by ``QueryFusionRetriever``
(``use_async=True``) and ``LLMRerank.apostprocess_nodes``.

The sync ``chat`` is intentionally NOT overridden. If LlamaIndex ever calls
it from a sync code path, the parent ``LIOpenAI.chat`` will make a normal
(uncached) OpenAI call. This is safer than wrapping ``asyncio.run()``
inside a potentially-running event loop.
"""

from typing import Any, Sequence

from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.llms.openai import OpenAI as LIOpenAI

from peerdex.shared.llm import cached_completion


class CachedLIOpenAI(LIOpenAI):
    """Drop-in ``LIOpenAI`` replacement with transparent disk caching on the async path."""

    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        oai_msgs = [
            {
                "role": _role_str(m.role),
                "content": m.content or "",
            }
            for m in messages
        ]
        rsp = await cached_completion(
            model=self.model,
            messages=oai_msgs,
            temperature=self.temperature,
            seed=self.additional_kwargs.get("seed"),
        )
        text = rsp.choices[0].message.content or ""
        return ChatResponse(
            message=ChatMessage(role="assistant", content=text),
            raw=rsp.model_dump(),
        )


def _role_str(role: Any) -> str:
    """Extract role string from enum or plain str (LlamaIndex version-safe)."""
    return role.value if hasattr(role, "value") else str(role)
