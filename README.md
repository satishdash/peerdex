# peerdex

Agentic RAG over business PDFs. Ask a question, get the value or nothing.

Built to be document-type agnostic: the machinery knows about tables, charts,
figures and prose, not about any particular kind of report. What varies per
document type is the schema of facts wanted and the questions asked.

## Quick start

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY
uv run rag index report.pdf -c acme -d corporate -y 2025
uv run rag ask "Gross global Scope 1 emissions" -c acme -d corporate -f year=2025
```

## How it works

```
PDF → extract → chunk (+VLM on figures) → embed → LanceDB + FTS + vector index

question → plan → retrieve (one LanceDB search) → extract → reflect → answer
```

Retrieval is a single database call. `retrieval.query_type` chooses the mode:
`fts` searches the chunk text through an inverted index and costs no API call;
`vector` searches the stored embeddings and costs one embedding of the question.

The reasoning lives in the agent, which plans, reformulates the query from what
came back, and retries — bounded at two attempts, with every attempt recorded on
the answer.

**A quantitative question returns the value alone, or an empty string.** Never a
hedge, never prose around a number. A qualitative question returns prose. Both
carry citations with page numbers.

Full detail in [`docs/architecture.md`](docs/architecture.md).

## Documents

Every document is indexed as-is — no report-type taxonomy, no routing. `company`
is the only fixed filter. Everything else is an attribute:

```bash
uv run rag index report.pdf -c acme -d corporate -y 2025 -m benchmark=true
uv run rag ask "Total water consumption" -c acme -d corporate -f benchmark=true
```

`-d` names the domain, which is one LanceDB table and one prompt set. It is
required on every ingest and every query, and an unconfigured domain is refused
rather than silently opening an empty table.

`doc_id` is `sha256(company + extractor + file bytes)`, so re-indexing a file
replaces it and extractor variants coexist for comparison.

Two documents are the same document when their content digests match — never
because their filenames look alike.

## Extractors

`-e docling` (default), `liteparse`, `kreuzberg`, `odl`. All emit the same
`ExtractedDoc`, so they are swappable and comparable.

`odl` additionally needs Java 11+ and `opendataloader-pdf-hybrid --port 5002`.

Measured over 11 PDFs from one issuer. Parse recall does not separate them, so
the choice is made on latency.

| extractor | text extracted | parse errors | parse time |
| --- | --- | --- | --- |
| `kreuzberg` | 2,674,607 chars | 0 | 7 s |
| `liteparse` | 1,917,146 chars | 0 | 177 s |
| `docling` | 1,613,930 chars | 0 | 1,121 s |
| `odl` | N/A | N/A | not run — ~59 min |

```bash
uv run python experiments/test_extractor_benchmark.py ~/Documents/reports
```

## Where it stands

One table, kept current as each step lands. A row is only added once it has been
measured; nothing here is an estimate.

### Corpus A — 11 documents, 648 pages, 49.5MB → 4,739 child chunks

Scored over the 28 questions that carry a reference value.

| stage | what it measures | full text | dense (vector) |
| --- | --- | --- | --- |
| 0 parse | reference value present in the extracted text | 28/28 ⚠ | 28/28 ⚠ |
| 1 figures | values reachable *only* via figure descriptions | +0 | +0 |
| 2 retrieval | value present in the retrieved passages | 17/28 | **19/28** |
| 3 end to end | final answer matches the reference | 12/28 | **13/28** |
| — | confidently wrong (`mismatch`) | 10 | **10** |
| — | abstained where a value exists (`missed`) | 6 | **5** |
| — | answered where the reference is empty (`extra`) | 32 | 31 |

**Higher retrieval recall did not pay out until the extractor earned it.** Dense
search reaches two questions full text cannot, but at first it answered *worse*:
asked for Scope 1 emissions it returned the right table and read `298,498` from
the `Baseline 2015` column instead of `62,587` from `2025` — a correct row label
on the wrong period. Requiring the extractor to name the column it read, and
refusing when that column states a different period, closed the gap:

| dense, end to end | match | mismatch | missed | extra |
| --- | --- | --- | --- | --- |
| row label only | 11 | 13 | 4 | 35 |
| + period column required | 12 | 11 | 5 | 31 |
| + derived where the question asks | **13** | **10** | 5 | 31 |

Six fabrications became abstentions in the same change. The guard judges only
columns that state a period — an early version demanded one of *every* column
and refused two correct board-member counts sitting under a `Female` header.

The last row is one question: `Total GHG emissions (Scope 1 + Scope 2 + Scope
3)`, whose reference is a sum the documents print nowhere. Because the question
spells the arithmetic out, the agent extracts each operand and adds them as
typed quantities. Every other question still reads one printed figure.

**Typed units and scale bought nothing measurable here** — of the 16
wrong-or-missed answers, none was off by a power of ten or any unit factor. The
unit table is the seam a second document domain needs, not an accuracy result.

### Retrieval mode, measured directly

k=25, three runs each, zero spread:

| mode | hits |
| --- | --- |
| full text (tantivy inverted index) | 17/28 |
| dense, exact search, no index | 19/28 |
| dense, IVF_PQ index, no refinement | 17/28 |
| dense, IVF_PQ index, `refine_factor=5` | **19/28** |

The index compresses each 1536-dim vector 64× and gives the entire dense gain
back; refinement against the uncompressed vectors restores it. `nprobes` made no
difference at this size, which is how we know the loss was compression rather
than partition pruning.

### Vector index type, all seven measured

Same 28 questions, k=25, three runs each, spread 0. `index.vector_type` selects
it; switching is a rebuild, never a re-embedding or a migration.

| index | recall unrefined | recall refined | latency | bytes/row | at 10k docs |
| --- | --- | --- | --- | --- | --- |
| exact, no index | 19/28 | 19/28 | 17.3ms | — | — |
| **IVF_PQ** (default) | 16/28 | **19/28** | 18.3ms | **0.55KB** | **2.4GB** |
| IVF_HNSW_PQ | 14/28 | 19/28 | 14.8ms | 0.71KB | 3.1GB |
| IVF_SQ | 19/28 | 19/28 | 15.9ms | 1.70KB | 7.3GB |
| IVF_RQ | 19/28 | 19/28 | 16.0ms | 1.73KB | 7.5GB |
| IVF_HNSW_SQ | 19/28 | 19/28 | 14.3ms | 1.88KB | 8.1GB |
| IVF_FLAT | 19/28 | 19/28 | 14.1ms | 6.55KB | 28GB |
| IVF_HNSW_FLAT | 19/28 | 19/28 | 15.9ms | 6.70KB | 29GB |

**HNSW was not adopted.** At every quantisation level its variant costs more
storage for identical recall and indistinguishable latency. Storage is the only
axis that separates these at all, and `IVF_PQ` wins it by 3×.

Two caveats. **Latency here proves nothing** — at 4,739 rows the metadata filter
dominates, not the vector search, so HNSW's sublinear query time cannot show
itself; it is unadopted on present evidence, not disproven. And **the unrefined
PQ numbers are pessimistic**: 96 sub-quantisers trained on 4,739 vectors are
undertrained, so PQ should lose less at production size, not more. `IVF_HNSW_PQ`
unrefined also measured 18/28 then 14/28 across two builds, because the graph
construction is randomised.

### Ingest cost

| measure | value |
| --- | --- |
| parse, mean per document | 101.9s |
| parse, median per document | 26.4s |
| parse, slowest document (232 pages) | 351.1s |
| parse, cached re-read | 0.01s (3,263× on a 34-page document) |
| vector index build, 4,739 rows | 2.6s |

Parse cost is heavily skewed: two 232-page documents account for 692s of the
1,121s total, so document-level parallelism is capped by the largest document.

### Corpus B — 10 documents, 3 annual + 7 sustainability, 2023–2025, 58.3MB

Deduplicated by content digest (three byte-identical pairs removed) but **not
yet ingested or scored**. Until it is, every number above describes one corpus
and one year, and none of them is evidence that the system generalises.

### Caveats that matter when reading the above

- **Stage 0 over-reports.** It compares with 1% tolerance *and* power-of-ten
  freedom across every block of every document, so `28/28` means "a number of
  that magnitude exists somewhere", not "the value is findable". Stages 2 and 3
  are narrower and trustworthy.
- **The `extra` bucket is not a win.** Those answers are unverified, and at
  least one is a known fabrication — a figure returned for a fuel the documents
  do not break out at all.
- **The reference itself is suspect, and it has now been audited.** Every
  disputed question was checked against the corpus for whether the reference
  value appears on a table row whose label relates to the question. Of 17, only
  **2** were genuinely ours to fix; 2 references are contradicted by the
  documents, 2 are printed nowhere at all, and 11 match no related row. The
  clearest case: total hazardous waste, reference `19.65`, which matches only a
  Scope 3 emissions category (`19,661` tonnes CO₂e) while the documents print
  `Total hazardous waste | Tonnes | 8,388` — the figure we returned and were
  scored wrong for. So `13/28` is a floor set partly by the ruler, not the
  system. Anything above roughly `14/28` cannot be earned without a corrected
  reference.
- **Repeat runs of an LLM stage are not independent** — completions are cached,
  so stage 3 run three times returns identical answers by construction.

The plan is in [`docs/backlog.md`](docs/backlog.md), the single source of
priority.

## Evaluation

Two independent measures, both required.

**Accuracy against a reference.** `config/suites.yaml` holds the `default`
suite — 89 questions with reference values, keyed by company and year.

```bash
uv run python experiments/score_suite.py --company acme --year 2025 --extractor docling
```

Outcomes are `match`, `mismatch`, `scale_mismatch`, `missed`, `abstained` and
`extra`. `extra` means a value was found where the reference is empty — a
candidate improvement for review, not an error.

**Answer quality.** deepeval judges faithfulness, answer relevancy and
contextual precision/recall. This separates "retrieval missed the passage" from
"the model had it and fumbled", and it is the only scorer for the qualitative
questions.

```bash
make eval COMPANY=acme YEAR=2025
```

The funnel runs stage by stage:

```bash
make stage0 COMPANY=acme YEAR=2025 PDF_DIR=/abs/dir   # parse recall
make stage1 COMPANY=acme YEAR=2025 PDF_DIR=/abs/dir   # figure recall
make stage2 COMPANY=acme YEAR=2025                    # retrieval recall
make stage3 COMPANY=acme YEAR=2025                    # end to end
make bench                                            # funnel report
```

Never report a single run of a stage that involves an LLM — the earlier
pipeline gave 16, then 12, then 13 on identical input.

## Config

`config/config.yaml` with `${ENV_VAR:-default}` expansion; secrets in `.env`.
No model name is hardcoded anywhere.

Storage is `./lancedb/` + `./cache/` locally, `gs://…` in prod.

## Development

```bash
make test      # unit tests, warnings fatal
make lint      # ruff check + format --check
make format
```

Conventions are in `AGENTS.md`. Open work is in
[`docs/backlog.md`](docs/backlog.md); designs in
[`docs/fact-layer.md`](docs/fact-layer.md) and
[`docs/prompt-profiles.md`](docs/prompt-profiles.md).
