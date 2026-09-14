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
src/
  parse/       extractors: docling, docling-rs, xberg, odl, liteparse. All emit ExtractedDoc.
  chunk/       hierarchical parent/child chunker, VLM description of figures
  index/       LanceDB child rows and parent rows, idempotent per doc_id
  retrieve/    PassageRetriever: one filtered LanceDB search, fts or vector
  agent/       bounded state machine (agent), payloads and ports (model), planning (planner)
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
| `make install` | `uv sync --all-extras` |
| `uv run rag index <pdf-or-dir> -c <company> -d <domain> -y <year> [-e <extractor>] [-m k=v]` | Ingest one PDF or a directory of them |
| `uv run rag ask "<q>" -c <company> -d <domain> [-f k=v]` | One question |
| `uv run rag suite default -c <company> -d <domain> [-f k=v]` | Whole question suite |
| `make tests` | Unit tests, warnings fatal |
| `make lint` / `make format` | ruff check + format |
| `uv run python experiments/score_suite.py --company <c> --year <y> --extractor <e>` | Score the suite end to end (spends API credit) |
| `uv run python experiments/test_extractor_benchmark.py <dir-or-pdfs>` | Extraction benchmark |
| `uv run ty check src/<module>.py` | Type check |

## Evaluation

`config/suites.yaml` holds the `default` suite: 89 questions with reference ground truth for 2023–2025 taken from a production extraction. A mismatch against it is a real miss, not a judgement call. `expected_answer: ""` means the document genuinely does not state the value, so returning any number there is a hallucination.

## Engineering guardrails

Non-negotiable. They outrank convenience and they outrank an existing file that violates them.

### Structure

- **Nothing at module scope but imports, classes, the module docstring, type aliases and `__all__`.** No module-level function, no module-level variable, no module-level call. A logger, a compiled pattern and a constant are all class state — `_LOG: ClassVar[...]`, not `log = get_logger(...)`.
- No leading underscore on a **module** filename. No leading underscore on a **class** name. Functions and methods may keep one for private.
- Public methods first inside a class, private and protected after.
- Every package has `__init__.py`, `tests/` included.
- Flat `src/` layout. No distribution sub-package inside it.
- Every document in this repository stays under 400 lines.

### Enforcement

- Google docstrings in **full form** on module, class and every method, private included, and on Protocol stubs: every parameter in `Args:`, every non-`None` return in `Returns:`, every raise in `Raises:`. Wording stays minimal — one line per entry, never restating a type.
- ruff (`D` + `DOC`, `convention = "google"`, `preview = true`) checks the summary, `Returns:` and `Raises:`, and a partly filled `Args:` block. **No ruff rule requires an `Args:` section to exist**, so that one is checked by hand on every method that takes a parameter.
- **`C901` is never ignored.** A `per-file-ignores` entry of `["C901"]` is debt to be deleted, never renamed to a new path and never carried forward. A function over complexity 3 is decomposed, never exempted, never `# noqa`. When a stage is refactored, its C901 ignore goes in that same stage's work.
- Measure real complexity with the ignores bypassed: `uv run ruff check --isolated --select C901 --config 'lint.mccabe.max-complexity=3' <path>`.
- A red lint is an acceptable intermediate state while a stage is being converted. Never weaken a rule to make it green.
- Fix any violation your own change introduces, inside that same change.

### Design

- Acceptance criteria first, then logic correctness, then optimisation.
- SOLID, complete DDD, strict hexagonal: IO at the adapter edge, pure logic behind a public seam that tests drive without touching the outside world.
- Pure-Java-style OOP — real classes and polymorphism, not module-level function soup.
- OO design patterns wherever one genuinely applies. `parse/liteparse.py` is the reference: Strategy per block kind, injectable gate, pure projector, adapter on top. The gold standard outside this repo is the sp utils package in platform svc and processr_upload in the core orchestrator benchmarking pipeline.
- Cyclomatic complexity ≤ 3 per method.
- Strict typing everywhere including local variables. Python 3.14 syntax. Never `from __future__ import annotations`.
- **No comments.** Not section dividers, not explanations, not restatements of the code. Applies to `.py`, `.toml` and `.yaml` alike. Docstrings only: module, class, public method, one line where one line does. Never restate a type in a docstring. Protocol property stubs still get a docstring.
- Logging is `get_logger(__name__)` with f-strings. Never `print()`, never `%s` lazy formatting.
- Reduce bloated logic rather than adding to it.

### Tests

- Strict TDD: the failing test first, run it, confirm it fails for the right reason, then implement.
- Files are `*_test.py`; names are `test_given_<precondition>_when_<action>_then_<expected>`.
- Consolidate and parameterise. Exhaustive assertions, exact counts (`== 3`, never `> 0`).
- Never test declarations — enums, schemas, dataclasses, exceptions. They are covered organically.
- Never test `_`-prefixed helpers. Drive them through the public seam.
- Mock with the `mocker` fixture, never `@patch`. Never call a real API from `tests/`.

## Boundaries

- 🚫 `.env` holds live secrets. Never print, log, echo, copy or commit its contents.
- 🚫 Never push. Commit only, and only when asked. A commit message is one line, sentence case, present-tense third-person verb, no prefix, no scope, no body, no trailer; several concerns join with `+`. Show the draft before committing.
- 🚫 Never hardcode an API key or a model name — models come from `config/config.yaml` and env overrides.
- ⚠️ Ask first before adding a dependency, a new extractor, or a managed cloud service.
