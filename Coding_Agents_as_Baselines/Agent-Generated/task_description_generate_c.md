You are asked to write a Python program, `c.py`. Given one target column of a MySQL database, `c.py` finds out whether the column is *derived* and, if it is, discovers formulas for it, with the help of a large language model (LLM).

While you write the program you have two resources, for development and testing only: read-only access to one **development database**, `sakila`, so that you can get familiar with how a database looks, and access to an LLM, so that you can test your program. Your program will later be run on **other databases that you cannot see**, with other LLM deployments. It must work there without any change.

## What `c.py` must do

Running `python c.py --column <database>.<table>.<column> --llm <gpt5|sonnet55>` from the current directory must process that one target column and write its results to the folder `output` in the current directory, as described under Deliverables of `c.py`.

For the target column `<column>` of the table `<table>` in the database `<database>`, `c.py` performs these tasks:

### Task 1: Understand the column semantics
Using the database (read-only) and the LLM, identify the semantics of the column given its table and the database context (for example the column name and data types).

### Task 2: Determine whether the column is derived
Determine whether the column is *derived*, i.e., whether it can be computed by a formula from other columns in the same database. The derivation can span multiple tables and is not limited to the table of the column. Not every column is derived.

### Task 3: Discover the formula
If the column is derived, discover its derivation formulas. A formula must be the actual derivation of the value (not an approximation or an estimate) and must be a general rule that applies to all rows.

A derived column can have multiple formulas, i.e., it can be derived in different ways (for example, from different columns or from different tables). `c.py` must find all of them. Each formula must be a different derivation, not a rewrite of another.

Example: in a table `orders` with the columns `store_id`, `order_no`, `subtotal`, `tax`, `shipping` and `total_amount`, the column `total_amount` could be derived as `subtotal + tax + shipping`, or as the sum of `line_total` over the rows of the table `order_items` with the same `store_id` and `order_no`, plus `tax` and `shipping`.

A formula must not read the stored value of the target column, in any form. For example, `SELECT <column> AS derived FROM <table>` is not allowed, because it returns the stored value instead of a value computed by the derivation formula.

### Task 4: Compute the confidence
For each formula, report its confidence: the percentage of the values of the target column that conform to the formula, among the rows whose stored value of the column is not NULL.

## Requirements on `c.py`
- **No hard-coded knowledge of any dataset.** `c.py` must contain nothing that is specific to the development database or to any particular database: no database, table or column names; no data values; no special cases or rules for particular columns or schemas; no lists of known derived columns or known formulas; no lookup tables. This also applies to the prompts that `c.py` sends to the LLM: they must be generic, and any example inside a prompt must be invented, not taken from the development database. Your program must work for any MySQL database, discovering everything it needs (schema, keys, relationships, data) at run time.
- It uses the LLM to help find formulas. Everything else about its design is up to you.
- The database account is read-only. `c.py` may only run read-only queries.
- **Time limit of 60 minutes per column, enforced by `c.py` itself.** It starts a wall-clock timer when it starts. When 60 minutes have passed it must stop all work, write the files for the formulas it has already found (or the `_not_derived.txt` file if it has none), and exit.
- **Errors.** `c.py` must never crash and must never confuse a failure with an answer. It always ends with exit code 0 and with exactly one outcome for the column: formula file(s), or `_not_derived.txt`, or `output/<database>.<table>.<column>_error.txt` (containing the error message). Only a decision based on the data may produce `_not_derived.txt`.
  - **A failing SQL query must be caught, and it never stops `c.py`.** It records the error in the trace and goes on with its work: for example it asks the LLM to repair the query, tries another approach, or searches for other formulas. One failed query must never end the search for a column.
  - *Temporary* failures (rate limit, timeout, dropped connection, an LLM response that is empty or cannot be parsed) are retried, waiting longer between attempts, for as long as the time limit allows.
  - *Permanent* failures (wrong password, invalid key, unreachable host after repeated attempts, the column does not exist, the table is empty) are not retried: write `_error.txt` at once.
  - The whole program runs inside a top-level exception handler, so that the error file and the trace are always written, even for an unexpected exception.
- It must record every LLM call (time, model, input tokens, output tokens) as one line in `output/<database>.<table>.<column>_llm_calls.jsonl`.
- **It must write a trace of how it works.** `c.py` appends, as it goes (one JSON object per line, flushed after each line, so that a crash or the time limit still leaves the trace), every step to `output/<database>.<table>.<column>_trace.jsonl`. Each line has a timestamp, a step type and its content, covering at least:
  - every database query it runs: the full SQL text, the number of rows returned, the time it took, and any error;
  - every LLM call: the complete prompt and the complete response, not shortened, with the model and the token counts;
  - every formula it produces or changes (the SQL and how it was obtained) and every decision it takes about a formula, with the information the decision was based on and the reason;
  - the final decision for the column (derived or not derived, which formulas were saved) with a short statement of why.
  The trace must be complete enough for a reader to reconstruct how each saved formula was found.
