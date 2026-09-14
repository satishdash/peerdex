"""Child nodes, embedded and written as the rows both indexes are built over.

The rows are written here rather than through a framework writer because the table
needs a column the writer cannot emit. ``parent_id`` is how the ask phase escalates
from a passage to the section it came from, so it is a column of its own, not a
metadata key: nothing outside the system knows a parent id, and metadata is what a
caller filters on.

Writing the rows also drops what the framework added and the design never asked
for: a second JSON copy of every node, and a column typed null.
"""

from collections.abc import Sequence
from typing import Any, ClassVar

import pyarrow as pa
from llama_index.core.schema import BaseNode, MetadataMode

import lancedb
from index.predicates import Predicates
from index.tables import Tables
from shared.logging import Logging
from shared.settings import get_settings


class ChildStore:
    """One domain's child nodes, in ``<domain>``: vector, text, parent_id, metadata."""

    _LOG: ClassVar[Any] = Logging.get("index.child_store")
    _NO_PARENT: ClassVar[str] = ""

    def __init__(self, domain: str) -> None:
        """Bind to one domain's table.

        Args:
            domain: The domain whose table these children belong to.
        """
        self._domain: str = domain

    @property
    def table_name(self) -> str:
        """The table this domain's children live in.

        Returns:
            The table name, which is the domain name.
        """
        return self._domain

    async def put(self, doc_id: str, nodes: Sequence[BaseNode], embed: Any) -> int:
        """Replace one document's children, returning how many were written.

        Args:
            doc_id: The document whose rows are being replaced.
            nodes: The child nodes to embed and write.
            embed: The embedding model, which decides the vector column's width.

        Returns:
            How many rows were written.
        """
        if not nodes:
            return 0
        vectors: list[list[float]] = await embed.aget_text_embedding_batch(
            [node.get_content(metadata_mode=MetadataMode.EMBED) for node in nodes],
            show_progress=True,
        )
        rows: list[dict[str, Any]] = [
            self._row(node, vector) for node, vector in zip(nodes, vectors, strict=True)
        ]
        self._write(Predicates.document(doc_id), self._arrow(rows))
        self._LOG.info(f"[children] stored {len(rows)} for doc_id={doc_id} in {self.table_name}")
        return len(rows)

    def _write(self, predicate: str, rows: pa.Table) -> None:
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
    def _arrow(rows: list[dict[str, Any]]) -> pa.Table:
        """The rows as an Arrow table whose vector column is fixed width.

        An inferred vector column is a variable-length list, which no vector index can be
        built over; the width is the embedding model's, so it is read off the first row.

        Args:
            rows: The rows to convert, at least one.

        Returns:
            The table, ready to create or append.
        """
        table: pa.Table = pa.Table.from_pylist(rows)
        position: int = table.schema.get_field_index("vector")
        width: int = len(rows[0]["vector"])
        fixed: pa.Field = table.schema.field(position).with_type(pa.list_(pa.float32(), width))
        return table.cast(table.schema.set(position, fixed))

    @classmethod
    def _row(cls, node: BaseNode, vector: list[float]) -> dict[str, Any]:
        """One child as a row: its id, its vector, its text, its parent and its metadata.

        Args:
            node: The child node.
            vector: The embedding of that node.

        Returns:
            The row, its ``parent_id`` empty when the node has no parent.
        """
        parent = node.parent_node
        return {
            "id": node.node_id,
            "vector": vector,
            "text": node.get_content(metadata_mode=MetadataMode.NONE),
            "parent_id": parent.node_id if parent else cls._NO_PARENT,
            "metadata": dict(node.metadata or {}),
        }
