"""Answer-accuracy scoring: pure comparison of model answers to oracle values."""

from peerdex.scoring._scorer import (
    MAGNITUDES,
    AnswerScorer,
    Category,
    Comparison,
    NumericParser,
)

__all__ = ["MAGNITUDES", "AnswerScorer", "Category", "Comparison", "NumericParser"]
