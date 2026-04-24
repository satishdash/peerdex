# peerdex

Production-grade RAG over peer company reports. Hierarchical retrieval, cited answers, local-first, GCS-ready.

## Quick start

```bash
uv sync
export OPENAI_API_KEY=sk-...
uv run rag index path/to/report.pdf --company ACME --year 2025 --type annual_report
uv run rag ask "Total revenue?" --company ACME --year 2025
uv run rag suite annual --company ACME --year 2025
```

## Stack

Extractor (parse) → Chunker + VLM (pictures) → OpenAI embeddings → LanceDB → topic router + hybrid retrieval (dense + BM25 RRF) + LLM rerank → cited synthesis.

## Config

| File | Purpose |
|------|---------|
| `config/config.yaml` | All settings with `${ENV_VAR:-default}` expansion |
| `.env` | API keys, model names, URIs |
| `config/suites.yaml` | Q&A suites with ground truth |

## Extractors

Pluggable via `--extractor`:

```bash
uv run rag index report.pdf --company acme --year 2025 --type annual_report --extractor liteparse
```

| Extractor | Backend | Tables | Images | Requirements |
|-----------|---------|--------|--------|--------------|
| **docling** (default) | Python ML models (layout + table structure) | Structured | Yes | `docling` pip package |
| **odl** | OpenDataLoader Java + docling hybrid | Structured | No | `opendataloader-pdf[hybrid]`, Java 11+, hybrid server running |
| **liteparse** | PDF.js spatial text + Tesseract OCR | Flat text | No | Node.js 18+, `npm i -g @llamaindex/liteparse` |

### Extraction benchmark: Neste 2025 Annual Report (241 pages, 15 MB)

Apple M3 Pro, macOS. Run: `uv run python experiments/test_extractor_benchmark.py ~/Documents/neste_2025.pdf`

| Metric | liteparse | docling | odl (hybrid) |
|--------|-----------|---------|--------------|
| **Extraction time** | **35s** | 5m 29s | 7m 05s |
| Blocks | 242 | 2,913 | 3,604 |
| Tables | 0 | 269 | 258 |
| Images | 0 | 32 | 0 |
| Nodes indexed | 240 | — | 973 |

### Suite results: Neste 2025 Annual Report

`rag suite annual --company neste --year 2025`

| Question | Expected | liteparse | docling | odl |
|----------|----------|-----------|---------|-----|
| Total number of employees? | 3,743 | PASS | PASS | PASS |
| Total Revenue for 2025? | 17,065 (p.173) | FAIL | PASS | PASS |
| Total hours worked? | Correct refusal | PASS | PASS | PASS |
| **Result** | | **2/3** | **3/3** | **3/3** |

Liteparse lacks table structure — revenue on p.173 is inside a financial table that becomes flat text, causing retrieval miss. Docling and ODL both parse tables structurally and retrieve correctly.

## Evaluation

```bash
pytest experiments/ -v                    # all
pytest experiments/test_retrieval.py -v   # retrieval only
pytest experiments/test_synthesis.py -v   # synthesis only
```

## Storage

Local: `./lancedb/` + `./cache/`. Prod: swap to `gs://...` via config.
