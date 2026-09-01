"""Hierarchical parent-child chunker.

Tables and figures are atomic (parent == child); prose is grouped by heading
section into parent nodes and split into child nodes, each linked to its
parent. Pictures are described asynchronously by the VLM first.
"""

from collections.abc import Iterable

import tiktoken
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from peerdex.parse import (
    ExtractedDoc,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    PictureBlock,
    TableBlock,
)
from peerdex.shared.cache import fs_and_root, join_path
from peerdex.shared.clients import openai_async
from peerdex.shared.ids import node_id
from peerdex.shared.logging import get_logger
from peerdex.shared.metadata import DocumentMetadata, MetadataVisibility, Scalar
from peerdex.shared.prompts import PROMPTS
from peerdex.shared.settings import get_settings
from peerdex.vlm import OpenAIPictureDescriber, PictureRef

log = get_logger("chunk")

_visibility = MetadataVisibility()


def _enc():
    return tiktoken.get_encoding(get_settings().chunker.tokenizer)


def _tok(text: str) -> int:
    return len(_enc().encode(text))


def _render_heading_prefix(heading_path: list[str]) -> str:
    if not heading_path:
        return ""
    return "## " + " > ".join(heading_path) + "\n\n"


def _render_paragraph(b: ParagraphBlock) -> str:
    return b.text.strip()


def _render_list(b: ListBlock) -> str:
    bullet = "1. " if b.ordered else "- "
    return "\n".join(f"{bullet}{item.strip()}" for item in b.items if item.strip())


