---
name: column-eligibility
description: How to decide whether a column is derived (computed from other data) or independently recorded, by trying to propose candidate formulas rather than answering yes or no. Use when you must judge whether a target column is derived at all.
---

# Column eligibility

Role: database engineer reverse-engineering computed columns from relational schemas.

No schema metadata distinguishes a derived column from an independently recorded one. Spending effort on a column that is not derived is wasteful, but declaring a derived column non-derived hides its formula for good, so a miss is the costlier mistake.

## How to judge
- Do not ask yourself a yes/no question: it invites a lazy "no". Instead try to **propose candidate formulas** for the target column, with a confidence for each (the confidences sum to 100 if you are uncertain).
- Use the PK/FK dependencies of the schema to explore derivation paths, also through joined tables. A derivation can span several tables.
- Look for aggregation (`SUM`, `COUNT`, `AVG`), arithmetic, string, date and conditional patterns.
- Use the column statistics and distinct values to confirm patterns, and the sample rows to check a formula against real data.
- Not every column is derived.

## Bias towards "derived"
If any plausible derivation path exists, including through joined tables, report it as a candidate even if you are uncertain, with a low confidence. Do not answer "none" just because you are unsure: propose the most likely formula with a low confidence instead. "None" is justified only if absolutely no derivation path exists.

## Retries
An identical question can give a different answer, and a first look can miss a path. Before declaring a column not derived, make up to **5 independent attempts**, each one starting from the context afresh. Only if all of them return no candidate is the column non-derived. If at least one attempt returns a candidate, the column is treated as computed.
