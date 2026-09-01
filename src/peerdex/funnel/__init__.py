"""Evaluation funnel core: extractable -> +vlm -> retrieved -> answered, attributable per stage."""

from peerdex.funnel._corpus import BlockProjector, SearchableBlock
from peerdex.funnel._recall import (
    OracleValue,
    ParseRecall,
    QuestionRecall,
    RetrievalOutcome,
    RetrievalRecall,
    RetrievedPassage,
    ValueHit,
    ValueMatcher,
)
from peerdex.funnel._report import FunnelRow, StageDocument

__all__ = [
    "BlockProjector",
    "FunnelRow",
    "OracleValue",
    "ParseRecall",
    "QuestionRecall",
    "RetrievalOutcome",
    "RetrievalRecall",
    "RetrievedPassage",
    "SearchableBlock",
    "StageDocument",
    "ValueHit",
    "ValueMatcher",
]
