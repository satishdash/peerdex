"""Resolve: gates, units and combination, with no model involved."""

from ask.resolve.label_gate import LabelGate
from ask.resolve.number_gate import NumberGate
from ask.resolve.period_gate import PeriodGate
from ask.resolve.resolver import Resolver

__all__ = ["LabelGate", "NumberGate", "PeriodGate", "Resolver"]
