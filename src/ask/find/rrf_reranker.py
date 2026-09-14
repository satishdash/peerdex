"""Reciprocal-rank fusion over the two lists hybrid search produces."""

from typing import Any

from lancedb.rerankers import RRFReranker as EngineRRF

from ask.find.reranker import Reranker


class RrfReranker(Reranker):
    """Merges two ranked lists by position, which is arithmetic and costs no call.

    It needs two lists, so the settings refuse it under a mode that ranks once.
    """

    def engine(self) -> Any:
        """The fusion to apply inside the database call.

        Returns:
            The engine's reciprocal-rank fusion reranker.
        """
        return EngineRRF()
