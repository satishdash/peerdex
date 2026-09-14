"""Answer-accuracy scoring: pure comparison of model answers to oracle values."""

from scoring.answer_scorer import AnswerScorer
from scoring.comparison import Category, Comparison

__all__ = ["AnswerScorer", "Category", "Comparison"]
