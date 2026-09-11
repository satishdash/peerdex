# Units and derivations

Shipped as step 5. Every quantitative answer carries a typed unit and a page.
A question that spells out arithmetic is derived from its operands.

## Rule

The core is document primitives: table, figure, prose, heading, page. A report,
an invoice and a bill share them. What differs goes in a prompt profile.

| layer | varies by document type |
| --- | --- |
| parse, chunk, units and scale | no |
| derivation rules | rules only |
| prompt profile | yes |

## Design

- `UnitRegistry` maps header text to a `Unit` with a `Dimension` and an exact
  factor to canonical. Energy canonical is GJ, so 1 MWh = 3.6 exactly. Text
  with a denominator (`per`, `/`) resolves to nothing.
- `Quantity` = Decimal magnitude + `Unit`. `.to(unit)` converts inside one
  dimension; across dimensions raises `IncompatibleUnitsError`.
- `ArithmeticQuestion` reads bracketed arithmetic with one operator kind.
  `DerivationEngine` applies `Sum`, `Difference` or `Ratio`.
- The agent derives first, extracts second, then converts to the unit the
  question states.

## Measured

- Total GHG (S1+S2+S3) derived exactly as 6,271,593 t, a figure printed nowhere.
- Corpus A: 0 of 16 failures were unit or scale errors. Units are the seam a
  second domain needs, not an accuracy win.
- A general fact layer (one typed row per number) was cut. Exact lookup still
  needs question-to-label matching, and dense search already recovered that bucket.
