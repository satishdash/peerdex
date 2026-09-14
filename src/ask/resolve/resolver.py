"""Resolve: gates, units and combination, with no model involved."""

from collections.abc import Sequence
from typing import ClassVar

from ask.reading import Reading
from ask.resolution import Resolution
from ask.resolve.label_gate import LabelGate
from ask.resolve.number_gate import NumberGate
from ask.resolve.period_gate import PeriodGate
from quantity import ArithmeticQuestion, Derivation, DerivationEngine, Quantity, QuantityParser


class Resolver:
    """Decides what the readings amount to. Everything here is decidable without a model."""

    _NOTHING_READ: ClassVar[str] = "no value was read from the passages"

    @classmethod
    def resolve(cls, readings: Sequence[Reading], period: int | None, question: str) -> Resolution:
        """The answer the readings support, or a refusal carrying its reason.

        Args:
            readings: One figure, or one per operand when the question named arithmetic.
            period: The year the caller filtered on, or None when they named no year.
            question: The question, which is where any arithmetic was named.

        Returns:
            The resolution.
        """
        if not readings:
            return Resolution(refused=True, reason=cls._NOTHING_READ)
        refusal: str = cls._gated(readings, period)
        if refusal:
            return Resolution(refused=True, reason=refusal)
        return cls._settled(readings, question)

    @staticmethod
    def _gated(readings: Sequence[Reading], period: int | None) -> str:
        """The first gate any reading fails.

        An operand that failed a gate cannot be silently dropped from a total, so one
        failure refuses the whole answer.

        Args:
            readings: The figures to gate.
            period: The year the caller filtered on.

        Returns:
            The refusal reason, empty when every reading passes every gate.
        """
        for reading in readings:
            refusal: str = (
                LabelGate.check(reading)
                or PeriodGate.check(reading, period)
                or NumberGate.check(reading)
            )
            if refusal:
                return refusal
        return ""

    @classmethod
    def _settled(cls, readings: Sequence[Reading], question: str) -> Resolution:
        """The value that stands, combining operands when the question named arithmetic.

        If two dimensions will not combine, nothing is derived and the single extracted
        figure stands.

        Args:
            readings: The gated figures.
            question: The question, which is where any arithmetic was named.

        Returns:
            The resolution.
        """
        combined: Quantity | None = cls._combined(readings, question)
        if combined is None:
            return Resolution(value=readings[0].value, unit=readings[0].unit)
        return Resolution(value=combined.rendered, unit=readings[0].unit)

    @staticmethod
    def _combined(readings: Sequence[Reading], question: str) -> Quantity | None:
        """The operands combined as typed quantities, converting units before adding.

        Args:
            readings: The gated figures, one per operand.
            question: The question, which is where any arithmetic was named.

        Returns:
            The combined quantity, or None when the question named no arithmetic or the
            operands do not combine.
        """
        derivation: Derivation | None = ArithmeticQuestion().read(question)
        if derivation is None:
            return None
        parser = QuantityParser()
        parts = [parser.parse(r.value, r.unit) for r in readings]
        return DerivationEngine().combine(derivation, parts)
