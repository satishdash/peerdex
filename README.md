# peerdex

Agentic RAG over business PDFs. Ask a question, get the value or nothing.

Document-type agnostic: the code knows tables, charts, figures and prose, not
report kinds. A domain (`-d`) is one LanceDB table plus one prompt set.

## Quick start

```bash
uv sync
cp .env.example .env          # then set OPENAI_API_KEY
uv run rag index report.pdf -c acme -d corporate -y 2025
uv run rag ask "Gross global Scope 1 emissions" -c acme -d corporate -f year=2025
```

## How it works

```
INGEST   PDF → parse → chunk → describe figures → embed → LanceDB
ASK      question → plan → retrieve → extract → reflect → answer
```

| stage | what it does | key terms |
| --- | --- | --- |
| parse | PDF → typed blocks: heading, paragraph, table, list, picture. `docling` by default. Cached on file bytes + extractor. | `ExtractedDoc`, `TableBlock` |
| chunk | Hierarchical. Parent = one heading section or one table, ≤1,024 tokens. Child = 256-token sentence split, 32 overlap. Table children are row groups that repeat caption and header row. | `HierarchicalChunker`, `parent_chunk_tokens`, `child_chunk_tokens` |
| describe figures | A VLM turns each picture into text, indexed like prose. | `ingest_vlm_prompt`, `prompt_version` |
| embed + store | Children embedded at 1,536 dims into LanceDB table `<domain>` with an `IVF_PQ` vector index and a tantivy full-text index. Parents go to `<domain>_parents`, stored but not searched. | `index.vector_type`, `vector_refine_factor` |
| plan | Quantitative or qualitative. Bracketed arithmetic such as `(Scope 1 + Scope 2 + Scope 3)` becomes operands. | `QuestionPlanner`, `ArithmeticQuestion` |
| retrieve | One LanceDB call filtered by company and attributes. `vector` (default, refine factor 5) or `fts`. k=25. | `retrieval.query_type`, `final_top_k` |
| extract | One LLM call returns value, unit, scale and the column it read. Refused if that column states another period. Operands are combined as typed quantities. | `Quantity`, `UnitRegistry`, `DerivationEngine` |
| reflect | Nothing found → reword once, retry. Max 2 attempts, all recorded on the answer. | `QueryReformulator` |

A quantitative answer is the value alone, or an empty string, with unit and
page. A qualitative answer is prose with citations. Detail per stage in
[`docs/architecture.md`](docs/architecture.md).

## Documents

- `company` is the only fixed filter. Anything else is `-m key=value` at index
  and `-f key=value` at ask.
- `-d domain` is required. An unconfigured domain is refused.
- `doc_id = sha256(company + extractor + file bytes)`. Re-indexing replaces;
  extractor variants coexist.

## Extractors

| `-e` | notes |
| --- | --- |
| `docling` (default) | best table structure; 1,121 s over 11 PDFs |
| `liteparse` | 177 s |
| `kreuzberg` | text only; 7 s |
| `odl` | needs Java 11+ and `opendataloader-pdf-hybrid --port 5002` |

## Where it stands

End to end, 28 reference questions per corpus, k=25:

| corpus | documents | match |
| --- | --- | --- |
| A | 11 reports, one issuer, one year | 14/28 |
| B | 1 annual + 1 ESG report, one year | no reference values exist |
| C | 1 report, one year | 21/28 |

History, rejected options and the plan: [`docs/backlog.md`](docs/backlog.md).

## Evaluation

```bash
uv run python experiments/score_suite.py --company acme --year 2025 --extractor docling
make stage0 COMPANY=acme YEAR=2025 PDF_DIR=/abs/dir   # parse recall
make stage1 COMPANY=acme YEAR=2025 PDF_DIR=/abs/dir   # figure recall
make stage2 COMPANY=acme YEAR=2025                    # retrieval recall
make stage3 COMPANY=acme YEAR=2025                    # end to end
make bench                                            # funnel report
make eval   COMPANY=acme YEAR=2025                    # deepeval quality judges
```

Outcomes: `match`, `mismatch`, `scale_mismatch`, `missed`, `abstained`,
`extra`. Never report one LLM run; run three.

## Config

`config/config.yaml` with `${ENV_VAR:-default}` expansion; secrets in `.env`.
No model name is hardcoded. Storage is `./lancedb/` + `./cache/`.

## Development

```bash
make test      # unit tests, warnings fatal
make lint      # ruff check + format --check
make format
```

Conventions: `AGENTS.md`. Plan: `docs/backlog.md`. Designs:
`docs/fact-layer.md`, `docs/prompt-profiles.md`.
