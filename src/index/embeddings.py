"""The embedding model, built once per process."""

from functools import lru_cache

from llama_index.embeddings.openai import OpenAIEmbedding

from shared.settings import get_settings


class Embeddings:
    """The embedding model every child row is vectorised with."""

    @staticmethod
    @lru_cache(maxsize=1)
    def model() -> OpenAIEmbedding:
        """The configured embedding model.

        Returns:
            The model named by ``embed.model``.
        """
        s = get_settings()
        return OpenAIEmbedding(model=s.embed.model, embed_batch_size=s.embed.batch_size)
