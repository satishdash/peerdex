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
from typing import Any, ClassVar

from llama_index.core.schema import BaseNode

import lancedb
from index.parent_row import ParentRow
from index.predicates import Predicates
from index.tables import Tables
from shared.logging import Logging
from shared.settings import get_settings


class ParentStore:
    """One domain's parent nodes, in ``<domain>_parents``."""

    _LOG: ClassVar[Any] = Logging.get("index.parent_store")
    _SUFFIX: ClassVar[str] = "_parents"

    def __init__(self, domain: str) -> None:
        """Bind to one domain's parent table.

        Args:
            domain: The domain whose parents these are.
        """
        self._domain: str = domain

    @property
    def table_name(self) -> str:
        """The table this domain's parents live in.

        Returns:
            The domain name with the parent suffix.
        """
        return f"{self._domain}{self._SUFFIX}"

    def get(self, parent_ids: Sequence[str]) -> dict[str, ParentRow]:
        """The parents behind these ids, for the escalation that reads them.

        Parents are never searched, only fetched, so this is a lookup by primary key.
        An id that is absent is simply not in the result: a figure sitting in a section
        with no parent carries an empty id, and a domain ingested before parents existed
        has no table at all.

        Args:
            parent_ids: The ids carried by the passages that were refused.

        Returns:
            One entry per id that exists, keyed by id.
        """
        wanted: list[str] = [p for p in parent_ids if p]
        if not wanted:
            return {}
        rows: list[dict[str, Any]] = self._rows(wanted)
        return {
            r["id"]: ParentRow(id=r["id"], text=r["text"], metadata=dict(r["metadata"]))
            for r in rows
        }

    def put(self, doc_id: str, nodes: Sequence[BaseNode]) -> int:
        """Replace one document's parents.

        The delete comes first for the same reason it does for children: re-indexing
        a file replaces it, and a parent that outlives its document is an orphan.

        Args:
            doc_id: The document whose parents are being replaced.
            nodes: The parent nodes to write.

        Returns:
            How many rows were written.
        """
        if not nodes:
            return 0
        rows: list[dict[str, Any]] = [self._row(node) for node in nodes]
        self._write(Predicates.document(doc_id), rows)
        self._LOG.info(f"[parents] stored {len(rows)} for doc_id={doc_id} in {self.table_name}")
        return len(rows)

    def _rows(self, parent_ids: list[str]) -> list[dict[str, Any]]:
        """The stored rows for these ids, empty when the domain has no parent table yet.

        Args:
            parent_ids: The ids to look up, none of them empty.

        Returns:
            The matching rows.
        """
        database = lancedb.connect(get_settings().storage.lancedb_uri)
        if not Tables.exists(database, self.table_name):
            return []
        table: Any = database.open_table(self.table_name)
        quoted: str = ", ".join(f"'{p.replace(chr(39), chr(39) * 2)}'" for p in parent_ids)
        return table.search().where(f"id IN ({quoted})").limit(len(parent_ids)).to_list()

    def _write(self, predicate: str, rows: list[dict[str, Any]]) -> None:
        """Create the table with these rows, or clear this document's and append them.

        Args:
            predicate: Selects the rows this document already has.
            rows: The rows to write.
        """
        database = lancedb.connect(get_settings().storage.lancedb_uri)
        if not Tables.exists(database, self.table_name):
            database.create_table(self.table_name, data=rows)
            return
        existing: Any = database.open_table(self.table_name)
        existing.delete(predicate)
        existing.add(rows)

    @staticmethod
    def _row(node: BaseNode) -> dict[str, Any]:
        """One parent as a database row: its id, its text, and its metadata.

        Args:
            node: The parent node.

        Returns:
            The row, carrying no vector because parents are never searched.
        """
        return {
            "id": node.node_id,
            "text": node.get_content(),
            "metadata": dict(node.metadata or {}),
        }
