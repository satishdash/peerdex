"""Rank once and stop."""

from typing import Any

from ask.find.reranker import Reranker


class NoReranker(Reranker):
    """Leaves the search's own ranking alone."""

    def engine(self) -> Any:
        """Nothing to apply.

        Returns:
            None, so the query keeps the ranking the mode produced.
        """
        return None
