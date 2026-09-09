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
PDF → extract → chunk (+VLM on figures) → embed → LanceDB + FTS index

question → plan → retrieve (one LanceDB full-text search) → extract → reflect → answer
```

Retrieval is a single step and makes zero LLM calls; the reasoning lives in the
agent, which plans, reformulates the query from what came back, and retries —
bounded at two attempts, with every attempt recorded on the answer.

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

Measured end to end on one corpus, 28 questions that have a reference value:

| stage | measures | result |
| --- | --- | --- |
| 0 parse | reference value present in extracted text | 28/28 — **but see the caveat** |
| 1 figures | values reachable only via figure descriptions | +0 |
| 2 retrieval | value present in the retrieved passages | **17/28** (15 exact, 2 unit-scale) |
| 3 end to end | final answer matches the reference | **12/28** |

Beyond those 28, the suite holds 58 questions whose reference value is empty.
The agent produced a value for 34 of them. Those are candidate improvements on
the reference, and they have **not been verified yet**.

**Caveat on stage 0.** It compares numbers with a 1% tolerance and power-of-ten
freedom, across every block of every document. That is loose enough to match an
unrelated figure of similar magnitude, so `28/28` means "a number of that
magnitude exists somewhere", not "the value is findable". Stage 2 and 3 are
narrower and trustworthy.

The plan to raise 12/28 is in [`docs/backlog.md`](docs/backlog.md), which is the
single source of priority.

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
