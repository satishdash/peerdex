"""External client factories. Orchestrators construct clients here and inject."""

from functools import lru_cache

from openai import AsyncOpenAI


@lru_cache(maxsize=1)
def openai_async() -> AsyncOpenAI:
    return AsyncOpenAI()
