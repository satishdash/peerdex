# Architecture

How a PDF becomes an answer. Two flows: ingest, then ask.

## Ingest

Once per document, expensive, cached at both slow stages.

```
  ┌─────┐
  │ PDF │
  └──┬──┘
     ▼
 ┌──────────────────────────────────────────────┐
 │ PARSE                                        │   cache key:
 │  docling: layout · table · reading order     │ ◄─ file bytes
 │  → project to typed blocks                   │   + extractor
 │    heading|paragraph|table|list|picture      │   + version
 │  → drop tiny + header/footer images          │   + config
 │  every block: page_no + heading_path         │
 └───────────────────┬──────────────────────────┘
                     ▼
 ┌──────────────────────────────────────────────┐
 │ CHUNK                                        │
 │                                              │   cache key:
 │  1. describe ALL figures, one VLM batch      │ ◄─ image bytes
 │     (a figure's description IS its text)     │   + model
 │                                              │   + prompt ver
 │  2. cut into sections at each heading        │
 │     → flat list, reading order (no nesting)  │
 │                                              │
 │  3. per section, emit TWO LEVELS:            │
 │                                              │
 │     table  ─► PARENT   whole table           │
 │               CHILDREN row groups, caption   │
 │                        + header repeated     │
 │                                              │
 │     prose  ─► PARENT   section ≤1024 tok     │
 │               CHILDREN 256 tok, 32 overlap   │
 │                                              │
 │     figure ─► CHILD    VLM description       │
 │               (no parent of its own —        │
 │                points at the section parent) │
 │                                              │
 │  every child carries parent_id               │
 └──────────┬───────────────────────┬───────────┘
            │ children              │ parents
            ▼                       │
 ┌──────────────────────┐           │
 │ EMBED                │           │
 │  1,536-dim vector    │           │
 │  children only       │           │
 └──────────┬───────────┘           │
            ▼                       ▼
 ┌──────────────────────┐  ┌──────────────────────┐
 │ <domain>             │  │ <domain>_parents     │
 │ vector + FTS index   │  │ no vector, no index  │
 │ + parent_id ─────────┼─►│ fetched by id        │
 │                      │  │                      │
 │ SEARCHED at ask      │  │ read ONLY on         │
 │                      │  │ escalation (toggle)  │
 └──────────────────────┘  └──────────────────────┘
```

### Parse

A PDF is positioned glyphs; it does not know what a table is. Docling runs the
layout, table and reading-order models. Everything after that is projection: the
result becomes five block kinds, each stamped with its page and its ancestor
headings, so an answer can cite a page later.

Extractors are swappable behind one contract: `docling` (default), `docling-rs`,
`xberg`, `liteparse`, `odl`.

### Chunk

Figures are described first, in one batch, because a figure chunk's text *is* the
description — there is nothing to embed until the vision model has run.

Sections are then cut at each heading into a flat list. Section nesting is not
modelled; `heading_path` is a breadcrumb string, not a link.

Each section yields two levels, never more. The one rule that matters: **every
table child repeats the caption and the header row.** Without it a row group reads
`| Scope 1 | 62,587 |` — no unit, no year, unanswerable. With it:

```
  |        | Unit        | 2025   | 2024    | 2023    |
  | Scope 1| Tonnes CO₂e | 62,587 | 125,386 | 180,898 |
```

### Embed and store

Children become 1,536-dimension vectors. Parents are stored without a vector and
are never searched — they are fetched by `parent_id`, and only when extraction
abstains. That escalation is a config toggle, so it can be cut without a revert.

Metadata is a struct, so a filter pushes into the database as SQL rather than
being applied in Python afterwards.

## Ask

Static. Two attempts at most, no agent, no loop. Every path is the same length
every time, which is what makes a toggle measurable.

```
                    ┌──────────────────────┐
                    │  question + kind     │
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  ROUTE               │   quantitative | qualitative
                    │                      │   + period
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  FIND ①             │   filter → search → rerank → top k
                    │                      │   one database call
                    └──────────┬───────────┘
                               ▼ passages
                    ┌──────────────────────┐
                    │  READ ①             │   value · unit · row label · column
                    │                      │   (or one call per operand)
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │  RESOLVE ①          │   gates · units · combine
                    │                      │   no model
                    └──────────┬───────────┘
                               │
           ┌───────────────┴───────────────┐
        passed                        refused — why?
           │                                  │
           │              ┌────────────────┴────────────────┐
           │         no passages                    found, no value
           │              │                                │
           │              ▼  toggle:                      ▼  toggle:
           │     ┌────────────────┐              ┌────────────────┐
           │     │  REWRITE       │              │  FETCH PARENT  │
           │     │  lexical, from │              │  by id,        │
           │     │  what came back│              │  no search     │
           │     └───────┬────────┘              └───────┬────────┘
           │             ▼                               │
           │          FIND ②                             │
           │             │                               │
           │             └──────────┬────────────────┘
           │                        ▼
           │             ┌─────────────────────┐
           │             │  READ ② · RESOLVE ②  │  final attempt
           │             └──────────┬───────────┘
           │                        │
           │            ┌──────────┴──────────┐
           │         passed                 refused
           ▼            ▼                      ▼
   ┌──────────────────┐          ┌──────────────────┐
   │answer + citations│          │ refusal + reason │
   └──────────────────┘          └──────────────────┘
```

