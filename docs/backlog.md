# Backlog

The agreed order, then the unordered pool, then debt. Nothing is added here
until it is decided.

## Where we are

End to end on the first corpus: **12 of 28 correct**. Target 90% = 25 of 28.
The 16 that are wrong or missing sit in three buckets:

| bucket | size | problem |
| --- | --- | --- |
| A | 5 | retrieval returned the value, the answer was still wrong |
| B | 4 | the answer is derived — a sum or unit conversion, printed nowhere |
| C | 7 | retrieval never found a value that is in the document |

16 available against 13 needed. No slack for a step that misses.

Per stage: parse 28/28 (loose — 1% tolerance with power-of-ten freedom across
the whole corpus, so it over-reports), figures +0, retrieval 17/28, end to end
12/28. Beyond those 28, the suite holds 58 questions with no reference value;
the agent answered 32 of them, unverified — and at least one is a known
fabrication, so that bucket is not yet evidence of anything.

## Agreed plan

Step numbers are stable: a completed step is removed, the rest keep their
numbers so earlier references stay valid.

| step | work | bucket |
| --- | --- | --- |
| 3 | Verify the 16 disputed questions — the 10 mismatches and 6 misses where we and the reference disagree. Candidates enumerated from the database with label, unit and page; a person adjudicates. The pipeline's own answer must never become the reference | — |
| 4 | Switch retrieval to dense vector search, build a vector index | C (2 of 7) |
| 5 | Typed units and scale, plus a derivation step for sums, differences, ratios and unit conversion | B (4) |
| 6 | Replace `final_top_k` with a score- or coverage-based cutoff | — |
| 7 | Second corpus — directory ingest, sidecar-driven year, then score it | — |
| 8 | Speed and scale — docstore off the single JSON, then configurable document concurrency | — |
| 9 | Agent framework — a real LlamaIndex agent instead of the hand-written retry | — |

Each step ends with a measured number over three runs, never one.

**Evidence behind step 4**: dense vector 19/28 against full-text 17/28, three
runs, spread 0, and dense misses nothing full-text finds. No build — the vectors
are already computed and paid for on every ingest, they were simply never
indexed or queried. Naive RRF fusion of the two scored 17 and is not worth it.

**Note on step 7**: it is the only check against fitting one report, and it sits
after five fixes and a schema. If step 5's schema turns out to be corpus-shaped,
part of it gets redone.

## Pool — decide when the plan above is done

| item | note |
| --- | --- |
| Reranker | worth +4 on the lexical path historically. Try LanceDB hybrid with a local cross-encoder before any LLM reranker: deterministic, no API call |
| Prompt profiles | the `DocumentPrompts` registry with `-p / --prompt-type`. Detail in `prompt-profiles.md`. Smaller than designed — 3 consumers remain, not 6 |
| Chunking: fold callouts | a bare `## number` plus caption is a fragment that outranks real tables. Lowest priority — parsing is not the bottleneck |
| Citation ordering | citations sort by retrieval score, so `[1]` can be a passage the answer did not use |
| Document dedup by digest | duplicates are structural, not a local accident. Identity from content digest, never filename |
| Second-corpus reference values | from a local data service on port 8182; needs that stack up and a metric-id mapping |
| Verify the 32 unverified claims | answers produced where the reference is empty. Deliberately out of step 3's scope, so "better than the reference" stays **unproven** and must not be reported as a result |
| Reference values look derived | water reference is a *withdrawal* figure against a consumption question; the total-GHG reference is a sum printed nowhere; two energy references have repeating decimals, so they are conversions of something else. The ruler itself is suspect |
| Hierarchical vector search | blocked: the table holds 0 parents of 4,739 rows. Parents live only in the docstore |
| **Compare the index algorithms — HNSW first** | only `IVF_PQ` has been measured (19/28 with `refine_factor=5`, 17/28 without). `IVF_HNSW_FLAT`, `IVF_HNSW_SQ`, `IVF_HNSW_PQ`, plus `IVF_FLAT`, `IVF_SQ` and `IVF_RQ`, are untried. Report **recall, query latency and storage together** on the same 28 questions against the exact brute-force baseline of 19/28 — an option that wins one axis by losing another is rejected. If HNSW is better on all three, adopt it |
| Extractor must cite the period column | it cites the row label but not the period, so it read `Baseline 2015` where `2025` was asked. Same fix shape as the label. **This is what the vector default is blocked on** |

## Debt

| item | note |
| --- | --- |
| Chunker complexity | `HierarchicalChunker.chunk` ≈30 and `_render_picture_chunk_text` 16, against a documented limit of 3 |
| `max_retries` hardcoded | fixed at 2 in the agent; should be config |
| `scripts/` formatting | two pre-existing `ruff format` failures, outside `make lint`'s scope |
| Unused embeddings | computed and stored per chunk, never queried. **Step 4 resolves this** |
| No embedding cache | unlike the parse, embeddings are recomputed on every re-index at API cost |
| Debloat pass | across the codebase |

## Done

| item | outcome |
| --- | --- |
| Wrong-answer regression | root-caused to full-text length bias; `final_top_k` 5 → 25 took retrieval 11/28 → 17/28 and the answer is now correct |
| Three chunker bugs | node-id collision causing an infinite loop, parents with no children, duplicate parent ids |
| First end-to-end baseline | 12/28 correct, beating the previous path on every bucket |
| Nine dead settings | three `retrieval` keys, three `llm` model keys, three `DocumentPrompts` fields — deleted |
| Docs | stale architecture image replaced with text; roadmap renamed to `prompt-profiles.md`; plan de-duplicated into this file |
| Corpus dedup | 3 byte-identical pairs removed by MD5; 63MB of stale local artifacts deleted |
| Step 2 — retrieved-but-wrong | Two fixes. The scorer now reads the answer's unit, so a figure reported in `$m` is no longer scored as a millionfold error: strict `match` 11 → 12. The extractor must cite the printed row label and refuses without one, which turned 4 fabricated answers and 2 confidently wrong numbers into abstentions — `mismatch` 12 → 10, `extra` 34 → 32. The label bought honesty, not accuracy. A deterministic term guard was designed and deliberately **not** built: it would have caught roughly one more case while risking refusal of correct answers |
| Step 1 — parse cache | `peerdex.index.parse_cached`, keyed on file bytes plus extractor name and version. Measured cold 39.82s → warm 0.01s on a 34-page document, with blocks, pages, `source_meta` and figure images identical. `index_doc` shrank by three lines |

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
