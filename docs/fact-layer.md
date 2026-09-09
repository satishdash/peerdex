# Units and derivations

Why some answers cannot be retrieved at all, and the smallest thing that fixes
it. Every number here is measured.

Originally designed as a general fact layer. De-scoped after review to the part
with a certain payoff: typed units and a derivation step. The reasoning for the
cut is at the end.

## The problem, in evidence

**Four of eleven retrieval misses have reference values that appear nowhere in
the document.**

| question | reference | what the document states |
| --- | --- | --- |
| Total GHG (S1+S2+S3) | 6,271,593 | three separate rows: 62,587 + 11,316 + 6,197,690 |
| Total water consumption | 22.15022 | "water **withdrawal** … (million m³)" |
| Non-recycled waste | 20.282 | non-hazardous waste 15,022 **tonnes** |
| Non-renewable energy | 2951.76 | renewable and total, separately |

These are arithmetic and unit conversion. No chunker, ranker, reranker or
deduplication can find a number that was never written.

**And units are thrown away.** The document says `62,587 Tonnes CO₂e`; the
reference stores `62587.0`. The unit is right there in the table header and we
discard it.

## The layering rule

The domain core is document primitives, and they are the same everywhere:
table, chart, figure, prose block, heading, key-value pair, page. A report, an
invoice and a contract differ in what you want out, not in what they are made
of.

| layer | varies by document type |
| --- | --- |
| parse | no |
| chunk | no |
| units and scale | no |
| derivation rules | rules only |
| prompt profile | **yes** |

The invoice test settles any design argument: an invoice line is
`(label, value, unit, date, page)` — the same tuple as a metric — and an invoice
total is a sum over lines, exactly like Total GHG. A mechanism that does not
serve both belongs in a profile, not in the core.

## What to build

**Typed units and scale on the answer.** The extraction step already returns a
value and a unit; neither is typed, and `scale` — the thousands or millions
declared in a table header — is not captured at all. Both belong on the answer
alongside the page, so `62,587 Tonnes CO₂e` survives instead of `62587.0`.

**A derivation step.** Rules are data, not code:

```
total_ghg      = sum(scope_1, scope_2, scope_3)
non_renewable  = total_energy - renewable_energy
intensity      = numerator / denominator
```

Each rule names the values it consumes, so the answer carries every page it drew
from. Unit conversion is the same mechanism with a scale factor. Rules live in
the prompt profile, because `total = sum(parts)` is universal but *which* parts
is not.

## Why this beats the reference rather than matching it

1. **Units.** We can return `62,587 Tonnes CO₂e` where the reference has
   `62587.0`.
2. **Coverage.** 86 quantitative questions exist and only 28 have a value for
   the year under test. `score_suite.py` already has an `extra` bucket for a
   value found where the reference is empty.
3. **Disagreement we can defend.** The reference says water consumption is
   22.15022; the document says water *withdrawal*, in million m³. With a typed
   unit and a page we can show the reference is measuring something else. Today
   we can only be marked wrong.

## Why the general fact layer was cut

The original design extracted a typed row per number in the document and made
metric lookup exact. Two objections held:

- **Exact lookup still needs a question-to-label mapping**, which is a retrieval
  problem again. It shrinks the haystack from 4,739 chunks to roughly 1,000
  labels — easier, not exact.
- **Dense vector search already recovered part of the same bucket for free** —
  19/28 against full-text's 17/28, with no build at all.

So the claim on the 7 "in the document but never retrieved" misses was weak,
while the claim on units and the 4 derived answers is solid. Only the solid part
survives, as step 5 of the plan in `backlog.md`.

**Done when** every quantitative answer carries a unit and a page, and the four
derived questions are answered from their parts.
