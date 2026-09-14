"""Escalation: rewrite and search again, or fetch the parents by id."""

from ask.escalate.parent_fetch import ParentFetch
from ask.escalate.rewriter import Rewriter

__all__ = ["ParentFetch", "Rewriter"]
