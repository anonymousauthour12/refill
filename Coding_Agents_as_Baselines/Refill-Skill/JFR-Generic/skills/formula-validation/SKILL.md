---
name: formula-validation
description: How to validate a candidate formula against the database - executing it and fixing SQL errors, computing its confidence (the percentage of stored values it reproduces), the self-reference check, and validation on a sample for expensive queries. Use when you must measure how well a candidate formula reproduces the stored values.
---

# Formula validation

The live database is the correctness oracle: it is exact and needs no labelled data. Use read-only SQL.

## The computation SQL
A candidate is a `SELECT` over the target table (aliased `target_table` in the outer `FROM`) that returns the primary key column(s), the predicted value as `computed_value` and the stored value of the target column as `actual_value`. (In the file you finally write, follow the task description: the primary key columns and the predicted value as `derived`.)

## Executing and fixing errors
Run the query. If it fails, read the error and fix the query: preserve its intent, change only the syntax or the structure, keep it compatible with the schema. Allow up to **5 attempts**; if it still fails, drop the candidate.

## Confidence
Compare predicted and stored values for the rows whose **stored value is not NULL**:
- `matches` are the rows where `actual_value = computed_value`; `mismatches` are all the other rows;
- **confidence = 100 * matches / (matches + mismatches)**;
- for a **floating-point column**, round both values to the number of decimals of the stored value before comparing (a stored `3.25` means comparing at 2 decimals);
- rows where the prediction is NULL (for example no related rows) are **left out of the count**: the confidence is computed over the rows where both the stored value and the prediction are not NULL.

```sql
SELECT 100 * SUM(actual_value = computed_value) / COUNT(*) AS confidence
FROM ( /* computation SQL */ ) AS t
WHERE actual_value IS NOT NULL AND computed_value IS NOT NULL;
```

A candidate is an **accepted formula** when its confidence is at least **80**, it is plausible, and it passes the self-reference check.

## Self-reference check (null perturbation)
A formula that reads the very value it predicts gets a misleadingly high confidence, and fails exactly when that value is missing. To detect it, take the expression that produces `computed_value`, replace **every** reference to the target column in it by `NULL`, and add the result as a second column `computed_value_null` of the same query. A row is self-referential if the original prediction matches the stored value but `computed_value_null` does not equal the stored value (use the NULL-safe `<=>`). If **any** row is self-referential, the confidence of the formula is **0**: discard it. A formula that does not mention the target column passes trivially. This check is skipped when validating on a sample.

## Expensive queries: validation on a sample
- Run `EXPLAIN` on the validation query. If it shows that the query is expensive (a full table scan, `type = ALL`, of a large table), do not run it on all rows. Validate on the first **1000 rows** of its result: wrap it as `SELECT * FROM (computation SQL) AS p LIMIT 1000` and compute the confidence on that. The formula you keep is the full query without the `LIMIT`.
- If a query times out or the connection is lost, switch once to this 1000-row validation and run again. If it times out again, drop the candidate.
- A confidence from a sample is approximate: label the formula as validated on a sample.

## Recording an accepted formula
Record the SQL, its confidence, and whether it was validated on the full data or on a sample. In the formula file, write the label as the second comment line, right after the confidence line:

```sql
-- confidence: 92
-- validated on: full        (or: sample)
SELECT ...
```
