# Backlog

The design is settled in `architecture.md`. Everything below follows from it.

| # | work | done when |
| --- | --- | --- |
| 1 | Evals per stage, so any part can be scored on its own | each stage reports a number, and a toggle can be turned on, measured, and kept or cut |
| 2 | Prompt profiles for non-report documents | a non-report PDF answers correctly under its own profile, with the report path unchanged |

Config is how a part gets cut. Every optional stage ships as a toggle, is scored
with it off and on, and only becomes a default once the number says so.

## Rules

- Never report a single run of anything involving an LLM. The old pipeline gave
  16, then 12, then 13 on identical input.
- A fix must be a property of the system, not of a corpus. A fixed top-k is
  corpus tuning; a score-based cutoff is a system property.
- Docling's output is not negotiable. Speed work may change when, where and how
  often it runs, never what it produces.
- The LanceDB table holds children only. Full-text and vector search both search
  children, where the numbers are.
- No document in this repository exceeds 400 lines.