def _render_table(b: TableBlock) -> str:
    caption = f"**{b.caption.strip()}**\n\n" if b.caption.strip() else ""
    if not b.rows:
        return caption.rstrip()
    headers = b.headers or [f"col{i}" for i in range(len(b.rows[0]))]
    sep = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(_cell(h) for h in headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in b.rows:
        row2 = [*row, *[""] * (len(headers) - len(row))][: len(headers)]
        lines.append("| " + " | ".join(_cell(c) for c in row2) + " |")
    return caption + "\n".join(lines)


def _cell(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("|", "\\|").strip()
    return s or " "


def _render_picture_chunk_text(page_no: int, heading_path: list[str], result: dict) -> str:
    """Renders a VLM description as a BM25-friendly figure chunk."""
    head = " > ".join(heading_path) or "root"
    title = result.get("title") or "Figure"
    desc = result.get("description") or ""
    values = result.get("values") or []
    val_line = ""
    if values:
        parts = []
        for v in values:
            label = v.get("label", "")
            value = v.get("value", "")
            unit = v.get("unit", "")
            if not (label or value):
                continue
            piece = f"{label} = {value}".strip(" =")
            if unit:
                piece += f" {unit}"
            parts.append(piece)
        if parts:
            val_line = "\nValues: " + "; ".join(parts)
    return f"[Figure p.{page_no} — {head}] {title}\n{desc}{val_line}".strip()


def _group_blocks_by_section(
    blocks: list,
) -> list[tuple[list[str], int, list]]:
    """Groups blocks into (heading_path, page_no, blocks) sections."""
    sections: list[tuple[list[str], int, list]] = []
    current_heading: list[str] = []
    current_page: int = 0
    current_blocks: list = []

    def _flush() -> None:
        if current_blocks:
            sections.append((list(current_heading), current_page, list(current_blocks)))

    for b in blocks:
        if isinstance(b, HeadingBlock):
            _flush()
            current_blocks = []
            current_heading = [*b.heading_path, b.text]
            current_page = getattr(b, "page_no", 0)
        else:
            current_blocks.append(b)

    _flush()
    return sections


def _make_node(
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
    metadata: dict[str, Scalar] = {
        "doc_id": doc_id,
        "company": doc_meta.company,
        "year": doc_meta.year,
        "page_no": page_no,
        "heading_path": " > ".join(heading_path),
        "is_figure": is_figure,
        "is_table": is_table,
        "is_parent": is_parent,
        "idx": idx,
        "source_uri": doc_meta.source_uri,
        "prompt_version": PROMPTS.prompt_version,
        "extractor": doc_meta.extractor,
        **doc_meta.attributes,
    }
    excluded: list[str] = _visibility.excluded(metadata)
    return TextNode(
        id_=node_id_,
        text=text,
        metadata=metadata,
        excluded_embed_metadata_keys=excluded,
        excluded_llm_metadata_keys=excluded,
    )


def _build_paragraph_chunk_text(
    heading_path: list[str],
    blocks: list[ParagraphBlock | ListBlock],
    max_tokens: int,
) -> list[str]:
    """Greedy-packs paragraphs/lists into GFM chunks of <= max_tokens with heading context."""
    out: list[str] = []
    buf_lines: list[str] = []
    buf_tok: int = 0

    prefix = _render_heading_prefix(heading_path)
    prefix_tok = _tok(prefix)

    for b in blocks:
        rendered = _render_paragraph(b) if isinstance(b, ParagraphBlock) else _render_list(b)
        tok = _tok(rendered)

        if buf_tok + tok + prefix_tok > max_tokens and buf_lines:
            out.append(prefix + "\n".join(buf_lines))
            buf_lines = []
            buf_tok = prefix_tok

        buf_lines.append(rendered)
        buf_tok += tok

    if buf_lines:
        out.append(prefix + "\n".join(buf_lines))

    return out


class _PendingNode:
    __slots__ = ("heading_path", "is_figure", "is_table", "page_no", "text")

    def __init__(
        self,
        text: str,
        heading_path: list[str],
        page_no: int,
        is_table: bool = False,
        is_figure: bool = False,
    ):
        self.text = text
        self.heading_path = heading_path
        self.page_no = page_no
        self.is_table = is_table
        self.is_figure = is_figure


async def _describe_pictures(
    pic_blocks: list[PictureBlock],
    doc_id: str,
) -> list[_PendingNode]:
    refs = [
        PictureRef(
            pil_image=pic.pil_image,
            page_no=pic.page_no,
            bbox_area_pct=pic.bbox_area_pct,
            heading_path=pic.heading_path,
            self_ref=pic.self_ref,
        )
        for pic in pic_blocks
    ]

    describer = OpenAIPictureDescriber(openai_async())
    results = await describer.describe(refs, doc_id=doc_id)

    out: list[_PendingNode] = []
    for pic, result in zip(pic_blocks, results, strict=True):
        if result:
            text = _render_picture_chunk_text(pic.page_no, pic.heading_path, result)
            out.append(
                _PendingNode(
                    text=text,
                    heading_path=list(pic.heading_path),
                    page_no=pic.page_no,
                    is_table=False,
                    is_figure=True,
                )
            )
    return out


def _write_debug_md(doc_id: str, nodes: Iterable[TextNode]) -> None:
    fs, _root = fs_and_root()
    debug_dir = join_path("cache", "chunks")
    if fs.exists(debug_dir):
        return
    fs.makedirs(debug_dir, exist_ok=True)

    path = join_path(debug_dir, f"{doc_id}.md")
    parts: list[str] = []
    for n in nodes:
        h = f"# {n.metadata.get('heading_path', 'root')}"
        meta_str = " | ".join(
            f"{k}={v}" for k, v in sorted(n.metadata.items()) if k not in ("heading_path",)
        )
        parts.append(f"{h} [{meta_str}]\n\n{n.text}")

    with fs.open(path, "w") as f:
        f.write("\n---\n\n".join(parts))


class HierarchicalChunker:
    """Metadata-aware parent-child chunker returning (parent_nodes, child_nodes).

    Parents are one node per heading section and stay out of the vector store;
    children are SentenceSplitter sub-chunks carrying a PARENT relationship.
    """

    async def chunk(
        self,
        ed: ExtractedDoc,
        *,
        doc_id: str,
        metadata: DocumentMetadata,
    ) -> tuple[list[TextNode], list[TextNode]]:
        s = get_settings()
        parent_tokens = s.chunker.parent_chunk_tokens
        child_tokens = s.chunker.child_chunk_tokens

        sections = _group_blocks_by_section(ed.blocks)

        all_pic_blocks = [b for _, _, blks in sections for b in blks if isinstance(b, PictureBlock)]
        pic_nodes: list[_PendingNode] = []
        if all_pic_blocks:
            pic_nodes = await _describe_pictures(all_pic_blocks, doc_id=doc_id)

        parent_nodes: list[TextNode] = []
        child_nodes: list[TextNode] = []
        pic_iter = iter(pic_nodes)
        child_idx = 0

        for sec_idx, (heading_path, page_no, blocks) in enumerate(sections):
            parent_id = node_id(doc_id, sec_idx * 10_000)

            table_blocks = [b for b in blocks if isinstance(b, TableBlock)]
            prose_blocks = [b for b in blocks if isinstance(b, (ParagraphBlock, ListBlock))]
            has_pictures = any(isinstance(b, PictureBlock) for b in blocks)

            for tb in table_blocks:
                table_text = _render_table(tb)
                p_node = _make_node(
                    parent_id,
                    table_text,
                    heading_path,
                    page_no,
                    doc_id,
                    metadata,
                    sec_idx,
                    is_table=True,
                    is_parent=True,
                )
                c_node = _make_node(
                    node_id(doc_id, child_idx),
                    table_text,
                    heading_path,
                    page_no,
                    doc_id,
                    metadata,
                    child_idx,
                    is_table=True,
                    is_parent=False,
                )
                c_node.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(node_id=parent_id)
                parent_nodes.append(p_node)
                child_nodes.append(c_node)
                child_idx += 1

            if prose_blocks:
                section_texts = _build_paragraph_chunk_text(
                    heading_path,
                    prose_blocks,
                    parent_tokens,
                )
                for part_idx, sec_text in enumerate(section_texts):
                    p_id = node_id(doc_id, sec_idx * 10_000 + part_idx + 1)
                    p_node = _make_node(
                        p_id,
                        sec_text,
                        heading_path,
                        page_no,
                        doc_id,
                        metadata,
                        sec_idx,
                        is_table=False,
                        is_parent=True,
                    )
                    parent_nodes.append(p_node)

                    splitter = SentenceSplitter(
                        chunk_size=child_tokens,
                        chunk_overlap=32,
                        tokenizer=_enc().encode,
                    )
                    for ct in splitter.split_text(sec_text):
                        if not ct.strip():
                            continue
                        c_node = _make_node(
                            node_id(doc_id, child_idx),
                            ct,
                            heading_path,
                            page_no,
                            doc_id,
                            metadata,
                            child_idx,
                            is_table=False,
                            is_parent=False,
                        )
                        c_node.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(
                            node_id=p_id
                        )
                        child_nodes.append(c_node)
                        child_idx += 1

            if has_pictures:
                for pn in pic_iter:
                    if not pn.text.strip():
                        continue
                    p_id = node_id(doc_id, sec_idx * 10_000 + 5_000)
                    p_node = _make_node(
                        p_id,
                        pn.text,
                        heading_path,
                        page_no,
                        doc_id,
                        metadata,
                        sec_idx,
                        is_figure=True,
                        is_parent=True,
                    )
                    c_node = _make_node(
                        node_id(doc_id, child_idx),
                        pn.text,
                        heading_path,
                        page_no,
                        doc_id,
                        metadata,
                        child_idx,
                        is_figure=True,
                        is_parent=False,
                    )
                    c_node.relationships[NodeRelationship.PARENT] = RelatedNodeInfo(node_id=p_id)
                    parent_nodes.append(p_node)
                    child_nodes.append(c_node)
                    child_idx += 1

        _write_debug_md(doc_id, child_nodes)
        log.info(
            f"[hierarchical-chunk] doc_id={doc_id} "
            f"parents={len(parent_nodes)} children={len(child_nodes)}"
        )
        return parent_nodes, child_nodes
