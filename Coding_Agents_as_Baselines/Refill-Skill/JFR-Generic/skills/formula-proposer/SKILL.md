---
name: formula-proposer
description: How to propose candidate SQL formulas for a column that is known to be derived - a broad discovery of formulas that use only the target table or other tables, and how to pick the rows that reveal each formula (single-table formulas and cross-table formulas). Use when you need to find formulas for a derived column.
---

# Formula proposer

Role: SQL developer generating verification queries for derived columns. Assume the column **is derived**: do not answer "not derivable". Keep every candidate that reaches a confidence of 80 or more; a column can have several valid formulas (different source columns or tables).

## What a candidate is
A textual formula plus a computation SQL: a MySQL `SELECT` that returns the primary key column(s), `computed_value` (the predicted value) and `actual_value` (the stored value of the target column, for checking), with the target table aliased `target_table` in the outer `FROM`. List the tables and columns the formula directly uses (not the tables that only serve as join intermediates; a formula that uses only the target table lists only that table).

## Discovery of formulas
Work from the context (pruned schema, statistics, distinct values, sample rows, table description) and look for formulas of any kind, up to **10 candidates**, each with a confidence between 0 and 100 (summing to 100):
- a formula may use only other columns of the **target table** (a single-table formula): a same-row expression, or window, aggregate or self-join logic over other columns of the table;
- it may use **other tables** via joins (multi-hop joins are allowed: 2-hop, 3-hop and more, following the PK/FK paths);
- or both.

Single-table formulas are allowed and encouraged when the column can be computed from other columns of its own table; do not add a table that the formula does not need. Never propose a formula that reads the target column itself (for example `MAX(target_column) GROUP BY pk`); that is circular.

## Rows that reveal a single-table formula
Look at about **10 rows of the target table with one row per distinct value of the target column** (a window function partitioned by the target column; leave out rows where the target is NULL), so that the co-variation between the target column and its predictors is visible. If the rows are too many to reason about, halve their number (down to 2). Then write the formula and its SQL over the target table only. Window functions and self-joins over **other** columns are allowed, for example to reach a related row of the same table, as long as they do not read the target column.

## Rows that reveal a cross-table formula
- Group the cross-table candidates by the **set of tables** they need (remove duplicates and redundant sets, merge sets that share the same tables) and prefer the sets with the **fewest tables**. Find the join path that connects the target table to the tables of the set through the foreign-key graph; skip sets whose path spans more than **4 tables** (they overflow the context and time out).
- Choose about **10 target rows** that (a) have **at least 2 related rows in every table of the set**, (b) cover **different values of the target column** (one row per distinct target value where possible), and (c) have **few related rows overall**, so that the context stays compact. If there are not enough such rows, relax the requirement to at least 1 related row.
- Show, for each table of the join path, the **related rows of the chosen target rows** (distinct rows, with a cap of about 1000 per table), and in addition about 10 **standalone rows of the target table** (independent rows, not via the join).
- Some tables of a set may be useless: use the rows to see which ones matter.

## SQL rules for cross-table formulas
- The target table appears **exactly once**, as `target_table` in the outer `FROM`. No self-join, and no derived table (subquery) in a join that reads the target table, even under another alias. A query that reads only the target table, through window functions, self-aggregation or derived subqueries, is not a cross-table formula.
- Use only the tables of the set, with explicit `JOIN`s from `target_table`.
- **Aggregate inside a subquery** and join it; never aggregate a `LEFT JOIN` value directly. Wrong: `SELECT a.id, SUM(i.amount) FROM account a LEFT JOIN income i ON ...`. Right: `SELECT a.id, total.computed_value FROM account a LEFT JOIN (SELECT account_id, SUM(amount) AS computed_value FROM income GROUP BY account_id) AS total ON a.id = total.account_id`. Always alias the computed column as `computed_value` inside the subquery and select it as `subquery_alias.computed_value AS computed_value`.

## Rules for every candidate
- **Never read the target column** anywhere in the SQL: not through `target_table`, not through another alias of the target table, not inside a subquery, CTE, self-join or window function, and not wrapped in an aggregate (`MAX`, `MIN`, `SUM`, ...): wrapping it does not make it valid. The value must be derived from other columns only.
- **No data-fitting.** Do not hard-code specific data instances (names, IDs, years, enumerated row-level values) in `IN (...)` lists or `CASE WHEN` conditions to derive the value, and do not use constants fitted to the data. The formula must follow structural logic (keys, joins, aggregations), not memorised data. Forbidden: `CASE WHEN FirstName IN ('Ann', 'Bob', ...) THEN 'F'`.
- Cast `UNSIGNED` columns to `SIGNED` before arithmetic that can go negative. Use `LIKE` for string comparison, never `FIND_IN_SET` or `REPLACE`. Rounding is not required.
- Write efficient SQL: `JOIN` with `GROUP BY` instead of correlated subqueries; avoid `COUNT(*)` or `ORDER BY ... LIMIT` inside a correlated subquery on a large table.
- Discard semantically equivalent formulas and keep one representative; keep separate the formulas that are really different derivations (a different source attribute or table, or a really different way of getting the value).
- Valid MySQL only.
