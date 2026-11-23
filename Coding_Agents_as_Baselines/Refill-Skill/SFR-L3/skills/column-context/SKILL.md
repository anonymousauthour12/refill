---
name: column-context
description: How to gather and organise the context needed to reason about a target column - pruned schema and foreign-key graph, column statistics, distinct values, sample rows, and a semantic description of the target table. Use when you need to understand the database around a column.
---

# Column context

Role: database analyst. Use only read-only SQL (`SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`, `information_schema`).

## Schema, keys and the foreign-key graph
- The schema consists of the tables, the columns with their data types, the primary keys and the foreign keys (`information_schema`, `SHOW CREATE TABLE`).
- Model it as an undirected graph: tables are vertices, PK/FK relationships are edges (a self-referencing foreign key is an edge too).
- **Prune the graph**: keep only the tables within **3 foreign-key hops** of the target table (breadth-first search from the target table). Pruning keeps the context small, removes tables that distract, and keeps queries cheap.
- Foreign keys are not always declared. When a column pair looks like a key (same name and type, `x_id`, `parent_id`, `next_id`), treat it as a possible join.

## What the context contains
The context has three parts:
- the pruned schema (table and column names, data types, PK/FK constraints);
- column statistics: number of values, number of NULLs, number of distinct values, whether the column is categorical (few distinct values), and for numeric columns the minimum, maximum and average; plus **up to 5 distinct values** of each column;
- **5 sample rows** of each table (as they come, not selected for any pattern).

Sample large tables with `LIMIT`; do not dump them.

## Semantic description of the target table
Two short notes make the rest of the reasoning much easier:
- **Column meanings.** Describe every abbreviated or ambiguous column of the target table in under 20 words. Use the names of sibling columns, the foreign keys, the table name and the domain to resolve abbreviations. Skip columns that are self-explanatory.
- **In-table correlations.** Describe the mathematical, categorical or logical relationships between the target column and the other columns of the same table (using the column meanings). Do not speculate about other tables here. Write "none" if there are none.
