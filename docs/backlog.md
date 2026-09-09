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
the agent answered 34 of them, unverified.

## Agreed plan

Step numbers are stable: a completed step is removed, the rest keep their
numbers so earlier references stay valid.

| step | work | bucket |
| --- | --- | --- |
| 2 | Close the retrieved-but-wrong gap | A (5) |
| 3 | Verify a sample of the 34 answers found where the reference is empty | — |
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
| Hierarchical vector search | blocked: the table holds 0 parents of 4,739 rows. Parents live only in the docstore |

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
