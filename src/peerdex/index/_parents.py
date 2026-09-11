"""Parent nodes, stored in the database beside the children they belong to.

Parents used to live in a LlamaIndex ``SimpleDocumentStore``, which is one JSON
file per domain. That file is loaded whole and rewritten whole on every ingest,
so the cost of adding one document grew with the size of the corpus rather than
with the document: 33MB at 9,160 rows, read and written again for each PDF, and
tens of gigabytes at the scale this is built for.

Parents get their own table rather than a flag on the searchable one. Nothing
searches parents today, and putting unsearchable rows in the table that both
indexes are built over would mean every query filtering out rows it must never
return, plus a vector column with nothing to put in it.

The table is created on first use, so a new domain needs no migration.
"""

from collections.abc import Sequence
from typing import Any, Final

from llama_index.core.schema import BaseNode

import lancedb
from peerdex.shared.logging import get_logger
from peerdex.shared.settings import get_settings

log = get_logger("index.parents")

_SUFFIX: Final[str] = "_parents"


class ParentStore:
    """One domain's parent nodes, in ``<domain>_parents``."""

    def __init__(self, domain: str) -> None:
        self._domain: str = domain

    @property
    def table_name(self) -> str:
        """The table this domain's parents live in."""
        return f"{self._domain}{_SUFFIX}"

    def put(self, doc_id: str, nodes: Sequence[BaseNode]) -> int:
        """Replace one document's parents, returning how many were written.

        The delete comes first for the same reason it does for children: re-indexing
        a file replaces it, and a parent that outlives its document is an orphan.
        """
        from peerdex.index._index import doc_predicate

        if not nodes:
            return 0
        rows: list[dict[str, Any]] = [_row(node) for node in nodes]
        self._write(doc_predicate(doc_id), rows)
        log.info(f"[parents] stored {len(rows)} for doc_id={doc_id} in {self.table_name}")
        return len(rows)

    def _write(self, predicate: str, rows: list[dict[str, Any]]) -> None:
        """Create the table with these rows, or clear this document's and append them."""
        database = lancedb.connect(get_settings().storage.lancedb_uri)
        if self.table_name not in database.table_names():
            database.create_table(self.table_name, data=rows)
            return
        existing: Any = database.open_table(self.table_name)
        existing.delete(predicate)
        existing.add(rows)


def _row(node: BaseNode) -> dict[str, Any]:
    """One parent as a database row: its id, its text, and its metadata."""
    return {
        "id": node.node_id,
        "text": node.get_content(),
        "metadata": dict(node.metadata or {}),
    }
