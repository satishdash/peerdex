# peerdex

Agentic RAG over business PDFs. Ask a question, get the value or nothing.

Built to be document-type agnostic: the machinery knows about tables, charts,
figures and prose, not about any particular kind of report. What varies per
document type is the schema of facts wanted and the questions asked.

## Quick start

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY
uv run rag index report.pdf -c acme -y 2025
uv run rag ask "Gross global Scope 1 emissions" -c acme -f year=2025
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
uv run rag index report.pdf -c acme -y 2025 -m benchmark=true
uv run rag ask "Total water consumption" -c acme -f benchmark=true
```

Attributes also load automatically from a `<pdf-stem>.meta.json` sidecar.
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
| 3 end to end | final answer matches the reference | **12/28** | 11/28 |
| — | confidently wrong (`mismatch`) | **10** | 13 |
| — | abstained where a value exists (`missed`) | 6 | 4 |
| — | answered where the reference is empty (`extra`) | 32 | 35 |

**Dense retrieval finds more and answers worse.** It recovers two questions full
text cannot reach, yet end-to-end accuracy falls by one and confident errors
rise by three. The reason is visible in one case: asked for Scope 1 emissions,
dense search returns the correct table and the extractor reads `298,498` from
the `Baseline 2015` column instead of `62,587` from `2025`. Recall improved;
column discipline did not. Higher retrieval recall is not the same as a better
answer, and this table exists so that distinction cannot be glossed over.

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
- **The reference itself is suspect in places.** One question asks for total
  hazardous waste; the documents print `8,388 Tonnes` and the reference says
  `19.65`. Our answer was marked wrong. `results/gt_review.md` enumerates the
  candidates for every disputed question.
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
