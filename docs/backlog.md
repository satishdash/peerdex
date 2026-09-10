# Backlog

The agreed order, then the unordered pool, then debt. Nothing is added here
until it is decided.

## Where we are

End to end on the first corpus: **13 of 28 correct**, 10 confidently wrong, 5
missed. Per stage: parse 28/28 (loose — 1% tolerance with power-of-ten
freedom across the whole corpus, so it over-reports), figures +0, retrieval
19/28, end to end 13/28.

**Target 90% is not reachable against this reference, and step 3 proved why.**
Every disputed question was audited for whether its reference value appears on a
related table row. Of 17:

| verdict | size | consequence |
| --- | --- | --- |
| genuinely ours | 2 | one fixed (Scope 1 column), one open (product recalls) |
| reference contradicted by the documents | 2 | we answer correctly and are scored wrong |
| reference printed nowhere | 2 | derived sums, unreachable without a derivation step |
| reference matches no related row | 11 | unconfirmable; several look like a unit convention the documents never print |

So the honest ceiling here is roughly **14 of 28** until the reference is
corrected, and 13 of it is now reached. Chasing 25/28 against this ruler would
be fitting to its errors.
A corrected reference, or a second corpus, is now the only way to raise the
number honestly.

Beyond those 28, the suite holds 58 questions with no reference value; the agent
answered 31 of them, unverified — and at least one is a known fabrication, so
that bucket is not yet evidence of anything.

## Agreed plan

Step numbers are stable: a completed step is removed, the rest keep their
numbers so earlier references stay valid.

| step | work | bucket |
| --- | --- | --- |
| 6 | Replace `final_top_k` with a score- or coverage-based cutoff | — |
| 7 | Second corpus — ingested; scoring blocked on the reference values | — |
| 8 | Speed and scale — docstore off the single JSON, then configurable document concurrency | — |
| 9 | Agent framework — a real LlamaIndex agent instead of the hand-written retry | — |

Each step ends with a measured number over three runs, never one.

**Note on step 7**: it is the only check against fitting one report, and after
step 3's audit it is also the only way left to raise the accuracy number
honestly. It is also where step 5's unit table gets its first real test: only
four of its dimensions are exercised by this corpus.

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
| Re-test the index types at production scale | all seven tied on recall and latency at 4,739 rows, where the metadata filter dominates the query. Storage decided it. HNSW's sublinear query time needs 400k+ rows to appear, so it is unadopted on present evidence rather than disproven — re-run when a table is that size |
| One value answered for several questions | `6,197,690` was returned for three different Scope 3 questions and `1.1%` for three others. The row label is being satisfied by a plausible neighbour — the same class of bug the period column just fixed, one axis over |
| Difference and ratio derivations are unexercised | the sum path is measured; no question in this suite spells out a subtraction or a division, so those two operators are covered by unit tests only |
| Unit conversion is unexercised | the same. No question here states a unit that the printed figure disagrees with, so conversion changed nothing measurable and is covered by unit tests only |
| Correct the reference | step 3 showed 15 of 17 disputed references are contradicted, absent or unconfirmable. Until they are corrected the accuracy number is capped around 14/28 by the ruler. Needs the source that produced them, not our own answers |

## Debt

| item | note |
| --- | --- |
| Chunker complexity | `HierarchicalChunker.chunk` ≈30 and `_render_picture_chunk_text` 16, against a documented limit of 3 |
| `max_retries` hardcoded | fixed at 2 in the agent; should be config |
| `scripts/` formatting | two pre-existing `ruff format` failures, outside `make lint`'s scope |
| Unused embeddings | resolved by step 4 — they are now the default read path |
| No embedding cache | unlike the parse, embeddings are recomputed on every re-index at API cost |
| Three files over the 400-line rule | `chunk/_chunker.py` 511 and `parse/_liteparse.py` 429 are long-standing; `index/_index.py` 435 grew during the domain change and is the one to split first. `agent/_agent.py` was split at 463 into `_agent` / `_model` / `_planner` |
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
| Index type is configuration | `index.vector_type`, validated against the seven LanceDB types so a typo fails at load rather than at build. Chosen by measuring all seven on recall, latency and storage together: every one reaches the exact brute-force 19/28 once refined, so storage decides and `IVF_PQ` wins it 3×. **HNSW rejected** — more storage at every quantisation level for identical recall. Fixed a shipped bug while proving it: LanceDB reports `IvfPq`, not `IVF_PQ`, so the "already indexed?" guard never fired and every ingest rebuilt the whole vector index |
| Step 4 — dense retrieval | `query_type` is a setting, `vector` the default, and the IVF_PQ index's partitions and sub-vectors are derived from the row count rather than tuned to one corpus. Retrieval 17/28 → **19/28**. Full text and dense return opposite score polarities, normalised in one place; `refine_factor=5` is mandatory or product quantisation gives the whole gain back |
| Step 3 — audit the reference | A probe decides, per disputed question, whether the reference value sits on a table row whose label relates to the question — a fact about the documents, not an opinion. The first version asked only whether the number existed anywhere and so decided nothing: with 1% tolerance and power-of-ten freedom almost everything matches something. Verdict on 17: 2 ours, 2 contradicted, 2 absent, 11 unconfirmable |
| Extractor cites the period column | The row label alone left one figure per period to choose from, and `298,498` came back from a `Baseline 2015` column under a correct `Scope 1` label. The extractor now names the column and refuses when it states a different period; the asked-for period reaches it from the `year` filter, since the question text rarely contains it. `match` 11 → **12**, `mismatch` 13 → **11**, six fabrications became abstentions. Only columns that state a period are judged — demanding one of every column refused two correct board counts under a `Female` header |
| Step 5 — typed units and derivations | `peerdex.quantity`: a unit registry, a `Quantity` whose arithmetic converts before it combines and refuses across dimensions, and a derivation step allowed **only** where the question spells the arithmetic out. `match` 12 → **13**, `mismatch` 11 → **10** — `Total GHG emissions (Scope 1 + Scope 2 + Scope 3)` is now summed from its three operands instead of read off a neighbouring row, and returns the reference value exactly. Measured first: **0 of 16** wrong-or-missed answers were off by a power of ten or any unit factor, so units and scale were worth nothing here and only the derivation moved the number. Kept as the seam a second domain needs, not counted as accuracy |
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
