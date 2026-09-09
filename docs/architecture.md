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
                                                        LanceDB rows + FTS index
                                                        docstore JSON
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

A PDF is a bag of positioned glyphs; it has no idea what a table is. Parsing is
what recovers the structure.

```
  page image / glyph stream
            │
            ├─ layout model      → what is a heading, a paragraph, a figure
            ├─ table model       → cell grid: which text is in which row/column
            └─ reading order     → the sequence a human would read in
            │
            ▼
   ExtractedDoc = [ Block, Block, ... ] + [ PageInfo, ... ]
```

Five block kinds, and nothing else. Deliberately the smallest set that covers
business documents:

| block | carries | why it exists |
| --- | --- | --- |
| `HeadingBlock` | text, level, page | gives every later block its section context |
| `ParagraphBlock` | text, page | prose answers, definitions, methodology notes |
| `TableBlock` | `headers`, `rows` (cell strings), `caption`, page | where the numbers live |
| `ListBlock` | items, ordered flag, page | bulleted disclosures |
| `PictureBlock` | the rendered **PIL image**, bbox area, page | charts, whose values exist only as pixels |

Every block also carries `page_no` and `heading_path` — the chain of ancestor
headings. That is what lets an answer cite a page, and lets a chunk know which
section it came from without re-walking the document.

**Four extractors implement the same contract** (`docling` by default, plus
`liteparse`, `kreuzberg`, `odl`), so they are swappable and directly comparable.
Downstream code never sees extractor internals.

**Parsing is cached** on the file's bytes plus the extractor's name and version.
Measured cold 39.82s versus warm 0.01s on a 34-page document. So changing the
chunker means re-indexing, never re-parsing. A version bump misses the cache
cleanly; a damaged entry is treated as a miss rather than an error.

## Stage 2 — chunk: blocks become retrievable units

A whole 200-page document is useless as a retrieval unit, and so is a lone
number. Chunking picks the size that can actually answer a question.

```
  a section with a table
            │
            ├──────────────► PARENT node: the whole table or section
            │                (full context, too big to rank well)
            │
            └──────────────► CHILD nodes: row groups, ~256 tokens each
                             (precise, what search actually matches)

   parent ◄──── CHILD relationship ────► child
   parent ◄──── PARENT relationship ──── child        (linked both ways)
```

**The critical detail: every table child repeats the header row and the
caption.** Without it a row group reads `| Scope 1 | 62,587 |` — no unit, no
year, unanswerable. With it:

```
  |        | Unit        | 2025   | 2024    | 2023    |
  | Scope 1| Tonnes CO₂e | 62,587 | 125,386 | 180,898 |
```

Row label, unit and period all survive in a chunk small enough to rank. This is
the single most important property of the chunker.

Ids are `<doc_id>:p<n>` for parents and `<doc_id>:c<n>` for children. The kind
letter is required, not optional — parents and children are numbered
independently, so without it a child could be handed its own id and become its
own parent.

## Stage 3 — describe figures: pixels become text

A chart's values are not in the PDF's text at all. A vision model reads the
image and writes what it shows, and that description becomes searchable like any
other text.

```
  PictureBlock.pil_image ──► vision model ──► "Revenue by region. North America
                                               43% ($25.5bn), Europe 22% …"
                                                        │
                                                        ▼
                                            stored as a chunk, cached by image
```

Small and edge-of-page images are skipped — area and header/footer band
thresholds — because those are logos and rules, not data.

## Stage 4 — embed and store

```
  child chunk text ──► embedding model ──► 1536-dim vector
                                                │
        ┌───────────────────────────────────────┴──────────────┐
        ▼                                                      ▼
  LanceDB table `peer_nodes`                          docstore JSON
  one row per CHILD chunk:                            parents + children
    id, text, vector, metadata struct                 with relationships
        │
        └─► FTS index (tantivy inverted index over `text`)
```

`metadata` is a struct, so filters push down into the database as SQL:
`metadata.company = '…' AND metadata.year = 2025`.

The table holds **children only**. Parents live in the docstore and are not on
the read path.

## Stage 5 — retrieve: narrow, then rank

```
  question ──► LanceDB
               .search(question, query_type="fts")     ← inverted index
               .where("metadata.company = … AND …")    ← SQL narrowing
               .limit(final_top_k)
                    │
                    ▼
             scored passages, each with its page
```

One step, **zero LLM calls**. `company` is always filtered; any other attribute
is optional, AND across keys and OR within a key.

## Stage 6 — extract: passages become one figure

```
  question + qualifiers (period, scope, unit)
  + passages
            │
            ▼
      one LLM call
            │
            ▼
   { "value": "62,587", "unit": "Tonnes CO₂e", "label": "Scope 1" }
            │
            ├─ label empty?  ──► refuse. A number nobody can attribute to a
            │                    printed row is how a neighbouring figure ends
            │                    up being returned as the answer.
            └─ value not a bare number? ──► refuse
```

`label` is the row label copied as printed. Requiring it is what stopped one
energy figure being returned for coal, natural gas and nuclear alike, in a
document that breaks out none of them.

**A quantitative answer is the value alone or an empty string** — never a hedge,
never prose around a number. Qualitative questions go to a synthesis step
instead and return prose. Both carry citations.

## Stage 7 — reflect: one bounded retry

```
  extract returned nothing
            │
            ▼
  reword the query from what came back ──► retrieve again ──► extract again
            │
            └─ still nothing after 2 attempts ──► refuse, with the reason
```

This is a deterministic retry, **not** a framework agent: no tool selection, no
scratchpad, no model deciding the next action. Every attempt is recorded on the
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

## What was removed, and why

Retrieval was deliberately stripped to a floor and each component measured
before being allowed back. Removed: dense (embedding) search, reciprocal-rank
fusion, an in-memory BM25 index, HyDE, multi-query expansion, an LLM reranker,
and `AutoMergingRetriever`.

Two were removed for cause rather than simplicity: `AutoMergingRetriever` looped
forever on one query and replaced precise row groups with whole tables, and the
LLM reranker plus query expansion made scores non-deterministic — 16, then 12,
then 13 on identical input.

The order for adding anything back is in `backlog.md`.

## One known inconsistency

**Embeddings are computed but never queried.** Ingest embeds every child chunk
and stores the vector, while retrieval uses full-text search only.

It is not merely unused, it is a loss: dense vector search measures **19/28**
against full-text's **17/28** on the reference questions, over three runs with
zero spread, and misses nothing full-text finds. The table also carries no
vector index, so that measurement was brute-force exact search. Switching
retrieval to vector, and indexing the column, is the next retrieval step in
`backlog.md`.
