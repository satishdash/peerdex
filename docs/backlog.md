# Backlog

The agreed order, then the unordered pool, then debt. Nothing is added here
until it is decided. Scores live in `README.md`.

## Agreed plan

Step numbers are stable: a completed step is removed, the rest keep their
numbers.

| step | work | status |
| --- | --- | --- |
| 8 | Speed and scale: parents as LanceDB rows, then configurable document concurrency | parents done; concurrency open |
| 9 | Agent framework: a real LlamaIndex agent instead of the hand-written retry. Matters at scale only, so last | not started |

Each step ends with a measured number over three runs, never one.

## Pool — decide when the plan above is done

| item | note |
| --- | --- |
| Eval hardening | precision-on-answered = `match/(match+mismatch)`: A 61%, C 84%, reported nowhere. Add MRR, cache-bypass variance runs, cost and latency per run. CLI output only; no Phoenix, Langfuse or similar |
| Scorer concurrency | `experiments/score_suite.py` is sequential; one stage-3 run takes 3–10 min. Semaphore under `openai_tpm` |
| Chunk vs rank on the 9 misses | for each retrieval miss at k=25, is the value inside any child chunk at all? Splits misses into bad chunk vs bad rank before changing either |
| Ranker, tuned properly | measured then reverted: number-density reorder moved 15 of 21 reachable answers up, none down; recall@10 14→20; MRR .27→.44; `match`/`mismatch` 15/7 vs 13/10 at k=25. k=50 had the best recall (21/28) and the worst accuracy (12): tune on accuracy, not recall |
| Units reconciliation | 2 of corpus C's 7 misses are unit or scale |
| Table-cell grid checker | index-time check that every cell sits under its header. Build only after corpus C's 3 extraction errors are classified row vs column |
| Reranker | LanceDB hybrid with a local cross-encoder before any LLM reranker: deterministic, no API call |
| Hierarchical retrieval | unblocked by step 8: 4,429 parents in `<domain>_parents`, still write-only. Retrieve children, hand the parent section to the extractor |
| Prompt profiles | `DocumentPrompts` registry with `-p / --prompt-type`. Detail in `prompt-profiles.md`. 3 consumers, not 6 |
| docling.rs | Rust port of docling as the parse backend. Parse is 1,121 s over 11 PDFs today, the ingest bottleneck. Needs a dependency decision first |
| Verify the unverified answers | 58 suite questions have no reference; ~31 answers there are unverified, at least one a known fabrication. "Better than the reference" stays unproven |
| Reference values look derived | water reference is a withdrawal figure against a consumption question; total-GHG reference is a sum printed nowhere; two energy references have repeating decimals |
| Correct the reference | corpus A: 15 of 17 disputed references are contradicted, absent or unconfirmable, capping A near 14/28. Needs the source that produced them |
| One value answered for several questions | `6,197,690` returned for three Scope 3 questions, `1.1%` for three others: a plausible neighbour satisfies the row label |
| Difference, ratio and unit conversion unexercised | no suite question spells out a subtraction, a division, or a unit the document disagrees with. Unit tests only |
| Duplicate document | `d85c8698.pdf` (1,018 rows) is a reprint of an indexed report with different bytes, invisible to the digest. Left unindexed on purpose |
| Document dedup by digest | identity from content digest, never filename |
| Citation ordering | citations sort by retrieval score, so `[1]` can be a passage the answer did not use |
| Chunking: fold callouts | a bare `## number` plus caption outranks real tables. Lowest priority |
| Re-test index types at scale | all seven tied on recall and latency at 4,739 rows. HNSW needs 400k+ rows to show; re-run when a table is that size |

## Debt

| item | note |
| --- | --- |
| Chunker complexity | `HierarchicalChunker.chunk` ≈30 and `_render_picture_chunk_text` 16, against a limit of 3 |
| `max_retries` hardcoded | fixed at 2 in the agent; should be config |
| `scripts/` formatting | two pre-existing `ruff format` failures, outside `make lint` |
| No embedding cache | embeddings are recomputed on every re-index at API cost |
| Three files over the 400-line rule | `chunk/_chunker.py` 511, `parse/_liteparse.py` 429, `index/_index.py` 408 |
| Debloat pass | across the codebase |

## Rules

- Never report a single run of anything involving an LLM. The old pipeline gave
  16, then 12, then 13 on identical input.
- A fix must be a property of the system, not of a corpus. A fixed top-k is
  corpus tuning; a score-based cutoff is a system property.
- Docling's output is not negotiable. Speed work may change when, where and how
  often it runs, never what it produces.
- The LanceDB table holds children only. Full-text and vector search both search
  children, where the numbers are.
- No document in this repository exceeds 400 lines.
