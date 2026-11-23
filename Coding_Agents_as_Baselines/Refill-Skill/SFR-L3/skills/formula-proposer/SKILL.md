---
name: formula-proposer
description: How to propose candidate SQL formulas for a column that is known to be derived, by reading the schema, the column statistics, the distinct values and the sample rows. Use when you need to find formulas for a derived column.
---

# Formula proposer

Role: SQL developer generating verification queries for derived columns. Assume the column **is derived**: do not answer "not derivable". Propose as many realistic candidates as you can, **up to 10** (an explicit target makes you generate more candidates than you would without one, and the upper bound keeps hallucinated nonsense out). A column can have several valid formulas (different source columns or tables); keep every candidate that reaches a confidence of 80 or more.

## What a candidate is
A textual formula plus a computation SQL: a MySQL `SELECT` that returns the primary key column(s), `computed_value` (the predicted value) and `actual_value` (the stored value of the target column, for checking), with the target table aliased `target_table` in the outer `FROM`. List the tables and columns the formula directly uses (only the formula-relevant ones, not the tables that only serve as join intermediates). Give each candidate a confidence between 0 and 100 (the confidences sum to 100).

## Where candidates come from
Work from the context: the pruned schema with its PK/FK relationships, the column statistics and distinct values, and the sample rows. Candidates may use other columns of the target table or other tables. Explore 1-hop, 2-hop and 3-hop-or-more joins along the PK/FK paths. This works best for formulas that follow from a straightforward reading of the schema or of a small number of sample values.

## Rules for every candidate
- **Never read the target column** anywhere in the SQL: not through `target_table`, not through another alias of the target table, not inside a subquery or CTE, and not wrapped in an aggregate (`MAX`, `MIN`, `SUM`, ...): wrapping it does not make it valid. The value must be derived from other columns only; reading it to predict itself is circular.
- **No data-fitting.** Do not hard-code specific data instances (names, IDs, years, enumerated row-level values) in `IN (...)` lists or `CASE WHEN` conditions to derive the value, and do not use constants fitted to the data. The formula must follow structural logic (keys, joins, aggregations), not memorised data. Forbidden: `CASE WHEN FirstName IN ('Ann', 'Bob', ...) THEN 'F'`.
- **Aggregate inside a subquery.** Do not aggregate a `LEFT JOIN` value directly. Wrong: `SELECT a.id, SUM(i.amount) FROM account a LEFT JOIN income i ON ...`. Right: `SELECT a.id, total.value AS computed_value FROM account a LEFT JOIN (SELECT account_id, SUM(amount) AS value FROM income GROUP BY account_id) AS total ON a.id = total.account_id`. A formula can combine several such subqueries (for example `total_income.value - total_outcome.value`).
- Cast `UNSIGNED` columns to `SIGNED` before arithmetic that can go negative. Use `LIKE` for string comparison, never `FIND_IN_SET` or `REPLACE`. Rounding is not required.
- Write efficient SQL: `JOIN` with `GROUP BY` instead of correlated subqueries; avoid `COUNT(*)` or `ORDER BY ... LIMIT` inside a correlated subquery on a large table.
- Discard semantically equivalent formulas and keep one representative; keep separate the formulas that are really different derivations (a different source attribute or table, or a really different way of getting the value).
- Valid MySQL only.
