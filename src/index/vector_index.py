"""The approximate-nearest-neighbour index over the embedding column."""

import math
from typing import Any, ClassVar

from index.tables import Tables
from shared.logging import Logging
from shared.settings import get_settings


class VectorIndex:
    """The approximate-nearest-neighbour index over the embedding column."""

    _LOG: ClassVar[Any] = Logging.get("index")
    _QUANTISED: ClassVar[frozenset[str]] = frozenset(
        {"IVF_SQ", "IVF_PQ", "IVF_RQ", "IVF_HNSW_SQ", "IVF_HNSW_PQ"}
    )

    @classmethod
    def ensure(cls, domain: str) -> None:
        """Build the index unless the table already carries one of the configured type.

        Without it every dense query scans every row. That is milliseconds on a few
        thousand rows and seconds on a few million, so the index is what makes dense
        retrieval possible at production size rather than merely faster.

        The type comes from ``index.vector_type``. Changing that setting is enough:
        an index of a different type is replaced, so switching costs a rebuild and
        never a re-embedding or a data migration.

        Args:
            domain: The domain whose table to index.
        """
        tbl = Tables.open(domain)
        index_type: str = get_settings().index.vector_type
        existing: Any | None = cls._existing(tbl)
        if existing is not None and cls._same_type(str(existing.index_type), index_type):
            return
        rows: int = tbl.count_rows()
        partitions: int
        sub_vectors: int
        partitions, sub_vectors = cls._shape(rows, cls._dim(tbl))
        quantised: dict[str, int] = (
            {"num_sub_vectors": sub_vectors} if index_type in cls._QUANTISED else {}
        )
        tbl.create_index(
            metric="cosine",
            num_partitions=partitions,
            vector_column_name="vector",
            index_type=index_type,
            replace=True,
            **quantised,
        )
        cls._LOG.info(
            f"[index] built {index_type} over vector rows={rows} "
            f"partitions={partitions} sub_vectors={sub_vectors}"
        )

    @staticmethod
    def _shape(rows: int, dim: int) -> tuple[int, int]:
        """Partitions and sub-vectors, derived from the table's size.

        Partitions sit near the square root of the row count, the usual balance between
        how many centroids must be compared and how much of the table each one holds.
        Sub-vectors must divide the embedding dimension; 16 dimensions each keeps the
        quantisation error low enough to matter little at this scale.

        Deriving both from the data is the point: a hardcoded pair tuned on one corpus
        would be wrong for the next one.

        Args:
            rows: How many rows the table holds.
            dim: Width of the embedding column.

        Returns:
            The partition count and the sub-vector count.
        """
        partitions: int = max(1, min(4096, int(math.sqrt(rows))))
        return partitions, max(1, dim // 16)

    @staticmethod
    def _dim(tbl: Any) -> int:
        """Width of the embedding column, read from the table rather than assumed.

        Args:
            tbl: The table to measure.

        Returns:
            The embedding width.
        """
        field: Any = tbl.schema.field("vector")
        return int(field.type.list_size)

    @staticmethod
    def _existing(tbl: Any) -> Any | None:
        """The existing index over the vector column, or None.

        Selected by column rather than by type name, so the full-text index over
        ``text`` is never mistaken for it.

        Args:
            tbl: The table to inspect.

        Returns:
            The index, or None when the column carries none.
        """
        for index in tbl.list_indices():
            if "vector" in [str(column) for column in getattr(index, "columns", [])]:
                return index
        return None

    @staticmethod
    def _same_type(reported: str, configured: str) -> bool:
        """Whether LanceDB's own spelling of an index type is the configured one.

        LanceDB reports ``IvfPq`` where the setting says ``IVF_PQ``. Comparing the two
        verbatim is always false, which silently rebuilt the index on every ingest.

        Args:
            reported: The type as LanceDB spells it.
            configured: The type as the setting spells it.

        Returns:
            Whether they name the same type.
        """
        return reported.replace("_", "").lower() == configured.replace("_", "").lower()
