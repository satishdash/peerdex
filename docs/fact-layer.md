# Fact layer

How peerdex stops guessing which passage holds a number, and starts knowing.

Written 2026-09-09 from measurements on the first corpus. Every number below is
observed, not estimated.

## The problem, in evidence

Retrieval returns text and hopes the ranking is right. Three failures follow,
and none of them is a property of one corpus.

**A number without its table outranks the table.** For "Gross global Scope 1
emissions" the correct row — a 544-character table on page 45 holding
`| Scope 1 | Tonnes CO₂e | 62,587 |` — ranked **20th**, score 13.1. First place,
score 16.33, went to a 75-character infographic callout on page 44:
`## 73,903 / gross Scope 1 and 2 GHG emissions`. BM25 divides by length, so a
caption beats a data table. Any document type with pull-quotes or callouts has
this.

**Lexical search cannot separate a metric from its neighbour.** "Scope 1 and 2"
matches a "Scope 1" query with nothing penalising the extra term. The general
shape is `X` versus `X and Y` — gross versus net, total versus per-unit,
inclusive versus excluding. Every domain has it.

**Some answers are not in the document at all.** Of eleven retrieval misses,
four have ground-truth values that appear nowhere in the PDF:

| question | ground truth | what the document states |
| --- | --- | --- |
| Total GHG (S1+S2+S3) | 6,271,593 | three separate rows; 62,587 + 11,316 + 6,197,690 |
| Total water consumption | 22.15022 | "water **withdrawal** … (million m³)" |
| Non-recycled waste | 20.282 | non-hazardous waste 15,022 **tonnes** |
| Non-renewable energy | 2951.76 | renewable and total, separately |

These are arithmetic and unit conversion. No chunker, ranker, reranker or
deduplication can find a number that was never written. **36% of the misses are
unreachable by retrieval of any quality.**

Deduplication, measured, moves a buried answer from rank 83 to 65 and 71 to 53.
Real, and nowhere near enough.

## The layering rule

The domain core is document primitives, and they are the same everywhere:
table, chart, figure, prose block, heading, key-value pair, page. An ESG report,
an invoice and a contract differ in what you want out, not in what they are made
of.

| layer | contents | varies by document type |
| --- | --- | --- |
| parse | primitives | no |
| chunk | self-contained retrieval units | no |
| **facts** | typed tuples with units and provenance | no |
| derivation | declarative rules over facts | rules only |
| prompt profile | schema wanted, questions asked, vocabulary | **yes** |

The invoice test settles any design argument: an invoice line is
`(label, value, unit, date, page)` — the same tuple as an ESG metric — and an
invoice total is a sum over lines, exactly like Total GHG. A mechanism that does
not serve both belongs in a profile, not in the core.

## The fact

One row per number the document states.

| field | why it exists |
| --- | --- |
| `label` | the row or line label as printed |
| `value` | the number, parsed |
| `unit` | `tonnes CO₂e`, `million m³`, `MWh`, `CAD` |
| `scale` | thousands, millions — printed in headers, lost today |
| `period` | the column the value sits under, not the file's year |
| `page` | provenance the answer cites |
| `primitive_id` | which table or chart it came from |
| `label_path` | parent headers, so `Scope 1` under `Market-based` stays distinct |
| `doc_id`, `extractor`, `prompt_version` | already how chunks are traced |

Stored as a second LanceDB table beside `peer_nodes`. Facts are additive: the
text path keeps working, and prose questions still use it.

**What changes at query time.** A metric lookup becomes a predicate on `label`
and `period`, not a BM25 ranking over 4,739 passages. `final_top_k` stops
mattering — it is currently 25 because one report needed 25, which is corpus
tuning and should not survive this design.

## Derivations

A sum is not intelligence, and an LLM should not be doing arithmetic in prose.
Derivations are data:

```
total_ghg      = sum(scope_1, scope_2, scope_3)
non_renewable  = total_energy - renewable_energy
intensity      = numerator / denominator
```

Each rule names the facts it consumes, so the answer carries every page it drew
from. Unit conversion is the same mechanism with a scale factor. Rules live in
the prompt profile because `total = sum(parts)` is universal but *which* parts
is not.

## Why this beats ground truth rather than matching it

Three distinct wins, all blocked today:

1. **Units.** We return `62,587 tonnes CO₂e`; the oracle stores `62587.0`. The
   unit is in the document and we currently throw it away.
