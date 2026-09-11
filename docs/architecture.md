# Architecture

What the system does today, stage by stage. Kept in text so it diffs in review
and cannot drift out of date unnoticed.

## The whole thing at a glance

```
 INGEST  (once per document)
 ┌──────┐   ┌───────┐   ┌───────┐   ┌──────────┐   ┌───────┐   ┌───────┐
 │ PDF  │──►│ parse │──►│ chunk │──►│ describe │──►│ embed │──►│ store │
 └──────┘   └───────┘   └───────┘   │ figures  │   └───────┘   └───────┘
                │                   └──────────┘                   │
            cached on                                              │
          bytes+extractor                                          ▼
                                                LanceDB rows + FTS + vector index
                                                `<domain>_parents` rows
 ─────────────────────────────────────────────────────────────────────────────
 ASK  (once per question)
 ┌──────────┐   ┌──────┐   ┌──────────┐   ┌─────────┐   ┌────────┐
 │ question │──►│ plan │──►│ retrieve │──►│ extract │──►│ answer │
 └──────────┘   └──────┘   └──────────┘   └─────────┘   └────────┘
                               ▲                │
                               │      no value found, so
                               └──── reflect: reword and retry (max 2)
```

Ingest is expensive and happens once. Asking is cheap: **one** database query
and **one** LLM call in the common case.

## Stage 1 — parse: a PDF becomes typed blocks

```
  page image / glyph stream
            │
            ├─ layout model      → heading, paragraph, figure
            ├─ table model       → cell grid
            └─ reading order     → human reading sequence
            ▼
   ExtractedDoc = [ Block, ... ] + [ PageInfo, ... ]
```

| block | carries |
| --- | --- |
| `HeadingBlock` | text, level, page |
| `ParagraphBlock` | text, page |
| `TableBlock` | `headers`, `rows`, `caption`, page |
| `ListBlock` | items, ordered flag, page |
| `PictureBlock` | PIL image, bbox area, page |

- Every block carries `page_no` and `heading_path` (ancestor headings): page
  citations and section context.
- Four extractors, one contract: `docling` (default), `liteparse`, `kreuzberg`, `odl`.
- Parse is cached on file bytes + extractor name and version. Cold 39.82 s, warm
  0.01 s on 34 pages. A damaged entry is a miss, not an error.

## Stage 2 — chunk: blocks become retrievable units

```
  a section with a table
            │
            ├──► PARENT: whole table or section, ≤1,024 tokens,
            │            stored in `<domain>_parents`, not searched
            └──► CHILD:  row groups or sentence splits, 256 tokens, 32 overlap,
                         embedded and searched

   parent ◄──── linked both ways ────► child
```

Every table child repeats caption and header row, so label, unit and period
survive in a chunk small enough to rank:

```
  |        | Unit        | 2025   | 2024    | 2023    |
  | Scope 1| Tonnes CO₂e | 62,587 | 125,386 | 180,898 |
```

Ids: `<doc_id>:p<n>` for parents, `<doc_id>:c<n>` for children. They are
numbered independently, so the kind letter is required.

## Stage 3 — describe figures: pixels become text

```
  PictureBlock.pil_image ──► vision model ──► "Revenue by region. North America
                                               43% ($25.5bn), Europe 22% …"
                                                        │
                                                        ▼
                                            stored as a chunk, cached by image
```

Small and edge-of-page images are skipped (area and header/footer band
thresholds): logos and rules, not data.

## Stage 4 — embed and store

```
  child chunk text ──► embedding model ──► 1536-dim vector
                                                │
        ┌───────────────────────────────────────┴──────────────┐
        ▼                                                      ▼
  LanceDB table `<domain>`                         LanceDB table `<domain>_parents`
  one row per CHILD chunk:                         one row per PARENT chunk:
    id, text, vector, metadata struct                id, text, metadata struct
        │
        ├─► FTS index    (tantivy inverted index over `text`)
        └─► vector index (IVF_PQ over `vector`)
```

- Both indexes are built after every ingest; no-ops if present. Vector index
  parameters derive from row count: partitions near √rows, sub-vectors dividing
  the embedding width.
- `metadata` is a struct, so filters push down as SQL:
  `metadata.company = '…' AND metadata.year = 2025`.
- Only children are searched. Parents are written per document and not yet read.

