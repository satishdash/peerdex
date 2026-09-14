"""TextNodes built with the document metadata every downstream stage filters on."""

from typing import ClassVar

from llama_index.core.schema import TextNode

from shared.document_metadata import DocumentMetadata
from shared.document_prompts import DocumentPrompts
from shared.metadata import Scalar
from shared.metadata_visibility import MetadataVisibility


class NodeFactory:
    """Builds a TextNode carrying the document metadata every downstream stage filters on."""

    _VISIBILITY: ClassVar[MetadataVisibility] = MetadataVisibility()

    @classmethod
    def create(
        cls,
        node_id_: str,
        text: str,
        heading_path: list[str],
        page_no: int,
        doc_id: str,
        doc_meta: DocumentMetadata,
        idx: int,
        *,
        is_table: bool = False,
        is_figure: bool = False,
        is_parent: bool = False,
    ) -> TextNode:
        """One node, with the metadata the retriever and the synthesiser both read.

        Args:
            node_id_: The node's own id.
            text: The chunk text.
            heading_path: The ancestor headings, outermost first.
            page_no: The page the chunk came from.
            doc_id: The document the chunk belongs to.
            doc_meta: Document-level metadata every node inherits.
            idx: Position of the node among its own kind.
            is_table: Whether the chunk came from a table.
            is_figure: Whether the chunk came from a figure.
            is_parent: Whether the node is a parent rather than a child.

        Returns:
            The node, its non-visible metadata keys already excluded.
        """
        metadata: dict[str, Scalar] = {
            "source_doc_id": doc_id,
            "company": doc_meta.company,
            "year": doc_meta.year,
            "page_no": page_no,
            "heading_path": " > ".join(heading_path),
            "is_figure": is_figure,
            "is_table": is_table,
            "is_parent": is_parent,
            "idx": idx,
            "source_uri": doc_meta.source_uri,
            "prompt_version": DocumentPrompts.current().prompt_version,
            "extractor": doc_meta.extractor,
            **doc_meta.attributes,
        }
        excluded: list[str] = cls._VISIBILITY.excluded(metadata)
        return TextNode(
            id_=node_id_,
            text=text,
            metadata=metadata,
            excluded_embed_metadata_keys=excluded,
            excluded_llm_metadata_keys=excluded,
        )
