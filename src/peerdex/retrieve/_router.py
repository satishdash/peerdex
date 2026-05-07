"""Question-topic router (static triggers + LLM fallback).

For each report type, ``ReportPrompts.topics`` declares canonical
question topics and where their answers structurally live (heading
patterns, common keywords, "lives in a table"). The router does TWO
cheap things on a topic hit:

  1. Builds an *augmented query* (question + canonical keywords) so
     the dense + BM25 retrievers get a second pass that surfaces the
     actual document phrasing. Recall fix.

  2. Adds a small additive boost to fusion candidates whose
     ``heading_path`` substring-matches the route's heading patterns,
     whose text contains any keyword, or whose ``is_table=True``
     matches ``prefer_table``. Precision nudge.

Two-tier matching:
  - **Static**: substring scan of trigger keywords (0ms, $0).
  - **LLM fallback**: if static misses, one cheap gpt-5.4-nano call
    classifies the query into a known route or "none" (~$0.00001,
    ~300ms). Catches paraphrases that static triggers miss.

Boosts are intentionally soft. The LLM reranker still casts the final
vote with its score threshold, so a wrong route can't smuggle a bad
passage past rerank.
"""

from dataclasses import dataclass

from llama_index.core.schema import NodeWithScore

from peerdex.shared.llm import cached_completion
from peerdex.shared.logging import get_logger
from peerdex.shared.prompts import ReportPrompts, TopicRoute, prompts_for
from peerdex.shared.schema import ReportType
from peerdex.shared.settings import get_settings

log = get_logger("router")


@dataclass
class RouteHit:
    route: TopicRoute
    augmented_query: str
    report_type: ReportType


def _static_match(query: str) -> RouteHit | None:
    """Try all report types' topics via substring triggers; return the first hit."""
    q = query.lower()
    for rt in ReportType:
        prompts = prompts_for(rt)
        for route in prompts.topics:
            if any(t.lower() in q for t in route.triggers):
                extras = " ".join(route.keywords)
                return RouteHit(
                    route=route,
                    augmented_query=f"{query} {extras}".strip(),
                    report_type=rt,
                )
    return None


def _build_route_index() -> dict[str, tuple[TopicRoute, ReportType]]:
    """Build a lookup from route name → (TopicRoute, ReportType)."""
    index: dict[str, tuple[TopicRoute, ReportType]] = {}
    for rt in ReportType:
        prompts = prompts_for(rt)
        for route in prompts.topics:
            index[route.name] = (route, rt)
    return index


_ROUTE_INDEX: dict[str, tuple[TopicRoute, ReportType]] | None = None


def _get_route_index() -> dict[str, tuple[TopicRoute, ReportType]]:
    global _ROUTE_INDEX
    if _ROUTE_INDEX is None:
        _ROUTE_INDEX = _build_route_index()
    return _ROUTE_INDEX


def _classify_prompt(query: str) -> list[dict[str, str]]:
    """Build the classification prompt for the LLM fallback."""
    route_index = _get_route_index()
    route_list = "\n".join(f"- {name}" for name in sorted(route_index))
    return [
        {
            "role": "system",
            "content": (
                "You are a query classifier for a document retrieval system. "
                "Given a user question, classify it into one of the known "
                "metric topics below, or reply 'none' if it doesn't match any.\n\n"
                f"Known topics:\n{route_list}\n\n"
                "Reply with ONLY the topic name (e.g. 'employees') or 'none'. "
                "No explanation."
            ),
        },
        {"role": "user", "content": query},
    ]


async def _llm_classify(query: str) -> RouteHit | None:
    """Use a cheap LLM call to classify the query into a known route."""
    s = get_settings()
    model = s.llm.router_model or s.llm.model
    messages = _classify_prompt(query)

    try:
        rsp = await cached_completion(
            model=model,
            messages=messages,
            temperature=0.0,
            seed=7,
        )
        resp = rsp.choices[0].message.content or ""
    except Exception:
        log.warning("[router] LLM classify failed, falling back to true miss")
        return None

    label = resp.strip().lower().rstrip(".")
    route_index = _get_route_index()

    if label in route_index:
        route, rt = route_index[label]
        extras = " ".join(route.keywords)
        log.info(f"[router] LLM classify → {label} (static missed)")
        return RouteHit(
            route=route,
            augmented_query=f"{query} {extras}".strip(),
            report_type=rt,
        )

    log.info(f"[router] LLM classify → none (true miss)")
    return None


async def match(query: str) -> RouteHit | None:
    """Two-tier routing: static triggers first, then LLM fallback."""
    hit = _static_match(query)
    if hit is not None:
        log.info(f"[router] static hit → {hit.route.name}")
        return hit
    return await _llm_classify(query)


def _node_metadata(n: NodeWithScore) -> dict:
    # NodeWithScore.metadata exists on .node, not .metadata directly in
    # some LI versions; both paths used elsewhere in the codebase.
    md = getattr(n, "metadata", None)
    if md is not None:
        return md
    return getattr(n.node, "metadata", {}) or {}


def _node_text(n: NodeWithScore) -> str:
    txt = getattr(n, "text", None)
    if txt:
        return txt
    return getattr(n.node, "get_content", lambda: "")() or ""


def boost(nodes: list[NodeWithScore], route: TopicRoute) -> tuple[list[NodeWithScore], dict]:
    """Apply additive boosts in-place; return (nodes, signal_counts_for_top).

    Boosts are additive on top of fusion's reciprocal-rank score
    (typically ~0.0–1.0 range). Three independent signals stack so a
    table row in the right section that contains the keyword gets the
    full boost; weaker matches get partial credit.

    The returned dict maps node_id -> {heading, keyword, table} bool
    counts. The retriever uses it to "force-keep" the top boosted
    candidate when all 3 signals fire — protects against LLM-rerank
    flakiness on canonical-table questions.
    """
    head_pats = tuple(p.lower() for p in route.heading_patterns)
    kw_lower = tuple(k.lower() for k in route.keywords)
    signals: dict = {}
    for n in nodes:
        md = _node_metadata(n)
        head = (md.get("heading_path") or "").lower()
        text = _node_text(n).lower()
        s_head = bool(head and any(p in head for p in head_pats))
        s_kw = bool(text and any(k in text for k in kw_lower))
        s_tbl = bool(route.prefer_table and md.get("is_table"))
        bonus = (
            (route.boost_heading if s_head else 0.0)
            + (route.boost_keyword if s_kw else 0.0)
            + (route.boost_table if s_tbl else 0.0)
        )
        if bonus:
            n.score = (n.score or 0.0) + bonus
        nid = getattr(n.node, "node_id", None) or getattr(n, "node_id", None) or id(n)
        signals[nid] = {"heading": s_head, "keyword": s_kw, "table": s_tbl}
    return nodes, signals


def merge_unique(
    primary: list[NodeWithScore],
    extra: list[NodeWithScore],
) -> list[NodeWithScore]:
    """Union by node_id, keeping the higher score on collisions.

    The augmented retrieval pass often surfaces the same node the
    primary pass found; merging by id avoids feeding duplicates to
    rerank (which would waste LLM tokens and skew scoring).
    """
    by_id: dict[str, NodeWithScore] = {}
    for n in primary + extra:
        nid = getattr(n.node, "node_id", None) or getattr(n, "node_id", None) or id(n)
        if nid in by_id:
            if (n.score or 0.0) > (by_id[nid].score or 0.0):
                by_id[nid] = n
        else:
            by_id[nid] = n
    return list(by_id.values())
