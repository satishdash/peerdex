# peerdex

Agentic RAG over corporate reports. Personal project — treat it as restricted.

## Project

- **Stack:** Python 3.14, LlamaIndex, LanceDB, OpenAI, Typer. Package manager `uv` — every command is `uv run`, never bare `python`/`pytest`.
- **Pipeline:** extractor → chunker (+ VLM on figures) → OpenAI embeddings → LanceDB → one filtered search (dense by default) → extraction of the single figure, or cited synthesis for a qualitative question.
- **Every document is indexed as-is.** There is no document-type taxonomy, no report-type routing, no topic router. A `doc_id` is `sha256(company + file bytes)`, so re-indexing the same file replaces it and two files never collide.
- **A domain owns a table.** `-d <domain>` is required on every ingest and every query; it names the LanceDB table and the prompt set, and an unconfigured domain is refused rather than opening an empty table.
- **Metadata is open.** `company` is the only always-on filter. Everything else — `year`, `type`, `title`, `benchmark`, anything — is an attribute attached at index time (`-m k=v`) and filterable at query time (`-f k=v`). Dense and BM25 derive their predicate from the same `AttributeFilter`; never let them diverge. Booleans are stored as `1`/`0` because LlamaIndex `MetadataFilter` rejects `bool`.
- **Answer shape is decided by the question.** Quantitative question → the value alone, or `""` when the document does not state it. Qualitative question → prose. Never a hedge, never a narrative wrapper around a number.

## Layout

```
src/peerdex/
  parse/       extractors: docling, kreuzberg, odl, liteparse. All emit ExtractedDoc.
  chunk/       hierarchical parent/child chunker, VLM description of figures
  index/       LanceDB + LlamaIndex docstore, idempotent per doc_id
  retrieve/    PassageRetriever: one filtered LanceDB search, fts or vector
  agent/       bounded state machine (_agent), payloads and ports (_model), planning (_planner)
  quantity/    typed units and scale, and the arithmetic a question may ask for
  scoring/     pure answer-vs-reference comparison, evaluation only
  synthesize/  cited answer
  vlm/         OpenAI Vision describer + on-disk cache
  shared/      settings, prompts, ids, clients, cache, resilience, logging
config/        config.yaml (settings), suites.yaml (questions + ground truth)
tests/         fast unit tests, no network
experiments/   slow evaluation and benchmark harnesses, hit real APIs
```

## Commands

| Command | What it does |
| :--- | :--- |
| `make install` | `uv sync` |
| `uv run rag index <pdf-or-dir> -c <company> -d <domain> -y <year> [-e <extractor>] [-m k=v]` | Ingest one PDF or a directory of them |
| `uv run rag ask "<q>" -c <company> -d <domain> [-f k=v]` | One question |
| `uv run rag suite default -c <company> -d <domain> [-f k=v]` | Whole question suite |
| `make test` | Unit tests, warnings fatal |
| `make lint` / `make format` | ruff check + format |
| `make eval COMPANY=<c> YEAR=<y>` | deepeval judge suite (spends API credit) |
| `uv run python experiments/test_extractor_benchmark.py <dir-or-pdfs>` | Extraction benchmark |
| `uv run mypy src/peerdex/<module>.py` | Type check (strict) |

## Evaluation

`config/suites.yaml` holds the `default` suite: 89 questions with reference ground truth for 2023–2025 taken from a production extraction. A mismatch against it is a real miss, not a judgement call. `expected_answer: ""` means the document genuinely does not state the value, so returning any number there is a hallucination.

## Engineering guardrails

Non-negotiable. They outrank convenience and they outrank an existing file that violates them.

- **No comments.** Not section dividers, not explanations, not restatements of the code. Docstrings only: module, class, public method, one line where one line does. Never restate a type in a docstring.
- Acceptance criteria first, then logic correctness, then optimisation.
- SOLID. Strict hexagonal architecture: IO at the adapter edge, pure logic behind a public seam that tests drive without touching the outside world.
- Pure-Java-style OOP — real classes and polymorphism, not module-level function soup.
- OO design patterns wherever one genuinely applies. `parse/_liteparse.py` is the reference: Strategy per block kind, injectable gate, pure projector, adapter on top.
- Strict TDD: the failing test first, run it, confirm it fails for the right reason, then implement.
- Strict typing everywhere including local variables. Python 3.14 syntax. Never `from __future__ import annotations`.
- Cyclomatic complexity ≤ 3 per method.
- Consolidate and parameterise tests. Exhaustive assertions, exact counts (`== 3`, never `> 0`).
- Never test declarations — enums, schemas, dataclasses, exceptions. They are covered organically.
- Never test `_`-prefixed helpers. Drive them through the public seam.
- Reduce bloated logic and bloated tests rather than adding to them.
- Test files are `*_test.py`; test names are `test_given_<precondition>_when_<action>_then_<expected>`.
- Mock with the `mocker` fixture, never `@patch`. Never call a real API from `tests/`.
- Logging is `get_logger(__name__)` with f-strings. Never `print()`, never `%s` lazy formatting.

## Boundaries

- 🚫 `.env` holds live secrets. Never print, log, echo, copy or commit its contents.
- 🚫 Never push. Commit only, and only when asked.
- 🚫 Never hardcode an API key or a model name — models come from `config/config.yaml` and env overrides.
- ⚠️ Ask first before adding a dependency, a new extractor, or a managed cloud service.
