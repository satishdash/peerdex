"""Route: the answer's shape and the period, settled before anything is searched."""

from collections.abc import Mapping, Sequence
from typing import ClassVar

from ask.question import Question
from ask.route.routing import Routing
from shared.metadata import Scalar, Scalars


class Router:
    """Selects the answer's shape from the declared kind, and the period from the filters."""

    _YEAR: ClassVar[str] = "year"

    @classmethod
    def route(cls, question: Question) -> Routing:
        """Settle the answer's shape and the period it will be judged against.

        The caller declares the kind, so nothing is inferred and nothing is paid for.

        Args:
            question: The question as the caller asked it.

        Returns:
            The routing, its period taken from the year filter alone.
        """
        return Routing(kind=question.kind, period=cls._period(question.filters))

    @classmethod
    def _period(cls, filters: Mapping[str, Scalars]) -> int | None:
        """The one year the caller asked for, if they asked for exactly one.

        The asked-for period comes from the year filter, not from the question text,
        which usually contains no year. Two admitted years name no single period.

        Args:
            filters: The attribute filters the caller supplied.

        Returns:
            The period, or None when the caller named no single year.
        """
        admitted: list[Scalar] = cls._values(filters.get(cls._YEAR))
        if len(admitted) != 1:
            return None
        return cls._year(admitted[0])

    @staticmethod
    def _values(asked: Scalars | None) -> list[Scalar]:
        """The filter's values, whether one was given or several.

        Args:
            asked: The year filter's value, or None when it was not given.

        Returns:
            Every admitted value.
        """
        if asked is None:
            return []
        if isinstance(asked, str) or not isinstance(asked, Sequence):
            return [asked]
        return list(asked)

    @staticmethod
    def _year(value: Scalar) -> int | None:
        """One filter value as a year.

        Args:
            value: The admitted year, which may have arrived as text.

        Returns:
            The year, or None when the value does not state one.
        """
        try:
            return int(value)
        except TypeError, ValueError:
            return None
