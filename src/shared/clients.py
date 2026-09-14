"""External client factories. Orchestrators construct clients here and inject."""

from functools import lru_cache

from openai import AsyncOpenAI


class Clients:
    """Builds the external clients, one per process."""

    @staticmethod
    @lru_cache(maxsize=1)
    def openai_async() -> AsyncOpenAI:
        """The shared async OpenAI client.

        Returns:
            The client.
        """
        return AsyncOpenAI()
