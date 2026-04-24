"""Cited, refusal-capable answer synthesis.

Contract:
  - Input: user query, list of reranked NodeWithScore, report type.
  - Output: CitedAnswer with verbatim quotes pinned to specific passages.
  - The model is instructed to refuse if the answer is not literally present
    in the supplied passages. Refusals are first-class, not a degenerate text
    response.

Implementation notes:
  - One JSON-mode chat completion (no streaming, no agent loop). Cheap and
    deterministic; the work has already been done by retrieval+rerank.
  - Per-report-type ``synthesis_rules`` are appended to a small generic
    rule set that handles citation format, quoting, and the refuse path.
  - Citations carry node_id + page so the CLI / UI can deep-link.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any

from llama_index.core.schema import NodeWithScore

from peerdex.shared.llm import cached_completion
from peerdex.shared.logging import get_logger
from peerdex.shared.prompts import prompts_for
from peerdex.shared.resilience import light_decorator
from peerdex.shared.schema import ReportType
from peerdex.shared.settings import get_settings

log = get_logger("synthesize")


# ---------- result types ----------

@dataclass
class Citation:
    n: int
    node_id: str
    company: str
    year: int
    page: int
    heading: str
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CitedAnswer:
    answer: str
    citations: list[Citation]
    refused: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "refused": self.refused,
            "reason": self.reason,
            "citations": [c.to_dict() for c in self.citations],
        }


# ---------- prompt building ----------

_SYS_TMPL = (
    "You are peerdex, a strict-citation answer engine over a {label}.\n"
    "RULES (non-negotiable):\n"
    "  1. Use ONLY information present in the numbered passages below. "
    "If the answer is not in those passages, refuse.\n"
    "  2. Every factual claim must be backed by an inline citation [#N] "
    "matching one of the supplied passages.\n"
    "  3. Quotes must be verbatim (preserve numbers, units, spacing, "
    "punctuation). Do not normalise '15 424' to '15,424'.\n"
    "  4. If multiple passages disagree, prefer the one closest to a "
    "primary table; mention the discrepancy.\n"
    "  5. Domain rules: {synthesis_rules}\n\n"
    "Return STRICT JSON with this schema:\n"
    "  {{\n"
    '    "refused": bool,                 // true => no grounded answer possible\n'
    '    "reason": str,                   // populated when refused=true\n'
    '    "answer": str,                   // the answer text with [#N] citations inline\n'
    '    "citations": [\n'
    '      {{ "n": int, "quote": str }}   // n must reference a passage shown below\n'
    "    ]\n"
    "  }}\n"
    "Never wrap the JSON in markdown fences."
)


def _format_passages(nodes: list[NodeWithScore]) -> tuple[str, list[NodeWithScore]]:
    """Number passages 1..N and emit a human-readable block. Returns the
    numbered block plus the same nodes in order so the caller can resolve
    citations back to node_ids/pages."""
    lines: list[str] = []
    for i, n in enumerate(nodes, start=1):
        m = n.node.metadata or {}
        head = m.get("heading_path") or "root"
        kind = "table" if m.get("is_table") else ("figure" if m.get("is_figure") else "prose")
        lines.append(
            f"[#{i}] {m.get('company','?')} {m.get('year','?')} "
            f"({m.get('report_type','?')}) p.{m.get('page_no','?')} "
            f"[{kind}] {head}\n"
            f"---\n{n.node.get_content().strip()}\n"
        )
    return "\n".join(lines), nodes


# ---------- main entry point ----------

@light_decorator()
async def synthesize(
    query: str,
    nodes: list[NodeWithScore],
    *,
    report_type: ReportType | str | None = None,
) -> CitedAnswer:
    prompts = prompts_for(report_type)

    if not nodes:
        return CitedAnswer(
            answer="",
            citations=[],
            refused=True,
            reason="no_passages_after_retrieval",
        )

    sys_msg = _SYS_TMPL.format(
        label=prompts.label,
        synthesis_rules=prompts.synthesis_rules,
    )
    passages_block, ordered = _format_passages(nodes)
    user_msg = (
        f"Question: {query}\n\n"
        f"Passages (use ONLY these):\n\n{passages_block}"
    )

    s = get_settings()
    rsp = await cached_completion(
        model=s.llm.synth_model or s.llm.model,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = rsp.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning(f"[synth] non-JSON response, refusing: {raw[:200]!r}")
        return CitedAnswer(
            answer="", citations=[], refused=True, reason="model_returned_invalid_json",
        )

    if data.get("refused"):
        return CitedAnswer(
            answer="", citations=[],
            refused=True, reason=str(data.get("reason") or "model_refused"),
        )

    answer = str(data.get("answer") or "").strip()
    citations: list[Citation] = []
    for c in data.get("citations") or []:
        try:
            n = int(c["n"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (1 <= n <= len(ordered)):
            continue
        node = ordered[n - 1].node
        m = node.metadata or {}
        citations.append(Citation(
            n=n,
            node_id=node.node_id,
            company=str(m.get("company", "")),
            year=int(m.get("year", 0) or 0),
            page=int(m.get("page_no", 0) or 0),
            heading=str(m.get("heading_path", "")),
            quote=str(c.get("quote") or "").strip(),
        ))

    if not answer or not citations:
        return CitedAnswer(
            answer=answer, citations=citations,
            refused=True,
            reason="no_grounded_citations" if not citations else "empty_answer",
        )

    return CitedAnswer(answer=answer, citations=citations, refused=False)
