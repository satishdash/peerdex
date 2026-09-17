"""Score the ask path against a suite of reference answers.

Usage:
    uv run python experiments/test_eval_suite.py --company acme --year 2024
    uv run python experiments/test_eval_suite.py                      # every scenario
    uv run python experiments/test_eval_suite.py --rescore            # no asking, stored answers
    uv run python experiments/test_eval_suite.py --find-only          # retrieval alone, no model

The suite is never committed. --suite, or PEERDEX_SUITES, points at it.
Answers are stored after every question, so an interrupted run resumes and a
rescore costs nothing.
"""

import argparse
import asyncio
import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from ask import AnswerKind, AskPipeline, Question
from ask.find import Finder
from evaluation import AnswerScorer

console = Console()

STRICT_ABS_TOL = 0.001
BUCKETS = ("good", "wrong", "missed", "silent", "invented")
NATIVE_TO_BUCKET = {
    "match": "good",
    "mismatch": "wrong",
    "scale_mismatch": "wrong",
    "missed": "missed",
    "abstained": "silent",
    "extra": "invented",
}


class StrictScorer(AnswerScorer):
    """The reference tolerance: 0.001 absolute, no relative slack, no scale forgiveness."""

    def __init__(self) -> None:
        super().__init__(rel_tol=0.0, scales=())

    def _close(self, a: float, b: float) -> bool:
        return abs(a - b) <= STRICT_ABS_TOL


@dataclass
class Asked:
    """One question put to one company for one year, and what came back."""

    question: str
    company: str
    year: int
    references: list[str]
    value: str
    unit: str
    refused: bool
    pages: list[int]
    expected_pages: list[int]

    @property
    def key(self) -> str:
        return f"{self.company}|{self.year}|{self.question}"


def scenarios(questions, company, year):
    """Every (company, year) the suite covers, narrowed by whatever was asked for."""
    seen = set()
    for q in questions:
        for co, years in (q.get("ground_truth") or {}).items():
            for yr in years:
                if (company and co != company) or (year and int(yr) != year):
                    continue
                seen.add((co, int(yr)))
    return sorted(seen)


def references(entry):
    """Every value that counts as correct: the expected answer and its alternates."""
    refs = [str(entry.get("expected_answer", "")).strip()]
    refs += [str(a).strip() for a in entry.get("expected_alternates", [])]
    return [r for r in refs if r]


def bucket(scorer, refs, value, unit):
    """The reference table, 1:1: good, wrong, missed, silent, invented."""
    if not refs:
        return "invented" if value.strip() else "silent"
    if not value.strip():
        return "missed"
    cats = [NATIVE_TO_BUCKET[scorer.score(r, value, unit).category] for r in refs]
    return "good" if "good" in cats else "wrong"


def scores(counts):
    """precision, positive recall, negative recall."""

    def ratio(num, den):
        return float("nan") if den == 0 else num / den

    good, wrong = counts["good"], counts["wrong"]
    missed, silent, invented = counts["missed"], counts["silent"], counts["invented"]
    return (
        ratio(good, good + wrong + invented),
        ratio(good, good + wrong + missed),
        ratio(silent, silent + invented),
    )


async def ask_one(q, company, year, domain, entry):
    """One question through the whole ask path."""
    answer = await AskPipeline.ask(
        Question(
            text=q["q"],
            kind=AnswerKind(q.get("kind", "quantitative")),
            company=company,
            domain=domain,
            filters={"year": {year}},
        )
    )
    return Asked(
        question=q["q"],
        company=company,
        year=year,
        references=references(entry),
        value="" if answer.refused else answer.value,
        unit=answer.unit,
        refused=answer.refused,
        pages=sorted({c.page_no for c in answer.citations}),
        expected_pages=[int(p) for p in entry.get("expected_pages", [])],
    )


async def find_one(q, company, year, domain, entry, top_k):
    """Retrieval alone. No reader, no resolver, no model."""
    passages = await Finder.find(
        Question(
            text=q["q"],
            kind=AnswerKind(q.get("kind", "quantitative")),
            company=company,
            domain=domain,
            filters={"year": {year}},
        )
    )
    return Asked(
        question=q["q"],
        company=company,
        year=year,
        references=references(entry),
        value="",
        unit="",
        refused=False,
        pages=[p.page_no for p in passages[:top_k]],
        expected_pages=[int(p) for p in entry.get("expected_pages", [])],
    )


async def run(questions, pairs, domain, store, find_only, top_k):
    """Ask every question of every scenario, storing each answer as it lands."""
    results = []
    for company, year in pairs:
        for q in questions:
            entry = ((q.get("ground_truth") or {}).get(company) or {}).get(year)
            entry = entry if entry is not None else ((q.get("ground_truth") or {}).get(company) or {}).get(str(year))
            if entry is None:
                continue
            key = f"{company}|{year}|{q['q']}"
            if key in store:
                results.append(Asked(**store[key]))
                continue
            fn = find_one(q, company, year, domain, entry, top_k) if find_only else ask_one(q, company, year, domain, entry)
            asked = await fn
            store[key] = asked.__dict__ | {}
            store[key].pop("key", None)
            results.append(asked)
            save(store)
    return results


