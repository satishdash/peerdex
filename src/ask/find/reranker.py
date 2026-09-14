"""The port a reranker implements."""

from abc import ABC, abstractmethod
from typing import Any


class Reranker(ABC):
    """Strategy: how a shortlist is reordered before the top k is taken.

    Reranking costs no API call — it is local or arithmetic — so a reranker returns the
    engine-side reranker to apply within the one database call, or None to rank once.
    """

    @abstractmethod
    def engine(self) -> Any:
        """The reranker to hand the query builder.

        Returns:
            The engine-side reranker, or None when the ranking stands as it is.
        """
