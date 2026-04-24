"""Extractor-agnostic chunker.

Input:  ExtractedDoc + per-doc identity (company, year, report_type)
Output: list[llama_index.core.schema.TextNode]

Rules (these are the "convention" of the chunker, not extractor concerns):

  - HeadingBlock: never emitted standalone -- only used to drive the
    section grouping + heading_path metadata.
  - TableBlock: ATOMIC. One TextNode per table. No mid-table splits.
    Rendered as GFM table with caption above. Metadata is_table=True.
  - PictureBlock: passed through OpenAIPictureDescriber (async) -> if
    has_quant_data, one TextNode per picture, formatted to be BM25-
    searchable (label = value unit triples flattened). Metadata
    is_figure=True.
  - ParagraphBlock + ListBlock under the same heading_path on the
    same page: greedily merged into one TextNode until token budget
    (settings.chunker.max_tokens). On overflow, start a new node
    inheriting the same heading_path so context isn't lost.

GFM is the *render* format that goes into TextNode.text -- it's what
the embedder + LLM see. Storage format is still LlamaIndex nodes.

Debug sidecar: writes cache/chunks/<doc_id>.md with all emitted nodes
in order, separated by `---`. Pure side-effect, no pipeline dependency.
"""

import asyncio
from typing import Iterable

import tiktoken
from llama_index.core.schema import TextNode

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
from peerdex.shared.prompts import prompts_for
from peerdex.shared.schema import ReportType
from peerdex.shared.settings import get_settings
from peerdex.vlm import OpenAIPictureDescriber
from peerdex.vlm import PictureRef

log = get_logger("chunk")


# ---------- token counting ----------
def _enc():
    return tiktoken.get_encoding(get_settings().chunker.tokenizer)


def _tok(text: str) -> int:
    return len(_enc().encode(text))


# ---------- GFM rendering ----------
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
        # pad / truncate to header length
        row2 = list(row) + [""] * (len(headers) - len(row))
        row2 = row2[:len(headers)]
        lines.append("| " + " | ".join(_cell(c) for c in row2) + " |")
    return caption + "\n".join(lines)


def _cell(s: str) -> str:
    s = (s or "").replace("\n", " ").replace("|", "\\|").strip()
    return s or " "


def _render_picture_chunk_text(page_no: int, heading_path: list[str],
                               result: dict) -> str:
    """Mirrors the old PictureChunkBuilder format -- BM25-friendly."""
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


# ---------- chunker ----------
class Chunker:
    """Stateless. One instance per index_doc() call."""

    async def chunk(
        self,
        ed: ExtractedDoc,
        *,
        doc_id: str,
        company: str,
        year: int,
        report_type: ReportType | str,
        source_uri: str,
    ) -> list[TextNode]:
        s = get_settings()
        max_tokens = s.chunker.max_tokens
        prompts = prompts_for(report_type)

        # 1) Walk blocks. Tables / pictures emit immediately. Paragraphs +
        #    lists buffer per (heading_path, page_no) and flush on overflow,
        #    on heading change, on table/picture, or at end.
        emitted: list[_PendingNode] = []
        buf_blocks: list[ParagraphBlock | ListBlock] = []
        buf_heading: list[str] = []
        buf_page: int = 0

        def _flush():
            nonlocal buf_blocks
            if not buf_blocks:
                return
            text = _build_paragraph_chunk_text(buf_heading, buf_blocks, max_tokens)
            for chunk_text in text:
                emitted.append(_PendingNode(
                    text=chunk_text,
                    heading_path=list(buf_heading),
                    page_no=buf_page,
                    is_table=False,
                    is_figure=False,
                ))
            buf_blocks = []

        picture_blocks: list[PictureBlock] = []

        for b in ed.blocks:
            if isinstance(b, HeadingBlock):
                # Heading change forces a flush; heading itself is never a chunk.
                _flush()
                continue

            if isinstance(b, (ParagraphBlock, ListBlock)):
                if (b.heading_path != buf_heading) or (b.page_no != buf_page):
                    _flush()
                    buf_heading = list(b.heading_path)
                    buf_page = b.page_no
                buf_blocks.append(b)
                continue

            if isinstance(b, TableBlock):
                _flush()
                emitted.append(_PendingNode(
                    text=_render_table(b),
                    heading_path=list(b.heading_path),
                    page_no=b.page_no,
                    is_table=True,
                    is_figure=False,
                ))
                continue

            if isinstance(b, PictureBlock):
                _flush()
                picture_blocks.append(b)
                continue

        _flush()

        # 2) Run VLM on pictures (async, batched).
        if picture_blocks:
            pic_chunks = await _describe_pictures(
                picture_blocks, doc_id=doc_id, report_type=report_type,
            )
            emitted.extend(pic_chunks)

        # 3) Materialize TextNodes with full metadata.
        nodes: list[TextNode] = []
        for idx, p in enumerate(emitted):
            text = p.text
            if not text.strip():
                continue
            metadata = {
                "doc_id": doc_id,
                "company": company,
                "year": int(year),
                "report_type": str(report_type),
                "page_no": p.page_no,
                "heading_path": " > ".join(p.heading_path),
                "is_figure": p.is_figure,
                "is_table": p.is_table,
                "idx": idx,
                "extractor_name": ed.source_meta.get("extractor_name", ""),
                "extractor_version": ed.source_meta.get("extractor_version", ""),
                "prompt_version": prompts.prompt_version,
                "source_uri": source_uri,
            }
            nodes.append(TextNode(
                id_=node_id(doc_id, idx),
                text=text,
                metadata=metadata,
                excluded_embed_metadata_keys=[
                    "doc_id", "idx", "source_uri",
                    "extractor_name", "extractor_version", "prompt_version",
                ],
                excluded_llm_metadata_keys=[
                    "doc_id", "idx", "source_uri",
                    "extractor_name", "extractor_version", "prompt_version",
                ],
            ))

        # 4) Debug sidecar: cache/chunks/<doc_id>.md
        _write_debug_md(doc_id, nodes)

        log.info(
            f"[chunk] doc_id={doc_id} nodes={len(nodes)} "
            f"(tables={sum(1 for n in nodes if n.metadata['is_table'])} "
            f"figures={sum(1 for n in nodes if n.metadata['is_figure'])} "
            f"prose={sum(1 for n in nodes if not n.metadata['is_table'] and not n.metadata['is_figure'])})"
        )
        return nodes


