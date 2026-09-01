# Roadmap

Deferred work, with enough detail to start cold. Nothing here begins until the funnel stages and evals are done.

## Pluggable prompt profiles

**Goal.** Any PDF can be ingested and answered well — an electricity bill, an invoice, a carbon disclosure — not only corporate reports. The machinery stays domain-free; only the prompt text is domain-specific and selected by an option.

**Already true.** Parse, chunk, index, retrieval mechanics and the rerank / synthesis / VLM steps carry no domain knowledge — they interpolate strings. The static annual/sustainability router is deleted, so nothing branches on document type. A non-report PDF indexes correctly today.

**The gap.** All domain knowledge lives in one `DocumentPrompts` value object, instantiated once as a module-level `PROMPTS` and imported directly by four modules. There is no seam to swap it.

| consumer | site | fields used |
| --- | --- | --- |
| fusion | `retrieve/_retriever.py:161` | `label`, `domain_brief`, `expansion_vocab` |
| reranker | `retrieve/_retriever.py:189` | `label`, `rerank_criteria` |
| HyDE | `retrieve/_retriever.py:221` | `label`, `domain_brief` |
| synthesis | `synthesize/_synth.py:124` | `label`, `synthesis_rules` |
| VLM describe | `vlm/_describer.py:117` | `ingest_vlm_prompt`, `prompt_version` |
| chunk metadata | `chunk/_chunker.py:154` | `prompt_version` |

**What answer quality looks like without it.** `expansion_vocab` steers HyDE toward scope 1/2/3, MD&A, GRI and SASB vocabulary the document does not contain, and `rerank_criteria` prefers financial statements and assurance statements that are not there. Both become dead signal.

### The constraint that shapes the design

The profile splits across two lifecycles.

| lifecycle | fields | chosen when |
| --- | --- | --- |
| query-time | `label`, `domain_brief`, `expansion_vocab`, `rerank_criteria`, `synthesis_rules` | per question |
| index-time | `ingest_vlm_prompt`, `prompt_version` | at ingestion, permanently |

The VLM prompt cannot be changed at query time — the figure was already described. `prompt_version` is already persisted on every chunk, so the profile that produced a chunk is recoverable and filterable. Reuse it rather than adding new provenance.

### Build

1. A registry of named `DocumentPrompts` profiles, `corporate report` staying the default.
2. Inject the resolved profile into the four consumers instead of importing `PROMPTS` directly.
3. `-p / --prompt-type` on `index` for the ingestion fields, and on `ask` and `suite` for the query fields.
4. Reject a query-time profile that does not match any indexed `prompt_version`, rather than answering from mismatched chunks.

**Done when** a non-report PDF indexed under its own profile answers correctly, the corporate-report path is byte-identical to today, and `make test` and `make lint` pass.

**Touches** `retrieve/_retriever.py` and `cli.py` — land any in-flight work on those first.
