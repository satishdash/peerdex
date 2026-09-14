"""Hierarchical parent-child chunker.

A table becomes a parent holding the whole table and children holding row groups.
Prose becomes a parent per packed section and children split from it. A figure
becomes a child alone, pointing at the parent of the section it sits in. Figures
are described by the vision model first, because a figure chunk's text is that
description.
"""

from collections import defaultdict
from typing import Any, ClassVar

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

from chunk.block_renderer import BlockRenderer
from chunk.debug_writer import DebugWriter
from chunk.node_accumulator import NodeAccumulator
from chunk.pending_node import PendingNode
from chunk.picture_descriptions import PictureDescriptions
from chunk.prose_chunker import ProseChunker
from chunk.section import Section
from chunk.section_grouper import SectionGrouper
from chunk.table_chunker import TableChunker
from chunk.tokenizer import Tokenizer
from parse import ExtractedDoc, ListBlock, ParagraphBlock, PictureBlock, TableBlock
from shared.document_metadata import DocumentMetadata
from shared.logging import Logging
from shared.settings import get_settings


class HierarchicalChunker:
    """Cuts an extracted document into the parent and child nodes the index stores."""

    _LOG: ClassVar[Any] = Logging.get("chunk")

    async def chunk(
        self,
        ed: ExtractedDoc,
        *,
        doc_id: str,
        metadata: DocumentMetadata,
    ) -> tuple[list[TextNode], list[TextNode]]:
        """Splits one extracted document into parent sections and the children beneath them.

        Args:
            ed: The parsed document.
            doc_id: The document's id, stamped on every node.
            metadata: Document-level metadata every node inherits.

        Returns:
            The parent nodes and the child nodes they own.
        """
        s = get_settings()
        parent_tokens: int = s.chunker.parent_chunk_tokens
        child_tokens: int = s.chunker.child_chunk_tokens
        splitter = SentenceSplitter(
            chunk_size=child_tokens,
            chunk_overlap=s.chunker.child_chunk_overlap,
            tokenizer=Tokenizer.encoding().encode,
        )

        sections: list[Section] = SectionGrouper.group(ed.blocks)
        figures: dict[int, list[PendingNode]] = self._descriptions(
            await self._described(sections, doc_id)
        )
        acc = NodeAccumulator(doc_id, metadata)

        for sec_idx, sec in enumerate(sections):
            acc.open_section()
            self._chunk_tables(sec, sec_idx, acc, child_tokens)
            self._chunk_prose(sec, sec_idx, acc, parent_tokens, splitter)
            self._chunk_figures(figures.get(sec_idx, []), acc)

        DebugWriter.write(doc_id, acc.children)
        self._LOG.info(
            f"[hierarchical-chunk] doc_id={doc_id} "
            f"parents={len(acc.parents)} children={len(acc.children)}"
        )
        return acc.parents, acc.children

    @staticmethod
    async def _described(sections: list[Section], doc_id: str) -> list[PendingNode]:
        """Describes every picture in the document in one batch, before any section is cut.

        Args:
            sections: The document's sections, in reading order.
            doc_id: The document being described.

        Returns:
            One pending node per described figure, empty when the document holds no pictures.
        """
        placed: list[tuple[int, PictureBlock]] = [
            (sec_idx, b)
            for sec_idx, sec in enumerate(sections)
            for b in sec.blocks
            if isinstance(b, PictureBlock)
        ]
        if not placed:
            return []
        return await PictureDescriptions.of(placed, doc_id=doc_id)

    @staticmethod
    def _descriptions(pending: list[PendingNode]) -> dict[int, list[PendingNode]]:
        """Groups described figures by the section they were found in.

        Args:
            pending: Every described figure, in reading order.

        Returns:
            The figures of each section, keyed by section index, in reading order.
        """
        grouped: dict[int, list[PendingNode]] = defaultdict(list)
        for pn in pending:
            grouped[pn.sec_idx].append(pn)
        return grouped

    @staticmethod
    def _chunk_tables(sec: Section, sec_idx: int, acc: NodeAccumulator, child_tokens: int) -> None:
        """Builds one atomic parent per table, split into row-group children.

        Args:
            sec: The section being chunked.
            sec_idx: Index of that section in the document.
            acc: Where the nodes are collected.
            child_tokens: Tokens a single row group may cost.
        """
        for tb in (b for b in sec.blocks if isinstance(b, TableBlock)):
            parent: TextNode = acc.parent(BlockRenderer.table(tb), sec, sec_idx, is_table=True)
            kids: list[TextNode] = [
                acc.child(text, sec, parent.node_id, is_table=True)
                for text in TableChunker.texts(tb, child_tokens)
            ]
            acc.keep(parent, kids)

    @staticmethod
    def _chunk_prose(
        sec: Section,
        sec_idx: int,
        acc: NodeAccumulator,
        parent_tokens: int,
        splitter: SentenceSplitter,
    ) -> None:
        """Builds one parent per packed prose chunk, split into sentence children.

        Args:
            sec: The section being chunked.
            sec_idx: Index of that section in the document.
            acc: Where the nodes are collected.
            parent_tokens: Tokens a single parent may cost.
            splitter: The sentence splitter that cuts a parent into children.
        """
        prose: list[ParagraphBlock | ListBlock] = [
            b for b in sec.blocks if isinstance(b, (ParagraphBlock, ListBlock))
        ]
        if not prose:
            return
        for text in ProseChunker.texts(sec.heading_path, prose, parent_tokens):
            parent: TextNode = acc.parent(text, sec, sec_idx)
            kids: list[TextNode] = [
                acc.child(ct, sec, parent.node_id) for ct in splitter.split_text(text) if ct.strip()
            ]
            acc.keep(parent, kids)

    @classmethod
    def _chunk_figures(cls, pending: list[PendingNode], acc: NodeAccumulator) -> None:
        """Builds one child per figure in this section; a figure owns no parent of its own.

        Args:
            pending: The figures found in this section.
            acc: Where the nodes are collected.
        """
        for pn in pending:
            cls._chunk_figure(pn, acc)

    @staticmethod
    def _chunk_figure(pn: PendingNode, acc: NodeAccumulator) -> None:
        """Builds one figure's child, pointing it at the parent of the section it sits in.

        Args:
            pn: The described figure.
            acc: Where the node is collected.
        """
        if not pn.text.strip():
            return
        acc.keep_child(acc.child(pn.text, pn.section, acc.section_parent_id, is_figure=True))