## Stage 5 — retrieve: narrow, then rank

Two modes, selected by `retrieval.query_type`. One database call either way.

```
  FULL TEXT (query_type: fts)          DENSE (query_type: vector)  ← default
  ──────────────────────────           ──────────────────────────
  question, verbatim                   question ──► embedding model
        │                                                │  (one API call)
        ▼                                                ▼
  .search(text, "fts")                 .search(vector, "vector")
  .where(<SQL on metadata>)            .where(<SQL on metadata>)
  .limit(final_top_k)                  .refine_factor(5)   ← see below
        │                              .limit(final_top_k)
        │                                     │
        └──────────────┬──────────────────────┘
                       ▼
         scored passages, each with its page
```

`company` is always filtered; any other attribute is optional, AND across keys
and OR within a key.

**Measured on the metric suite, k=25, three runs each with zero spread:**

| mode | hits |
| --- | --- |
| full text | 17/28 |
| dense, exact (no index) | 19/28 |
| dense, IVF_PQ index, no refinement | 17/28 |
| **dense, IVF_PQ index, `refine_factor=5`** | **19/28** |

## Stage 6 — extract: passages become one figure

```
  question + qualifiers (period, scope, unit) + passages
            │
            ▼
      one LLM call
            │
            ▼
   { "value": "62,587", "unit": "Tonnes CO₂e", "label": "Scope 1", "column": "2025" }
            │
            ├─ label empty?                   ──► refuse
            ├─ column states another period?  ──► refuse
            └─ value not a bare number?       ──► refuse
```

`column` matters because a correct row label still leaves one figure per period:

```
  |        | Baseline 2015 | 2024    | 2025   |   ← asked for 2025
  | Scope 1|   298,498     | 125,386 | 62,587 |
```

- The asked-for period comes from the `year` filter, not the question text.
- Only a column that states a period is judged. A `Female` column holding a
  board count states none; demanding one refused two correct answers.
- Quantitative: the value alone or an empty string. Qualitative: a synthesis
  step returning prose. Both carry citations.

A question that spells the arithmetic out is derived; nothing else is:

```
  "Total GHG emissions (Scope 1 + Scope 2 + Scope 3)"
            │
            ▼
  operands extracted from the retrieved passages ──► 62,587 t  108,000 t  6,100,000 t
            │   typed unit + scale, converted before adding
            ▼
      6,270,587 t      any operand missing, or dimensions that do not combine
                       ──► derive nothing, fall back to the printed figure
```

Magnitudes are `Decimal`. Units live in `peerdex.quantity`, which also converts
the result to the unit the question states.

## Stage 7 — reflect: one bounded retry

```
  extract returned nothing
            │
            ▼
  reword the query from what came back ──► retrieve again ──► extract again
            │
            └─ still nothing after 2 attempts ──► refuse, with the reason
```

Deterministic retry, not a framework agent. Every attempt is recorded on the
answer.

## How it is scored (evaluation only, never the serving path)

```
  reference value ──┐
                    ├─► compare ──► match | mismatch | scale_mismatch
  our answer   ─────┤              | missed | abstained | extra
  our unit     ─────┘
```

- 1% relative tolerance, so `100.9` matches `100`.
- Power-of-ten aware: `58,739` against `58,739,000,000` is a `scale_mismatch`.
- **The unit can confirm that scale.** Reported in `$m`, that same answer is a
  `match` — the unit was the missing evidence. A unit never rescales on its own,
  and a magnitude after `per` is ignored because it belongs to the denominator.
- `extra` means we produced a value where the reference is empty. That is a
  candidate improvement awaiting review, **not** a proven win.

## Configuration

`config/config.yaml`, with `${ENV_VAR:-default}` expansion. Secrets in `.env`.
No model name is hardcoded anywhere.

| concern | key |
| --- | --- |
| embedding model | `embed.model` |
| agent and extraction model | `llm.model` |
| synthesis model | `llm.synth_model` |
| evaluation judge | `llm.judge_model` |
| figure description model | `vlm.model` |
| chunk sizes | `chunker.parent_chunk_tokens`, `chunker.child_chunk_tokens` |
| passages returned | `retrieval.final_top_k` |
| search mode | `retrieval.query_type` |
| vector index type | `index.vector_type` |
