# peerdex

RAG over business PDFs. Ask a question, get the value or nothing.

Document-type agnostic: the code knows tables, charts, figures and prose, not
report kinds. A domain (`-d`) is one LanceDB table plus one prompt set.

## Quick start

```bash
make install                  # then set OPENAI_API_KEY in .env
uv run rag index report.pdf -c acme -d corporate -y 2025 -e docling-rs
uv run rag ask "Gross global Scope 1 emissions" -c acme -d corporate -f year=2025
```

## How it works

```
INGEST   PDF → parse → chunk → embed → LanceDB
ASK      question → route → find → read → resolve → answer | refusal
```

A quantitative answer is the value alone, or nothing, with unit and page. A
qualitative answer is prose with citations. Both flows, stage by stage, in
[`docs/architecture.md`](docs/architecture.md).

## Documents

- `company` is the only fixed filter. Anything else is `-m key=value` at index
  and `-f key=value` at ask.
- `-d domain` is required. An unconfigured domain is refused.
- `doc_id = sha256(company + extractor + file bytes)`. Re-indexing replaces;
  extractor variants coexist.
- A document the extractor cannot read is skipped, with its traceback written to
  `cache/dlq/<doc_id>/parse.json`. One bad PDF does not stop a directory ingest.

## Extractors

All emit the same `ExtractedDoc`, so they are swappable. One run over 16 PDFs,
946 pages, 78 MB:

| `-e` | time | tables | table cells | figures | text |
| --- | --- | --- | --- | --- | --- |
| `docling` (default) | 779 s | 874 | 40,924 | 435 | 2.23 M |
| `docling-rs` | 416 s | 886 | 42,742 | 418 | 2.23 M |
| `liteparse` | 283 s | 1,076 | 39,908 | 341 | 2.52 M |
| `xberg` | **23 s** | 660 | 19,447 | 376 | 3.62 M |
| `odl` | not run | | | | |

Speed decides nothing. What decides is whether a value survives parsing with its
row label, unit and period intact.

- `docling-rs` matches docling's output at roughly twice the speed, but panics on
  a non-breaking space in a heading when `heading_hierarchy` is on
  ([issue 377](https://github.com/docling-project/docling.rs/issues/377)). Not the
  default until that is fixed. Needs a pdfium shared library; point
  `docling.pdfium_lib_path` at a local build.
- `liteparse` splits one table into many, losing the row-label and header
  structure a value needs.
- `xberg` finds the text and loses the structure. Its table models never engage
  on a digital PDF, and no config knob changes that.
- `odl` needs Java 11+ and `opendataloader-pdf-hybrid --port 5002`.

## Evaluation

Suite: `config/suites.yaml` (gitignored; start from `config/suites.example.yaml`), keyed
`<company code> -> <year> -> expected_answer`. Index each company under its code.

```bash
make eval COMPANY=<code> YEAR=<year>                        # answers replay from $PEERDEX_EVAL_DIR
make eval COMPANY=<code> YEAR=<year> EVAL_FLAGS=--rescore   # score only, no model calls
```

Outcomes: `good`, `wrong`, `missed`, `silent`, `invented`. An empty reference
scores hallucination: answering it is `invented`.

Never report one LLM run; run three.

## Config

`config/config.yaml` with `${ENV_VAR:-default}` expansion; secrets in `.env`.
No model name is hardcoded. Storage is `~/.cache/peerdex/`.

Every optional stage is a toggle, scored off and on before it becomes a default.

## Development

```bash
make tests     # unit tests, warnings fatal
make lint      # ruff check + format --check
make format
```

Conventions: `AGENTS.md`. Design: `docs/architecture.md`.

## License

AGPL-3.0-or-later, see `LICENSE`. A commercial license for closed or hosted use
is available from the author.
