# Backlog

Every open item in one place. Order will change; nothing here gets dropped
without a decision. Grouped by what the item is *for*, not by priority.

Status: `open` · `blocked` · `parked` (deliberately deferred) · `debt`

## Accuracy — the path to 90%

| # | item | status | why it matters |
| --- | --- | --- | --- |
| A1 | Parse cache. `parse/_docling.py` and `parse/_odl.py` both promise `peerdex.index.parse_cached`; nothing implements it, so every run re-parses every PDF and re-embeds every chunk | open | enabler — A2, A4 and A5 all need re-indexing |
| A2 | Directory ingest. `index` takes a single `PDF=`; add `PDF_DIR=`. And `year` is in `RESERVED_KEYS`, so each sidecar's year is dropped and the CLI value wins — a mixed-year directory cannot be ingested correctly | blocked on nothing, needed by A3 | without it the second corpus cannot land |
| A3 | Second corpus scored. 10 unique PDFs, 2 document types, 3 years, already deduplicated | blocked on A2 | every score so far measures one corpus and one year, so all of them may be overfitted |
| A4 | Fact layer — typed `(label, value, unit, scale, period, page, provenance)` rows. Design in `fact-layer.md` | open | the largest single win: units, coverage beyond the oracle, and the 36% of misses that are arithmetic |
| A5 | Derivation rules over facts — sums, differences, ratios, unit conversion | blocked on A4 | four of eleven misses have ground truth that appears nowhere in the document |
| A6 | Self-contained chunks — fold a bare `## number` plus caption into its table or section | open | a 75-char callout currently outranks the 544-char table that holds the answer |
| A7 | Replace `final_top_k` with a score- or coverage-based cutoff | open | 25 was chosen so one report's table fell inside the window; that is corpus tuning |
| A8 | LLM reranker back on top of FTS, measured 3× with `variance.py` | open | worth +4 on the lexical path (10/28 → 14/28). Deliberately last: one LLM call per question, and it previously made scores non-deterministic |
| A9 | `query_type="hybrid"` and `lancedb.rerankers` — a local cross-encoder may buy A8's +4 with no API call and no non-determinism | open | cheaper and deterministic if it works |
| A10 | First end-to-end agent baseline (`make stage3`) | open | no number recorded so far measures the agent end to end; stage 2 is retrieval only |
| A11 | Citation ordering — citations sort by retrieval score, so citation `[1]` can be a passage the answer did not use. Observed: the answer was right and `[1]` was the wrong-metric callout | open | a misleading citation undermines a correct answer |
| A12 | Document-level deduplication by content digest at ingest | open | measured as marginal for ranking (rank 83 → 65), but the second corpus proved duplicates are structural, not a local accident. Identity must come from the digest, never the filename |
| A13 | Ground truth for the second corpus from the local data service on port 8182, plus a mapping from its metric identifiers to suite questions | blocked on that stack running | without it the second corpus cannot be scored |

## Generic-ness — any PDF, not one report

| # | item | status | why it matters |
| --- | --- | --- | --- |
| G1 | Pluggable prompt profiles — a registry of `DocumentPrompts`, injected rather than imported, with `-p / --prompt-type` on `index`, `ask` and `suite`, and a refusal when a query-time profile does not match any indexed `prompt_version`. Detail in `roadmap.md` | open | the seam that makes an invoice or a bill work as well as a report |
| G2 | `roadmap.md` is stale — it cites fusion, HyDE and reranker call sites in `retrieve/_retriever.py` that were deleted when retrieval was stripped to one step | debt | the design is still right; the line references are not |
| G3 | Docling markdown dump per document (`export_to_markdown()`) so chunking strategy is designed from the real structure rather than guesswork | open | requested explicitly as a discussion artifact — produce the file, do not redesign chunking alone |

## Speed and scale — 1 → 3 → 5 → 10 → 10k

| # | item | status | why it matters |
| --- | --- | --- | --- |
| S1 | Per-stage wall-clock: parse vs chunk vs embed vs docstore-persist, on 3 documents, sequential then 3-way parallel | open | the 1→3 speedup must be a measured number, not a guess |
| S2 | Move the docstore off a single JSON file. `index_doc` loads and rewrites a 17.7MB `docstore.json` **once per document** | open | O(corpus) work per document — the real wall at 10k docs, and no language rewrite fixes it |
| S3 | Configurable document-level concurrency, sequential or parallel, with the width itself a knob | open | 10 documents at once, not 10 in a row |
| S4 | Mojo for profiled hot kernels only — never the docling models | parked | speed may change when and how often docling runs, never what it produces |

## Debt

| # | item | status |
| --- | --- | --- |
| D1 | `HierarchicalChunker.chunk` complexity ≈30 and `_render_picture_chunk_text` = 16, against a documented limit of 3 | debt |
| D2 | Agent `max_retries` hardcoded to 2 — should be a config knob | debt |
| D3 | Two pre-existing `ruff format` failures under `scripts/` | debt |
| D4 | Debloat pass across the codebase | debt |
| D5 | Nothing committed since `bb410bc` — the retrieval rewrite, the top-k fix and these docs are all working-tree only | debt |

## Parked

| # | item | note |
| --- | --- | --- |
| P1 | VLM extractor via pydantic-ai | deliberate |
| P2 | Mojo PDF parser research | see S4 |
| P3 | README rewrite | after the fact layer changes the story |
| P4 | Rotate the credential in `.git/config`; git history and commit identity carry identifying data | repository is private for now, so deferred by decision |

## Rules that constrain all of the above

- **Never report a single run.** `variance.py` runs stage 2 three times and prints
  the spread. The old pipeline gave 16, then 12, then 13 on identical input.
- **A fix must be a property of the system, not of a corpus.** A fixed top-k is
  corpus tuning; a score-based cutoff is a system property.
- **Docling's output is not negotiable.** Speed work may change when, where and
  how often it runs, never what it produces.
- **The LanceDB table holds children only** (4,739 rows; parents live in the
  docstore). Full-text search therefore searches children, where the numbers are.
