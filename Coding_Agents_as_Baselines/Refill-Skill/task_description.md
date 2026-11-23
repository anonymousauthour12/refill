You have read-only access to the database `{DATABASE}`, which runs on MySQL 8.0.46; the connection settings are in `config.json` in the current directory. The target is the column `{COLUMN}` of the table `{TABLE}`.

Skills in `.claude/skills` describe a methodology for this task (building the context, deciding whether the column is derived, proposing formulas, checking their plausibility, validating them and refining them). Before you start working, read every skill in that folder (invoke each one with the Skill tool) and apply what they say while you work.

## Your tasks

### Task 1: Understand the column semantics

You have access to the database. From it you can get the column name, data types and sample values, and identify the semantics of `{COLUMN}` given the table `{TABLE}` and the database context.

### Task 2: Determine whether the column is derived

Determine whether `{COLUMN}` is *derived*, i.e., whether it can be computed by a formula from other columns in the database `{DATABASE}`. The derivation can span multiple tables and is not limited to the table `{TABLE}`. Not every column is derived.

### Task 3: Discover the formula

If `{COLUMN}` is derived, discover its derivation formulas. A formula must be the actual derivation of the value (not an approximation or an estimate) and must be a general rule that applies to all rows.

A derived column can have multiple formulas, i.e., it can be derived in different ways (for example, from different columns or from different tables). Your task is to find all of them. Each formula must be a different derivation, not a rewrite of another.

Example: in a table `orders` with the columns `store_id`, `order_no`, `subtotal`, `tax`, `shipping` and `total_amount`, the column `total_amount` could be derived as `subtotal + tax + shipping`, or as the sum of `line_total` over the rows of the table `order_items` with the same `store_id` and `order_no`, plus `tax` and `shipping`.

A formula must not read the stored value of `{COLUMN}`, in any form. For example, `SELECT <primary key>, {COLUMN} AS derived FROM {TABLE}` is not allowed because it returns the stored value instead of a value computed by the derivation formula.

### Task 4: Compute the confidence

For each formula you discover, report its confidence. The confidence is the percentage of the values of `{COLUMN}` that conform to the formula.

## Deliverables

Save everything you generate in the folder `output` in the current directory.

If you conclude that `{COLUMN}` is not derived, create an empty file named `output/{DATABASE}.{TABLE}.{COLUMN}_not_derived.txt` and do not create any formula files.

Otherwise, if `{COLUMN}` is derived, save its formula as a single MySQL `SELECT` query in the file `output/{DATABASE}.{TABLE}.{COLUMN}_formula_1.sql`. If you find more than one formula, save each one in its own file, `output/{DATABASE}.{TABLE}.{COLUMN}_formula_2.sql`, `output/{DATABASE}.{TABLE}.{COLUMN}_formula_3.sql`, and so on.

Each query returns one row per row of `{TABLE}`: the primary key column(s) of `{TABLE}` and the value computed by your formula as `derived`.

Write the confidence of the formula (a number between 0 and 100) in the first line of its file, as the SQL comment `-- confidence: <number>`. Write in the second line the comment `-- validated on: full` if you validated the formula on all rows, or `-- validated on: sample` if you validated it only on a sample of the rows.

Example: for the column `total_amount` of the table `orders` in the database `shop` (composite primary key `(store_id, order_no)`), with the two formulas `subtotal + tax + shipping` and "the sum of `line_total` over the rows of `order_items` with the same `store_id` and `order_no`, plus `tax` and `shipping`", the two files are:

`output/shop.orders.total_amount_formula_1.sql`
```sql
-- confidence: 100
-- validated on: full
SELECT store_id, order_no, subtotal + tax + shipping AS derived
FROM orders
```

`output/shop.orders.total_amount_formula_2.sql`
```sql
-- confidence: 100
-- validated on: full
SELECT o.store_id, o.order_no,
       COALESCE(SUM(oi.line_total), 0) + o.tax + o.shipping AS derived
FROM orders o
LEFT JOIN order_items oi ON oi.store_id = o.store_id AND oi.order_no = o.order_no
GROUP BY o.store_id, o.order_no, o.tax, o.shipping
```

## Working mode

Work on your own until the task is done. There is nobody to answer questions, so do not ask any; if something is unclear, make the most reasonable choice and continue.