2. **Coverage.** 86 quantitative questions exist and only 28 have a non-empty
   2025 value, so 58 are unanswered by the oracle. The fact table holds every
   row the document printed, not the subset a human filled in. `score_suite.py`
   already has an `extra` bucket for a value found where the oracle is empty.
3. **Disagreement we can defend.** Ground truth says water consumption is
   22.15022; the document says water *withdrawal*, in million m³. With a typed
   fact we can show the label, unit and page and argue the oracle is measuring
   something else. Today we can only be marked wrong.

## Path to 90%

Each step is gated on a measured number, on **two corpora**, and nothing
proceeds on one corpus alone.

| # | step | fixes | gate |
| --- | --- | --- | --- |
| 1 | second corpus ingested and scored | overfitting | any score reported for both |
| 2 | self-contained chunks: a bare number folds into its table or section | callout outranking tables | stage 2 recall, both corpora |
| 3 | fact extraction over table and key-value primitives | ranking irrelevant for metric lookup | exact-match rate per question |
| 4 | units and scale as typed fields | GT parity on units | unit present on every answer |
| 5 | derivation rules | the 36% arithmetic misses | those four questions answered |
| 6 | score- or coverage-based cutoff replaces `final_top_k` | corpus tuning | no fixed k in config |
| 7 | reranker, only if a gap remains | residual ranking errors | +N measured over 3 runs |

Step 7 is last on purpose. It costs an LLM call per question and made the
pipeline non-deterministic before (16, then 12, then 13 on identical input).
Fix the structure first and it may not be needed.

**Done when** answer accuracy is ≥90% on both corpora, every quantitative
answer carries a unit and a page, and no configuration value exists that was
chosen to make one document pass.

## Proving it is generic

The whole stage 0–3 funnel measures one company and one year, so every score
recorded so far is potentially overfitted. A second corpus is a prerequisite for
the design above, not a follow-up to it.

The second corpus is drawn from a different sector and a different reporting
framework: 10 unique PDFs, two document types (`Annual report`,
`Sustainability report`), three reporting years, each carrying a
sidecar `<id>.meta.json` shaped

```json
{ "<bucket_key>": { "title": null, "file_name": "...", "type": "Annual report",
                    "year": 2024, "bucket_key": "...", "url": "..." } }
```

Two properties of it are worth more than the extra questions, because both are
structural rather than corpus quirks:

**Documents duplicate at source.** The collection is assembled by a scraper
whose routing is probabilistic, so the same document arrives more than once
under different names. Comparing MD5 digests found three byte-identical pairs
out of thirteen files, one pair differing only by a trailing underscore in the
name. The first corpus had the same report in two PDFs, which was wrongly read
as a local accident. Deduplication belongs upstream in the scraper; downstream,
identity must be established by content digest, never by filename.

Name-based guessing is actively misleading here. Two documents in the same year
share a document type and an identical page count, and a filename reading would
call them duplicates — their text digests differ, and they are two distinct
reports.

**The sidecar year is not always the reporting year.** A file whose name carries
one year is tagged with the next, and a disclosure response published in one
year reports the prior year's figures. Publication year and reporting year are
different fields, and `period` on a fact must come from the table column, never
from the file.

Note that the code already drops a sidecar `year`: `year` is a reserved key, so
the value passed on the command line wins. Ingesting a mixed-year directory
therefore needs the sidecar year to become usable, not merely present.

## Open decisions

These change the build and are not mine to make.

1. **Which year is authoritative** for ingestion — the sidecar `year`, or the
   reporting period found in the document? They disagree in this corpus.
2. **Duplicate documents** — ingest all and deduplicate at fact level, or reject
   near-identical documents at ingest?
3. **Ground truth for the second corpus** comes from a local data service on
   port 8182, which needs that stack running and a mapping from its metric
   identifiers to suite questions.

## Keeping the repository generic

The project is intended to be open source, so no organisation name may appear in
it. Two places carry one today:

| place | tracked by git | contents |
| --- | --- | --- |
| `config/suites.yaml` | yes | 86 occurrences — the oracle is keyed by organisation |
| `results/funnel/*.json` | no, already ignored | run output, including extracted page text |

Only the first is a real exposure. The oracle is corpus data, not machinery: it
belongs outside the repository, with a small anonymised example checked in so
the format stays documented.

Note that `company` is a caller-supplied identifier throughout the code, never a
literal, so the machinery itself is already clean.
