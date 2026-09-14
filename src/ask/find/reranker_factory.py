"""The reranker a setting names."""

from typing import ClassVar

from ask.find.cross_encoder_reranker import CrossEncoderReranker
from ask.find.no_reranker import NoReranker
from ask.find.reranker import Reranker
from ask.find.rrf_reranker import RrfReranker


class RerankerFactory:
    """Builds the reranker the ``reranker`` setting names."""

    _BY_NAME: ClassVar[dict[str, type[Reranker]]] = {
        "none": NoReranker,
        "rrf": RrfReranker,
        "cross_encoder": CrossEncoderReranker,
    }

    @classmethod
    def for_name(cls, name: str) -> Reranker:
        """The reranker registered under this name.

        Args:
            name: The configured reranker.

        Returns:
            The reranker.

        Raises:
            ValueError: If nothing is registered under that name.
        """
        if name not in cls._BY_NAME:
            raise ValueError(f"unknown reranker '{name}'. available: {sorted(cls._BY_NAME)}")
        return cls._BY_NAME[name]()