def save(store):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(store, indent=1))


def recall_at_k(asked):
    hit = len(set(asked.pages) & set(asked.expected_pages))
    return hit / len(asked.expected_pages)


def ndcg_at_k(asked):
    want = set(asked.expected_pages)
    gain = sum(1 / math.log2(i + 2) for i, p in enumerate(asked.pages) if p in want)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(want), len(asked.pages) or len(want))))
    return gain / ideal if ideal else float("nan")


def per_question(results, strict, native):
    table = Table(title="per question", show_lines=False)
    for col in ("company", "year", "question", "reference", "answer", "strict", "native"):
        table.add_column(col, overflow="fold")
    for r in results:
        ref = " | ".join(r.references) or "—"
        table.add_row(
            r.company,
            str(r.year),
            r.question[:48],
            ref[:24],
            (r.value or "—")[:20],
            bucket(strict, r.references, r.value, r.unit),
            bucket(native, r.references, r.value, r.unit),
        )
    console.print(table)


def report(results, strict, native):
    table = Table(title="buckets and scores")
    for col in ("scope", "tolerance", *BUCKETS, "precision", "pos recall", "neg recall"):
        table.add_column(col)

    by_company = {}
    for label, scorer in (("strict", strict), ("native", native)):
        per_co = {}
        for r in results:
            per_co.setdefault(r.company, Counter())[bucket(scorer, r.references, r.value, r.unit)] += 1
        by_company[label] = per_co
        for co, counts in sorted(per_co.items()):
            table.add_row(co, label, *(str(counts[b]) for b in BUCKETS), *(f"{s:.3f}" for s in scores(counts)))

    for label in ("strict", "native"):
        per_co = by_company[label]
        macro = [
            sum(m[i] for m in (scores(c) for c in per_co.values()) if not math.isnan(m[i]))
            / max(1, sum(1 for c in per_co.values() if not math.isnan(scores(c)[i])))
            for i in range(3)
        ]
        table.add_row(f"macro ({len(per_co)})", label, *("" for _ in BUCKETS), *(f"{m:.3f}" for m in macro))
    console.print(table)
    if len(by_company["native"]) == 1:
        console.print("[yellow]one company only — indicative, not a headline score[/yellow]")


def report_find(results, top_k):
    scored = [r for r in results if r.expected_pages]
    if not scored:
        console.print("[yellow]no expected_pages in this suite — retrieval cannot be scored[/yellow]")
        return
    table = Table(title=f"retrieval @ k={top_k}")
    for col in ("company", "year", "scored", f"recall@{top_k}", f"ndcg@{top_k}"):
        table.add_column(col)
    per = {}
    for r in scored:
        per.setdefault((r.company, r.year), []).append(r)
    for (co, yr), rs in sorted(per.items()):
        table.add_row(
            co, str(yr), str(len(rs)),
            f"{sum(recall_at_k(r) for r in rs) / len(rs):.3f}",
            f"{sum(ndcg_at_k(r) for r in rs) / len(rs):.3f}",
        )
    console.print(table)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--suite", default=os.environ.get("PEERDEX_SUITES", "config/suites.yaml"))
    p.add_argument("--name", default="")
    p.add_argument("--company", default="")
    p.add_argument("--year", type=int, default=0)
    p.add_argument("--domain", default="corporate")
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--rescore", action="store_true")
    p.add_argument("--find-only", action="store_true")
    p.add_argument("--detail", action="store_true", default=True)
    args = p.parse_args()

    suites = yaml.safe_load(Path(args.suite).expanduser().read_text())["suites"]
    name = args.name or next(iter(suites))
    questions = suites[name]
    questions = questions if isinstance(questions, list) else questions.get("questions", [])

    global STORE_PATH
    root = Path(os.environ.get("PEERDEX_EVAL_DIR", "~/Documents/peerdex-eval")).expanduser()
    STORE_PATH = root / "answers" / f"{name}{'-find' if args.find_only else ''}.json"
    store = json.loads(STORE_PATH.read_text()) if STORE_PATH.exists() else {}

    pairs = scenarios(questions, args.company, args.year)
    if not pairs:
        console.print("[red]no scenario matches[/red]")
        return
    console.print(f"suite [bold]{name}[/bold] · {len(questions)} questions · scenarios {pairs}")

    if args.rescore:
        results = [Asked(**v) for k, v in store.items() if (k.split("|")[0], int(k.split("|")[1])) in set(pairs)]
    else:
        results = asyncio.run(run(questions, pairs, args.domain, store, args.find_only, args.top_k))

    if args.find_only:
        report_find(results, args.top_k)
        return

    strict, native = StrictScorer(), AnswerScorer()
    if args.detail:
        per_question(results, strict, native)
    report(results, strict, native)


if __name__ == "__main__":
    main()
