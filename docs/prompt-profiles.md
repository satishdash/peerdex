# Pluggable prompt profiles

**Goal.** Any PDF can be ingested and answered well — an electricity bill, an
invoice, a carbon disclosure — not only corporate reports. The machinery stays
domain-free; only the prompt text is domain-specific, selected by an option.

**Already true.** Parse, chunk, index, retrieval, synthesis and the figure
description step carry no domain knowledge — they interpolate strings. Nothing
branches on document type, so a non-report PDF indexes correctly today.

**The gap.** All domain knowledge lives in one `DocumentPrompts` value object,
instantiated once as a module-level `PROMPTS` and imported directly by its
consumers. There is no seam to swap it.

## Consumers

Stripping retrieval to a single full-text step removed three of the six
consumers this design was originally written against. What remains:

| consumer | site | fields used |
| --- | --- | --- |
| synthesis | `synthesize/_synth.py:124` | `label`, `synthesis_rules` |
| figure description | `vlm/_describer.py:117` | `ingest_vlm_prompt`, `prompt_version` |
| chunk metadata | `chunk/_chunker.py:226` | `prompt_version` |

Three fields now have no reader at all — `domain_brief`, `expansion_vocab` and
`rerank_criteria` — because query generation, HyDE and the LLM reranker were
removed. They come back only if those components do.

This shrinks the work: there are three injection points, not six, and two of
them only need `prompt_version`.

## The constraint that shapes the design

The profile splits across two lifecycles.

| lifecycle | fields | chosen when |
| --- | --- | --- |
| query-time | `label`, `synthesis_rules` | per question |
| index-time | `ingest_vlm_prompt`, `prompt_version` | at ingestion, permanently |

The figure-description prompt cannot change at query time — the figure was
already described. `prompt_version` is persisted on every chunk, so the profile
that produced a chunk is recoverable and filterable. Reuse it rather than adding
new provenance.

## Build

1. A registry of named `DocumentPrompts` profiles, `corporate report` staying
   the default.
2. Inject the resolved profile into the three consumers instead of importing
   `PROMPTS` directly.
3. `-p / --prompt-type` on `index` for the ingestion fields, and on `ask` and
   `suite` for the query fields.
4. Reject a query-time profile that does not match any indexed `prompt_version`,
   rather than answering from mismatched chunks.

**Done when** a non-report PDF indexed under its own profile answers correctly,
the corporate-report path is unchanged, and `make test` and `make lint` pass.

## Where this sits

This is the seam that makes the system generic, and it pairs with the fact
schema in `fact-layer.md`: a profile says *what facts to want*, the fact layer
says *how they are stored*. Priority against everything else is in
`backlog.md` — it is not in the current plan's first steps, because raising
answer accuracy on documents we already handle comes first.
