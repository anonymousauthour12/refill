# DCR-Synthetic

185 derived columns added to 10 public databases from the CTU relational repository. The formula of every column is known by construction.

## Files

- `gt.csv`: one row per column, with `db_name`, `table_name`, `column_name`, `formula_textual_description`, `formula_sql`, `complexity_level` (easy, medium, hard) and `pattern` (row-scope, chaining, hierarchical, aggregation, across-tables, window, string-embedded join, multi-hop). There are 40 easy, 84 medium and 61 hard columns.
- `alter_tables.sql`: adds the 185 columns (all NULL).
- `populate_values.sql`: fills them with the values given by the formulas.
- `prepare_lahman_2014_S.sql`: removes one player from the copy of `lahman_2014` (see below).

## formula_sql

A formula returns `computed_value`, the value given by the formula, next to `actual_value`, the value stored in the column. For the 34 columns defined by iterative algorithms the formula is a script that builds temporary tables and ends with the final `SELECT`.

## Building the databases

1. Copy each original database to a database with the suffix `_S`, for example `mysqldump Mondial | mysql Mondial_S`. The databases are `lahman_2014`, `NCAA`, `Financial_ijs`, `imdb_full`, `oulad`, `YelpDataset3`, `ErgastF1`, `Basketball_men`, `Mondial` and `stats`.
2. Only for `lahman_2014_S`: run `prepare_lahman_2014_S.sql`.
3. Run `alter_tables.sql`.
4. Run `populate_values.sql` (MySQL 8.0). It takes a while: the iterative columns need a few minutes each and the largest updates up to an hour.

`YelpDataset3_S.Tips` has no key. The scripts add a helper column `tip_id` (a row number, not one of the 185 columns) that the formula of `Tips.draw_coefficient` uses.

