# Architecture

What the system does today. Kept in text so it diffs in review and cannot drift
out of date unnoticed.

## Ingest

```
PDF ──► extract ──► chunk ──► describe figures ──► embed ──► store
        docling     parent/   VLM                  OpenAI    LanceDB  + docstore
        (default)   child                                    (rows)     (JSON)
                                                                │
                                                                ▼
                                                          FTS index
                                                          (tantivy, over `text`)
```

| step | what it produces | notes |
| --- | --- | --- |
| extract | `ExtractedDoc` — text, table and picture blocks with page numbers | four interchangeable extractors, chosen with `-e` |
| chunk | a parent per table or section, children per row group or sentence split | every table child repeats the header row and caption, so a row stays answerable alone |
| describe | a text description per figure, including chart values | cached; searchable like any other text |
| embed | one vector per child chunk | **see the note below — nothing queries these** |
| store | child rows in LanceDB, parents and children in the docstore | `doc_id` is content-addressed, so re-indexing replaces cleanly |

## Query

```
question ──► plan ──► retrieve ──► extract ──► reflect ──► answer + citations
                         │                        │
                         │                        └─ retry with a reformulated
                         │                           query, bounded at 2 attempts
                         ▼
              ONE LanceDB full-text search
              .search(q, query_type="fts")
              .where(<SQL predicate on metadata>)
              .limit(final_top_k)
```

Retrieval is a single step and makes **zero LLM calls**. The reasoning lives in
the agent, which plans, reformulates and retries. `company` is always filtered;
any other attribute is optional, AND across keys and OR within a key.

A quantitative question returns the value alone or an empty string — never a
hedge, never prose around a number. A qualitative question returns prose. Both
carry citations.

## Stores

| store | holds | used by |
| --- | --- | --- |
| LanceDB table `peer_nodes` | child chunks: `id`, `text`, `vector`, `metadata` struct | full-text search, metadata predicates |
| tantivy FTS index | inverted index over `text` | every retrieval |
| docstore JSON | parents and children with relationships | not on the read path |

`metadata` is a struct, so filters push down as SQL: `metadata.company = '…'`,
`metadata.year = 2025`.

## What was removed, and why

Retrieval was deliberately stripped to a floor and each component measured
before being allowed back. Removed: dense (embedding) search, reciprocal-rank
fusion, an in-memory BM25 index, HyDE, multi-query expansion, an LLM reranker,
and `AutoMergingRetriever`. Two of them were removed for cause rather than
simplicity: `AutoMergingRetriever` looped forever on one query and replaced
precise row groups with whole tables, and the LLM reranker plus query expansion
made scores non-deterministic — 16, then 12, then 13 on identical input.

The order for adding anything back is in `backlog.md`.

## One known inconsistency

**Embeddings are computed but never queried.** Ingest embeds every child chunk
through the embedding API and stores the vector, while retrieval uses full-text
search only — a real cost per document buying nothing today.

It is not just unused, it is a loss: dense vector search measures **19/28**
against full-text's **17/28** on the reference questions, over three runs with
zero spread, and misses nothing full-text finds. The table also carries no
vector index at all, so that measurement was brute-force exact search. Switching
retrieval to vector, and indexing the column, is step 4 in `backlog.md`.

The nine settings left behind by the retrieval strip — three `retrieval` keys,
three `llm` model keys and three `DocumentPrompts` fields — have been deleted.

## Live configuration

`config/config.yaml`, with `${ENV_VAR:-default}` expansion. Secrets in `.env`.

| concern | key |
| --- | --- |
| embedding model | `embed.model` |
| agent and extraction model | `llm.model` |
| synthesis model | `llm.synth_model` |
| evaluation judge | `llm.judge_model` |
| figure description model | `vlm.model` |
| chunk sizes | `chunker.parent_chunk_tokens`, `chunker.child_chunk_tokens` |
| passages returned | `retrieval.final_top_k` |

No model name is hardcoded anywhere; every one comes from config or an
environment override.
