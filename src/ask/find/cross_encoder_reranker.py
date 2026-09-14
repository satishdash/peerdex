"""A cross-encoder re-reading the question and each passage together."""

from typing import Any

from lancedb.rerankers import CrossEncoderReranker as EngineCrossEncoder

from ask.find.reranker import Reranker
from shared.settings import get_settings


class CrossEncoderReranker(Reranker):
    """Scores the question and a passage as a pair, rather than ranking them apart.

    It reads both texts together, which is why it works over one ranked list or two,
    and why it can only run over a shortlist. The model runs locally, so reranking
    still costs no API call. Which model is a setting, never a literal.
    """

    def engine(self) -> Any:
        """The cross-encoder to apply inside the database call.

        Returns:
            The engine's cross-encoder, bound to the configured model.
        """
        return EngineCrossEncoder(model_name=get_settings().retrieval.reranker_model)
