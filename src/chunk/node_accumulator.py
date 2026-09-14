"""A document's nodes collected, with the ids that keep them in reading order."""

from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from chunk.node_factory import NodeFactory
from chunk.section import Section
from shared.document_metadata import DocumentMetadata
from shared.ids import Ids


class NodeAccumulator:
    """Collects a document's nodes, handing out the ids that keep them in reading order."""

    def __init__(self, doc_id: str, metadata: DocumentMetadata) -> None:
        """Start empty for one document.

        Args:
            doc_id: The document being chunked.
            metadata: Document-level metadata every node inherits.
        """
        self.parents: list[TextNode] = []
        self.children: list[TextNode] = []
        self._doc_id: str = doc_id
        self._metadata: DocumentMetadata = metadata
        self._parent_idx: int = 0
        self._child_idx: int = 0
        self._section_parent_id: str = ""

    @property
    def section_parent_id(self) -> str:
        """The parent a figure in the current section points at.

        Returns:
            The first parent built since the section opened, empty when it has none.
        """
        return self._section_parent_id

    def open_section(self) -> None:
        """Begin a section, so the next parent built becomes the one its figures point at."""
        self._section_parent_id = ""

    def parent(
        self,
        text: str,
        sec: Section,
        sec_idx: int,
        *,
        is_table: bool = False,
        is_figure: bool = False,
    ) -> TextNode:
        """One parent node, taking the next parent id.

        Args:
            text: The parent's text.
            sec: The section the parent covers.
            sec_idx: Index of that section in the document.
            is_table: Whether the parent is a whole table.
            is_figure: Whether the parent is a figure.

        Returns:
            The node, and the section's parent when it is the first one built.
        """
        node: TextNode = NodeFactory.create(
            Ids.node(self._doc_id, self._parent_idx, "p"),
            text,
            sec.heading_path,
            sec.page_no,
            self._doc_id,
            self._metadata,
            sec_idx,
            is_table=is_table,
            is_figure=is_figure,
            is_parent=True,
        )
        self._parent_idx += 1
        self._section_parent_id = self._section_parent_id or node.node_id
        return node

    def child(
        self,
        text: str,
        sec: Section,
        parent_id: str,
        *,
        is_table: bool = False,
        is_figure: bool = False,
    ) -> TextNode:
        """One child node, taking the next child id and pointing at the parent it belongs to.

        Args:
            text: The child's text.
            sec: Where the child sits, for its page and heading path.
            parent_id: The parent this child points at, empty when it has none.
            is_table: Whether the child came from a table.
            is_figure: Whether the child came from a figure.

        Returns:
            The node, its PARENT relationship set unless it has no parent at all.
        """
        node: TextNode = NodeFactory.create(
            Ids.node(self._doc_id, self._child_idx, "c"),
            text,
            sec.heading_path,
            sec.page_no,
            self._doc_id,
            self._metadata,
            self._child_idx,
            is_table=is_table,
            is_figure=is_figure,
            is_parent=False,
        )
        if parent_id:
            node.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(node_id=parent_id)
        self._child_idx += 1
        return node

    def keep(self, parent: TextNode, children: list[TextNode]) -> None:
        """Hold on to a parent and the children that point at it.

        Args:
            parent: The parent node.
            children: The children already pointing at it.
        """
        self.parents.append(parent)
        self.children.extend(children)

    def keep_child(self, child: TextNode) -> None:
        """Hold on to a child that owns no parent of its own, such as a figure.

        Args:
            child: The child node.
        """
        self.children.append(child)