- It runs with Python 3.13. Use only the standard library and these packages: `pymysql`, `openai` and `anthropic`.

## Configuration files (read by `c.py` at run time, in the current directory)
The program reads its database and LLM settings only from these files. During development they point to the development database and to a test LLM endpoint; later, other files with exactly the same form (different values) are used.

`db_access.json`:
{"host": "db.example.org", "port": 3306, "user": "reader", "password": "secret"}
(`c.py` connects without a default database and refers to tables as `database.table`, or selects the database itself.)

`llm_gpt5.json` (used for `--llm gpt5`):
{"provider": "azure_openai", "azure_endpoint": "https://example.cognitiveservices.azure.com/", "api_key": "key", "api_version": "2024-12-01-preview", "model": "gpt-5"}
Use `openai.AzureOpenAI(azure_endpoint=..., api_key=..., api_version=...)` and `client.chat.completions.create(model=..., messages=[...])`.

`llm_sonnet55.json` (used for `--llm sonnet55`):
{"provider": "anthropic_foundry", "base_url": "https://example.services.ai.azure.com/anthropic/", "api_key": "key", "model": "claude-sonnet-5-5"}
Use `anthropic.AnthropicFoundry(api_key=..., base_url=...)` and `client.messages.create(model=..., max_tokens=..., messages=[...])`.

### Optional field `unix_socket` (in all three files)
Any of the three files may contain an extra field `"unix_socket": "<path>"`, and `c.py` must support it:
- `db_access.json` with `unix_socket`: connect with `pymysql.connect(unix_socket=<path>, user=..., password=...)` and ignore host and port.
- `llm_gpt5.json` or `llm_sonnet55.json` with `unix_socket`: send the requests through that Unix socket instead of the network, by giving the client an `httpx` transport: `http_client=httpx.Client(transport=httpx.HTTPTransport(uds=<path>))` (`httpx` is installed together with `openai` and `anthropic`; the URL in the file is then only used to build the request path). Do not use proxy environment variables in that case.
If the field is absent, use host and port, or the URL, as usual. During development the three files contain this field, because the machine you work on reaches the database and the LLM only through sockets. The files used later normally do not contain it, and `c.py` must work with both forms.

## Deliverables of `c.py` (for the target column)
Everything is saved in the folder `output` in the current directory (create it if it does not exist).

If the column is not derived, create an empty file named `output/<database>.<table>.<column>_not_derived.txt` and no formula files.

Otherwise save each formula as a single MySQL `SELECT` query in its own file `output/<database>.<table>.<column>_formula_1.sql`, `..._formula_2.sql`, and so on. Each query returns exactly one column, aliased `derived`, that contains the value computed by the formula, with one row per row of `<table>`. Write the confidence (a number between 0 and 100) in the first line of the file, as the SQL comment `-- confidence: <number>`.

Example, for `total_amount` of `orders` in the database `shop`, `output/shop.orders.total_amount_formula_1.sql`:
-- confidence: 100
SELECT subtotal + tax + shipping AS derived
FROM orders

In addition to the formula files, `c.py` always writes the trace file `output/<database>.<table>.<column>_trace.jsonl` and the LLM-call log `output/<database>.<table>.<column>_llm_calls.jsonl`, also for columns that are not derived.

## How `c.py` will be checked for errors
Before it is run on real data, `c.py` is run in the situations below. In each it must finish with exit code 0 and write one of the outcomes described above, plus the trace:
1. the database password is wrong;
2. the database host cannot be reached;
3. the target column does not exist;
4. the target table is empty;
5. the LLM key is invalid;
6. the LLM cannot be reached, or returns an empty or malformed answer;
7. the LLM returns SQL that fails when it is run: the error is caught and `c.py` continues (for example it repairs the query, tries another approach, or searches for other formulas);
Test these situations yourself while developing (for example with wrong configuration files, or by replacing the LLM call by a stub that returns broken SQL).

## What you may do while developing
- Explore the development database `sakila` with read-only queries, and run `c.py` on any of its columns to test it.
- Call the test LLM endpoint through the configuration files, to test `c.py`.
- Run Python locally.
- Do not try to reach anything else (other databases, other services, the internet). The development resources are for testing: do not copy anything from the development database into the program.

## What you deliver
Save the program as `output/c.py`. It is the only file you are asked for. It must run as described above on a machine where the packages are installed and the configuration files exist.

## Working mode
Work on your own until the program is done. There is nobody to answer questions, so do not ask any; if something is unclear, make the most reasonable choice and continue.
