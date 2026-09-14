"""The inverted index over chunk text, which lexical search reads."""

from typing import Any, ClassVar

from index.tables import Tables
from shared.logging import Logging


class FtsIndex:
    """The inverted index over chunk text, which lexical search reads."""

    _LOG: ClassVar[Any] = Logging.get("index")

    @classmethod
    def ensure(cls, domain: str) -> None:
        """Build the full-text index over the chunk text unless the table already has one.

        LanceDB keeps this inverted index beside the rows, so lexical search needs no
        second copy of the corpus loaded and re-stemmed in memory per process.

        Args:
            domain: The domain whose table to index.
        """
        tbl = Tables.open(domain)
        if any(getattr(i, "index_type", "") == "FTS" for i in tbl.list_indices()):
            return
        tbl.create_fts_index("text", replace=True)
        cls._LOG.info("[index] built FTS index over text")