### Route

The caller declares `kind`, so nothing is inferred and nothing is paid for. It
selects the answer's shape, not the question's meaning: the same question asked
as `quantitative` returns a bare value, as `qualitative` returns prose. Only the
former is scoreable.

### Find

One database call does all four steps. The filter is a SQL predicate on stored
metadata, so it narrows before ranking rather than discarding after. Search mode
and reranker are settings:

| mode | none | rrf | cross-encoder |
| --- | --- | --- | --- |
| fts | ✓ | ✗ | ✓ |
| vector | ✓ | ✗ | ✓ |
| hybrid | ✓ | ✓ | ✓ |

Reciprocal-rank fusion merges two ranked lists by position, so it needs hybrid to
have two. A cross-encoder re-reads the question and passage text together and
scores the pair, which is why it works on one list or two, and why it can only
run over a shortlist.

### Read

One call returns the value **and the evidence for it**:

```
  { "value": "62,587", "unit": "Tonnes CO₂e", "label": "Scope 1", "column": "2025" }
```

The label and column exist so the next stage can catch the model out. Asking a
model whether it was right returns yes; asking which row and column it read
returns something testable.

Where the question names arithmetic — `Total GHG (Scope 1 + Scope 2 + Scope 3)` —
each operand is extracted separately from the passages already in hand. That
costs one call per operand and no further search.

### Resolve

No model. Everything here is decidable:

```
  { value, unit, label, column }
            │
            ├─ no row label?                 ──► refuse
            ├─ column states another period? ──► refuse
            ├─ value is not a bare number?   ──► refuse
            └─ operands present?             ──► combine as typed quantities
```

The asked-for period comes from the `year` filter, not from the question text,
which usually contains no year. Only a column that actually states a period is
judged — a `Female` column over a board count states none.

Operands combine as typed quantities, converting units before adding. If two
dimensions will not combine, nothing is derived and the single extracted figure
stands.

A quantitative answer is the value alone. Never a hedge, never prose wrapped
around a number. A refusal carries its reason.

### Cost

| | |
| --- | --- |
| embeddings | 1 |
| LLM calls | 1, or 2 on escalation |
| reranking | 0 calls — local or arithmetic |
| toggles | search mode · reranker · top k · escalate on refusal |

### Why static

An agent would replace the fixed branch with a chosen move: reword the query,
widen the filter, stop early. That is more capable and less predictable, and the
same question can then take different paths on different runs. A toggle cannot be
measured against a control that varies. Agents come after the toggles are scored,
not before.

## Evaluation

```
  suite ──► ask ──► answers ──► compare ──► buckets ──► scores
  gitignored         │            │
                     │            ├─ strict  0.001 absolute
                     │            └─ native  1% relative, scale aware
                     ├─► stored, rescored without asking again
                     └─► find alone · recall@k · ndcg@k · expected_pages · no model
```

| reference | answer | bucket |
| --- | --- | --- |
| a value | the same, or the alternate | good |
| a value | another | wrong |
| a value | none | missed |
| "" | none | silent |
| "" | any | invented |

```
  precision       = good / (good + wrong + invented)
  positive recall = good / (good + wrong + missed)
  negative recall = silent / (silent + invented)

  native  match | mismatch | scale_mismatch | missed | abstained | extra
          scale_mismatch → wrong   abstained → silent   extra → invented

  companies averaged unweighted · never a single run · never on the serving path
```

## Configuration

`config/config.yaml`, with `${ENV_VAR:-default}` expansion. Secrets in `.env`.
No model name is hardcoded.

| concern | key |
| --- | --- |
| embedding model | `embed.model` |
| passages returned | `retrieval.final_top_k` |
| search mode | `retrieval.query_type` |
| vector index type | `index.vector_type` |
| parent and child size | `chunker.parent_chunk_tokens`, `chunker.child_chunk_tokens` |
