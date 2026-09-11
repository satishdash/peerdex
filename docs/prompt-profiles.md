# Pluggable prompt profiles

Goal: any PDF answers well with the same code. Only prompt text is
domain-specific, chosen by an option. Not built yet; priority in `backlog.md`.

## Today

Parse, chunk, index, retrieval and synthesis carry no domain knowledge. All
prompt text sits in one `DocumentPrompts` value, `PROMPTS`, imported directly.

| consumer | site | fields |
| --- | --- | --- |
| synthesis | `synthesize/_synth.py` | `label`, `synthesis_rules` |
| figure description | `vlm/_describer.py` | `ingest_vlm_prompt`, `prompt_version` |
| chunk metadata | `chunk/_chunker.py` | `prompt_version` |

Unread fields: `domain_brief`, `expansion_vocab`, `rerank_criteria`. They return
only with query expansion or an LLM reranker.

## Two lifecycles

| when | fields | chosen |
| --- | --- | --- |
| query time | `label`, `synthesis_rules` | per question |
| index time | `ingest_vlm_prompt`, `prompt_version` | at ingest; `prompt_version` is stored on every chunk |

## Build

1. Registry of named profiles; `corporate report` stays default.
2. Inject the profile into the three consumers.
3. `-p/--prompt-type` on `index` for ingest fields, on `ask` and `suite` for query fields.
4. Refuse a query profile that matches no indexed `prompt_version`.

Done when a non-report PDF under its own profile answers correctly and the
report path is unchanged.
