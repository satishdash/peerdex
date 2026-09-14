"""Both of a table's indexes, kept built and covering every stored row."""

from typing import Any, ClassVar

from index.fts_index import FtsIndex
from index.tables import Tables
from index.vector_index import VectorIndex
from shared.logging import Logging


class TableIndexes:
    """Keeps both of a table's indexes built and covering every stored row."""

    _LOG: ClassVar[Any] = Logging.get("index")

    @classmethod
    def build(cls, domain: str) -> None:
        """Make every stored row searchable, building what is missing and folding in the rest.

        This is part of ingesting a document, not a step a caller can forget: embedding a
        chunk stores its vector, it does not put that row inside an index. A row outside
        the index is still answered, by scanning, which is the cost the index exists to
        remove.

        Args:
            domain: The domain whose table to index.
        """
        FtsIndex.ensure(domain)
        VectorIndex.ensure(domain)
        cls.refresh(domain)

    @classmethod
    def refresh(cls, domain: str) -> None:
        """Fold newly ingested rows into the indexes that already exist.

        Both indexes are built once and skipped afterwards, so without this every
        document after the first sits outside them. LanceDB answers such rows by
        scanning, which keeps results correct while the cost grows back to exactly
        what the index was built to avoid.

        Incremental by design: ``optimize`` folds the new rows in, where rebuilding
        from scratch costs minutes at production size and is what this replaced.

        Args:
            domain: The domain whose table to refresh.
        """
        tbl = Tables.open(domain)
        pending: int = cls._unindexed(tbl)
        if not pending:
            return
        tbl.optimize()
        cls._LOG.info(f"[index] folded {pending} new rows into the existing indexes")

    @staticmethod
    def _unindexed(tbl: Any) -> int:
        """The most rows any existing index does not yet cover.

        Args:
            tbl: The table to inspect.

        Returns:
            The largest uncovered row count across the table's indexes.
        """
        return max(
            (int(getattr(index, "num_unindexed_rows", 0) or 0) for index in tbl.list_indices()),
            default=0,
        )
