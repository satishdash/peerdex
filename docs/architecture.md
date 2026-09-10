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
        ├─► FTS index    (tantivy inverted index over `text`)
        └─► vector index (IVF_PQ over `vector`)
```

Both indexes are built after every ingest and are no-ops if already present.
The vector index's parameters are **derived from the row count** — partitions
near √rows, sub-vectors dividing the embedding width — because a pair tuned on
one corpus is wrong for the next.

`metadata` is a struct, so filters push down into the database as SQL:
`metadata.company = '…' AND metadata.year = 2025`.

The table holds **children only**. Parents live in the docstore and are not on
the read path.

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

Dense finds everything full text finds, plus two more. The index without
refinement gives that gain straight back — see the first boulder below.

## Stage 6 — extract: passages become one figure

```
  question + qualifiers (period, scope, unit)
  + passages
            │
            ▼
      one LLM call
            │
            ▼
   { "value": "62,587", "unit": "Tonnes CO₂e",
     "label": "Scope 1", "column": "2025" }
            │
            ├─ label empty?  ──► refuse. A number nobody can attribute to a
            │                    printed row is how a neighbouring figure ends
            │                    up being returned as the answer.
            ├─ column states another period? ──► refuse. See below.
            └─ value not a bare number? ──► refuse
```

`label` is the row label copied as printed. Requiring it is what stopped one
energy figure being returned for coal, natural gas and nuclear alike, in a
document that breaks out none of them.

`column` is the same evidence along the other axis, and it is needed because a
correct row label still leaves one figure per period to choose from:

```
  |        | Baseline 2015 | 2024    | 2025   |   ← asked for 2025
  | Scope 1|   298,498     | 125,386 | 62,587 |
              └─ answered this, under the correct label `Scope 1`
```

The asked-for period arrives from the `year` filter, not from the question —
`Gross global Scope 1 emissions` contains no year, so reading the period from
the question text alone left this unfixable. Only a column that *states* a
period is judged: a `Female` column holding a board count states none, and
demanding a period of it refused two correct answers when measured.

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
| search mode | `retrieval.query_type` |
| vector index type | `index.vector_type` |

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

## Rocks and boulders

The things that will bite someone reading this code for the first time. Every
one was found the hard way.

**Full text and dense return opposite polarities.** Full text gives `_score`
(higher is better); dense gives `_distance` (lower is better). Reading only
`_score` scores every dense hit zero and leaves citations in arbitrary order —
silently, with no error. Both are normalised in one place, `_relevance`.

**Product quantisation silently costs recall.** IVF_PQ compresses each 1536-dim
vector from 6,144 bytes to 96 — 64× — which is what makes a large corpus fit,
and it loses the fine distinctions. Measured: 19/28 exact, 17/28 indexed.
`refine_factor` re-ranks the top candidates against the *uncompressed* vectors
and restores 19/28. **Never run IVF_PQ without it.**

**`nprobes` was not the knob.** 20 versus 68 partitions probed made no
difference, which proves the loss was compression and not partition pruning. It
becomes the recall knob at a size where partitions number in the thousands.

**The table holds children only** — zero parents in 4,739 rows. Coarse-to-fine
hierarchical search is therefore impossible without changing what is stored.

**LanceDB reports an index type in its own spelling.** The setting says
`IVF_PQ`; `list_indices()` says `IvfPq`. Comparing them verbatim is always
false, so the "already indexed?" guard never fired and every ingest silently
rebuilt the whole vector index — 2.6s on 4,739 rows, and tens of minutes at
millions. Compare with underscores stripped and case folded, and select the
index by its *column*, or the full-text index over `text` gets mistaken for it.

**Switching index type is a rebuild, not a migration.** The index is derived
from the stored `vector` column, so changing `index.vector_type` costs one
rebuild and touches no rows, no schema and no embeddings. Verified live by
switching to `IVF_HNSW_SQ` and back, after which the repeat call is a 4.8ms
no-op. Whether queries are served *during* a rebuild is untested.

**`create_index` takes the column from a positional argument named `metric`.**
The modern-looking `create_index(config=FTS(), vector_column_name="text")` fails
with `Field path 'l2' not found`, which explains nothing. Pass `metric=`,
`vector_column_name=` and `index_type=` explicitly.

**The parse cache must be pickle, not JSON.** `PictureBlock` carries a live PIL
image that the figure stage consumes; a JSON round-trip loses it.

**Cache IO resolves through one seam at call time.** `from peerdex.shared import
cache` then `cache.fs_and_root()`, never `from …cache import fs_and_root` — a
direct import binds at import time, defeats patching, and will write to the real
filesystem from inside a test.

**Stage 0's recall number over-reports.** It compares with 1% tolerance *and*
power-of-ten freedom across every block of every document, so it once counted a
goodwill figure as waste tonnage. Read it as "a number of that magnitude exists
somewhere", not "the value is findable".

**An extraction with no row label is a refusal.** Otherwise a plausible
neighbouring figure gets returned — one energy number was answered for coal,
natural gas and nuclear alike in a document that breaks out none of them.

**The asked-for period is a filter, not words in the question.** `plan.period`
comes from a regex over the question text, and most questions state no year, so
anything keyed on it silently does nothing. The period is taken from the `year`
filter, and a filter naming several years yields none — there is then no single
period to check a column against.

**A guard that judges too much costs accuracy.** Requiring the extracted column
to match the period looks right until a column is not a period at all: two
correct board-member counts under a `Female` header were refused. Only columns
that state a period are judged. Measured both ways — 10 matches against 12.

**Scoring must read the unit.** `58,739` reported in `$m` looks a millionfold
wrong against `58739000000` until the unit is consulted.

**Repeat runs of an LLM stage are not independent.** Completions are cached, so
running stage 3 three times returns identical answers by construction. The
three-run rule earns its keep on uncached comparisons like the retrieval modes.
