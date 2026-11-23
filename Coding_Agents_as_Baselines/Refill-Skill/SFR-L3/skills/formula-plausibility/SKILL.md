---
name: formula-plausibility
description: Criteria for judging whether a candidate formula for a target column is semantically plausible (domain, scale and type, circularity, hard-coded data). Use when you need to decide whether a proposed formula and its SQL make sense for the column.
---

# Formula plausibility

Assess whether a proposed formula for the target column is semantically plausible. The input is the textual formula and its SQL. A plausibility judgment is cheap and can save many executions on large tables.

## Criteria
- **Accept** if any reasonable derivation path exists for the column.
- **Reject** if the formula is domain-nonsensical (for example dividing name strings).
- **Reject** if the formula produces a type or scale mismatch with the column (for example it produces brand names for a person-name column, or future years for a birth-date column).
- **Reject** if the formula is circular on the target column: it reads the stored value of the target column itself, directly or inside a subquery, CTE, self-join, window function or aggregate, or it simplifies algebraically to the target column itself (for example `total = a - a + total`).
- **Reject** if the SQL or the formula uses hard-coded lists of specific data instances to derive the value, for example `FirstName IN ('Ann', 'Bob', ...)` or `ID IN (1, 3, 7, ...)`. This is data overfitting, not a schema-derived formula.
- **When in doubt, accept.** Only hard rejections are rejections; a mismatch with the data is not a plausibility question, it is settled by checking the formula against the stored values.

An implausible formula must not be reported as a result.