# ---------- helpers ----------
class _PendingNode:
    __slots__ = ("text", "heading_path", "page_no", "is_table", "is_figure")

    def __init__(self, *, text: str, heading_path: list[str], page_no: int,
                 is_table: bool, is_figure: bool):
        self.text = text
        self.heading_path = heading_path
        self.page_no = page_no
        self.is_table = is_table
        self.is_figure = is_figure


def _build_paragraph_chunk_text(
    heading_path: list[str],
    blocks: list[ParagraphBlock | ListBlock],
    max_tokens: int,
) -> list[str]:
    """Greedy pack paragraphs/lists into chunks of <= max_tokens. Each
    chunk gets the same heading prefix so context survives splits."""
    prefix = _render_heading_prefix(heading_path)
    prefix_tok = _tok(prefix)
    out: list[str] = []
    cur: list[str] = []
    cur_tok = prefix_tok

    for b in blocks:
        rendered = _render_paragraph(b) if isinstance(b, ParagraphBlock) else _render_list(b)
        if not rendered:
            continue
        # +1 token for the joining newline.
        rt = _tok(rendered) + 1
        if cur and cur_tok + rt > max_tokens:
            out.append(prefix + "\n\n".join(cur))
            cur, cur_tok = [], prefix_tok
        cur.append(rendered)
        cur_tok += rt

    if cur:
        out.append(prefix + "\n\n".join(cur))
    return out


async def _describe_pictures(
    pictures: list[PictureBlock],
    *,
    doc_id: str,
    report_type: ReportType | str,
) -> list[_PendingNode]:
    refs = [
        PictureRef(
            page_no=p.page_no,
            heading_path=p.heading_path,
            pil_image=p.pil_image,
            bbox_area_pct=p.bbox_area_pct,
            self_ref=p.self_ref,
        )
        for p in pictures
    ]
    describer = OpenAIPictureDescriber(openai_async())
    results = await describer.describe(refs, report_type=report_type, doc_id=doc_id)

    out: list[_PendingNode] = []
    kept = quant_drop = call_drop = 0
    for ref, res in zip(refs, results):
        if res is None:
            call_drop += 1
            continue
        if not res.get("has_quant_data"):
            quant_drop += 1
            continue
        text = _render_picture_chunk_text(ref.page_no, ref.heading_path, res)
        if not text:
            quant_drop += 1
            continue
        out.append(_PendingNode(
            text=text,
            heading_path=ref.heading_path or ["Figures"],
            page_no=ref.page_no,
            is_table=False,
            is_figure=True,
        ))
        kept += 1
    log.info(
        f"[chunk] picture nodes kept={kept} "
        f"dropped(no_quant)={quant_drop} dropped(call_failed)={call_drop}"
    )
    return out


def _write_debug_md(doc_id: str, nodes: Iterable[TextNode]) -> None:
    fs, _root = fs_and_root()
    path = join_path("chunks", f"{doc_id}.md")
    fs.makedirs(join_path("chunks"), exist_ok=True)
    parts = []
    for n in nodes:
        m = n.metadata
        head = m.get("heading_path") or "root"
        flags = []
        if m.get("is_table"):
            flags.append("table")
        if m.get("is_figure"):
            flags.append("figure")
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        parts.append(
            f"<!-- node idx={m['idx']} page={m['page_no']} "
            f"heading={head!r}{flag_str} -->\n{n.text}\n"
        )
    with fs.open(path, "w") as f:
        f.write("\n---\n\n".join(parts))
