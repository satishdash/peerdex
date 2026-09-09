# peerdex

Agentic RAG over corporate reports. Ask a question, get the value or nothing.

## Quick start

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY
uv run rag index report.pdf -c acme -y 2025
uv run rag ask "Gross global Scope 1 emissions" -c acme -f year=2025
```

## How it works

```
PDF → extractor → chunker (+VLM on figures) → embeddings → LanceDB
                                                              ↓
question → plan → retrieve (dense + BM25 RRF, HyDE, LLM rerank) → extract → reflect → answer
```

The agent retries with a reformulated query when the first pass misses, bounded at two attempts. Every attempt is recorded on the answer.

**A quantitative question returns the value alone, or an empty string.** Never a hedge, never prose around a number. A qualitative question returns prose. Both carry citations.

## Documents

Every document is indexed as-is — no report-type taxonomy, no routing. `company` is the only fixed filter. Everything else is an attribute:

```bash
uv run rag index report.pdf -c acme -y 2025 -m benchmark=true
uv run rag ask "Total water consumption" -c acme -f benchmark=true
```

Attributes also load automatically from a `<pdf-stem>.meta.json` sidecar. `doc_id` is `sha256(company + extractor + file bytes)`, so re-indexing a file replaces it and extractor variants coexist for comparison.

## Extractors

`-e docling` (default), `liteparse`, `kreuzberg`, `odl`. All emit the same `ExtractedDoc`, so they are swappable and comparable.

`odl` additionally needs Java 11+ and `opendataloader-pdf-hybrid --port 5002` running.

Measured on 11 PDFs from a single issuer. Parse recall does not separate them — every extractor reaches every value the oracle holds — so the choice is made on latency.

| extractor | text extracted | parse errors | oracle values reached | parse time |
| --- | --- | --- | --- | --- |
| `kreuzberg` | 2,674,607 chars | 0 | 28/28 (26 exact, 2 scale) | 7 s |
| `liteparse` | 1,917,146 chars | 0 | 28/28 (26 exact, 2 scale) | 177 s |
| `docling` | 1,613,930 chars | 0 | 28/28 (26 exact, 2 scale) | 1,121 s |
| `odl` | N/A | N/A | N/A | not run — huge latency (~59 min) |

Oracle-reached counts are provisional while the ground-truth values are under review.

```bash
uv run python experiments/test_extractor_benchmark.py ~/Documents/reports
```

## Evaluation

Two independent measures, both required.

**Accuracy against ground truth.** `config/suites.yaml` holds the `default` suite — 89 questions with reference values for 2023–2025 taken from a production extraction.

```bash
uv run python experiments/score_suite.py --company acme --year 2025 --extractor liteparse
```

Outcomes are `match`, `mismatch`, `scale_mismatch`, `missed`, `abstained`, and `extra`. `extra` means we found a value the ground truth marks unavailable — a candidate improvement for review, not an error.

**Answer quality.** deepeval judges faithfulness, answer relevancy and contextual precision/recall. This is what separates "retrieval missed the passage" from "the model had it and fumbled", and it is the only scorer for the qualitative questions.

```bash
make eval COMPANY=acme YEAR=2025
```

## Config

`config/config.yaml` with `${ENV_VAR:-default}` expansion; secrets in `.env`.

Storage is `./lancedb/` + `./cache/` locally, `gs://...` in prod.

## Development

```bash
make test      # unit tests, warnings fatal
make lint      # ruff check + format --check
make format
```

Conventions live in `AGENTS.md`. Deferred work is in `docs/roadmap.md`.
