"""LLM Prompt Templates - Centralized prompt definitions for data imputation pipeline.

This module contains all prompt templates used by the pipeline to communicate with LLMs.
Prompts are organized by category: schema understanding, formula detection, SQL generation, etc.
Each function takes relevant parameters and returns a formatted prompt string.
"""

import json
from src.core.config import config
from src.steps.formula_common import load_database_columns_metadata, load_database_distinct_values, load_database_sample_rows, load_database_schema


def _build_prompt(
    role: str = "",
    context: str = "",
    focus: str = "",
    task: str = "",
    reasoning: str = "",
    constraints: str = "",
    output: str = "",
) -> str:
    sections = [
        ("[ROLE] " + role) if role else "",
        ("[CONTEXT] " + context) if context else "",
        ("[FOCUS] " + focus) if focus else "",
        ("[TASK] " + task) if task else "",
        ("[REASONING] " + reasoning) if reasoning else "",
        ("[CONSTRAINTS] " + constraints) if constraints else "",
        ("[OUTPUT] " + output) if output else "",
    ]
    return " ".join(s for s in sections if s)


# ============================================================================
# SCHEMA UNDERSTANDING PROMPTS
# ============================================================================

def prompt_get_table_description_columns(table_name: str) -> str:
    role = "You are an expert database analyst specializing in interpreting relational database schemas and inferring the semantic meaning of columns."
    focus = f"Analyze the columns of the `{table_name}` table."
    task = f"Provide a concise textual description (fewer than 20 words each) for each column in `{table_name}` whose name is ambiguous or contains abbreviations."
    reasoning = "Step 1: Examine each column name and data type. Step 2: Use context from related tables and foreign key relationships to infer meaning. Step 3: For abbreviations, expand based on domain knowledge."
    constraints = "Do not describe columns whose names are already self-explanatory. Be concise — under 20 words per column."
    payload = {
        "column_descriptions": [
            {"column_name": "...", "description": "..."}
        ]
    }
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_get_table_description_correlations(
    table_name: str,
    column_name: str,
    target_table_description: str,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying intra-table column correlations."
    context = initial_prompt_str + " " + f"Table description: {target_table_description}"
    focus = f"Analyze potential correlations between `{column_name}` and other columns within `{table_name}`."
    task = f"Describe only in-table correlations — relationships between `{column_name}` and other columns in `{table_name}`. Exclude cross-table correlations."
    reasoning = "Step 1: Review each column in the same table. Step 2: Consider mathematical, categorical, and logical relationships. Step 3: Use distinct values and sample rows to spot patterns."
    constraints = f"Avoid speculating about cross-table relationships. If no in-table correlations exist, say so explicitly."
    payload = {"correlations": "describe correlations here or None if none found"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# FORMULA DETECTION PROMPTS
# ============================================================================

def prompt_is_computed_column(
    target_table_description: str,
    target_column_name: str,
    target_table_name: str,
    strategy: int = 1
) -> str:
    initial_prompt_str = get_initial_prompt_str(strategy)
    role = "You are an expert database engineer reverse-engineering computed columns from relational schemas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"Determine whether `{target_column_name}` in `{target_table_name}` is a computed/derived column."
    task = f"Identify if `{target_column_name}` can be calculated from other columns in `{target_table_name}` or related tables, and provide the formula."
    reasoning = "Step 1: Examine primary and foreign key relationships in the schema. Step 2: Check data types and statistics for mathematical patterns. Step 3: Look for aggregation relationships (SUM, COUNT, AVG) across joined tables. Step 4: Consider string, date, and conditional derivation patterns."
    constraints_parts = ["Use the schema (especially the PK-FK dependencies) to explore this."]
    if strategy >= 2:
        constraints_parts.append("Use the provided column statistics and distinct values.")
    if strategy >= 3:
        constraints_parts.append("Use the sample rows to verify patterns.")
    constraints_parts.append(
        "Bias towards computed: if any plausible derivation path exists via joined tables, report it as a candidate even if uncertain. "
        "Do NOT return None just because you are unsure — propose the most likely formula with a low confidence score instead. "
        "Return None only if absolutely no derivation path exists. "
        "Provide multiple candidates with confidence scores summing to 100 if uncertain."
    )
    constraints = " ".join(constraints_parts)
    payload = {
        "candidate_formulas": [
            {"textual_formula": f" write here the most potential formula to compute `{target_column_name}` "},
            {"textual_formula": f" write here the other candidate formula to compute `{target_column_name}`, if any "}
        ]
    }
    payload_None = {"candidate_formulas": "None"}
    output = (
        "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
        "If you do not find any formula, just write 'None' in the JSON. "
        "JSON format example when no potential formula is found:" + json.dumps(payload_None, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_semantic_plausibility_check(
    textual_formula: str,
    computation_sql_query: str,
    target_column_name: str,
    target_table_name: str,
) -> str:
    role = "You are an expert database engineer evaluating formula correctness."
    context = (
        f"Column `{target_column_name}` in table `{target_table_name}`. "
        f"Proposed formula: {textual_formula}. "
        f"SQL: {computation_sql_query}."
    )
    focus = f"Assess whether the proposed formula is semantically plausible for `{target_column_name}`."
    task = "Determine if the formula is domain-appropriate and structurally correct for the target column."
    reasoning = (
        "Step 1: Check whether the formula produces values of the right data type and scale. "
        "Step 2: Verify it is domain-meaningful (e.g. summing quantities is OK, dividing names is not). "
        "Step 3: Confirm it does not circularly reference the target column itself."
    )
    constraints = (
        "Accept if any reasonable derivation path exists. "
        "Reject only if clearly domain-nonsensical, type-incompatible, or structurally wrong. "
        "Reject if the SQL or formula uses hardcoded lists of specific data instances — e.g., FirstName IN ('Ken', 'Rob', 'Michael', ...) or ID IN (1, 3, 7, ...) — to derive the computed value. This is data overfitting from training data, not a schema-derived formula, and must be marked as NOT plausible."
    )
    payload = {"is_plausible": True, "reason": "<brief reason>"}
    output = "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# SQL GENERATION PROMPTS
# ============================================================================

def prompt_find_formulas_and_computation_sql(
    target_table_description: str,
    target_column_name: str,
    target_table_name: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL developer generating SQL expressions to compute derived columns."
    context = initial_prompt_str + " " + target_table_description
    focus = f"Generate SQL to compute `{target_column_name}` in `{target_table_name}`."
    task = (
        f"In `{target_table_name}` table, `{target_column_name}` column has some missing values. "
        f"How the `{target_column_name}` column in the `{target_table_name}` table can be calculated? "
        f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_column_name}` from other columns and rows whether in the same table or in other tables (using joins) in the database. "
        "The schema (especially the PK-FK dependencies) is essential to explore this. "
        f"I am a program, so I just need you to write me the formula that will give us the missing values of the `{target_column_name}` column in the `{target_table_name}` table using stored values in the database. "
        f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. "
        f"I expect having multiple candidate formulas. Try to bring at max {config.max_candidate_formulas_single_table} realistic formulas. "
        f"Also, do not limit the search single-hop join tables. Maybe the formula requires accessing tables that require 2-hop or 3-hop joins (or even more). "
        "In addition, provide the names of the tables and columns that are used in the formula. "
        "For example, assume a table T contains column C (among other columns in T) and we want to find a formula to compute C from other tables and table T1 (a parent of table T) contains columns A and B (among other columns in T1) "
        "and another table T2 (a child of table T) contains columns X, Y and Z (among other columns in T2). "
        "Assume the textual formula to compute column C in table T is: IF T1.A is True then T.C = SUM(T2.X) ELSE (i.e. T1.A is False) then T.C = SUM(T2.X - T2.Y). "
        "In this example the used tables for the above formula are T1 and T2 and the used columns are T1.A, T2.X and T2.Y. "
        f"Moreover, as NL-to-SQL task, I want you to reflect the textual formula on an SQL query that computes {target_column_name} column in the {target_table_name}. "
        "The computation query shall not modify or fill missing values. "
        "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "
        + (
            f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
            f"the actual value of {target_column_name} (alias it as actual_value). "
            if number_of_pks_in_target_table == 0
            else
            f"The computation query is a select query that returns {number_of_pks_in_target_table+2} columns which are the primary keys of `{target_table_name}` table {names_of_pk_columns_of_target_table}, computed_value which is "
            f"resulted from the textual formula and the actual value of {target_column_name} (alias it as actual_value). "
        )
        + f"In other words, computed_value is the predicted value of `{target_column_name}` based on the textual formula. "
        f"Also, please alias the {target_table_name} table in the outer query's FROM clause as target_table. "
        "For each candidate formula identified, write the corresponding SQL computation expression."
    )
    reasoning = "Step 1: For each candidate formula, identify the source columns and operations. Step 2: Write the SQL expression using correct syntax for the identified pattern. Step 3: Handle JOINs if columns come from other tables. Step 4: Account for primary key structure when forming subqueries."
    constraints = (
        "To ensure the correctness of the query, consider the following rules: "
        "Rule 1: Do not use aggregation functions that include values retrieved from left joins. Rather, the left join clause shall include the aggregation functions inside it. "
        "Example of wrong SQL: SELECT id, SUM(i.amount) - SUM(o.amount) as balance from account a left join (select account_id, amount from income) as i on a.id = i.account_id left join (select account_id, amount from outcome) as o on a.id = o.account_id; "
        "Example of correct SQL: SELECT id, total_income.value - total_outcome.value as balance from account a left join (select account_id, sum(amount) as value from income group by account_id) as total_income on a.id = total_income.account_id left join (select account_id, sum(amount) as value from outcome group by account_id) as total_outcome on a.id = total_outcome.account_id; "
        "Avoid nesting aggregate functions; compute them in subqueries before comparison. "
        "Avoid creating temporary tables. "
        "Rule 2: Rounding is not required at all. "
        "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
        "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
        "Rule 5: In case of string comparisions, do not use 'FIND_IN_SET' and 'REPLACE' functions. Rather use the 'LIKE' function. "
        f"Rule 6: Do NOT read `{target_column_name}` from `{target_table_name}` anywhere in the SQL — not via the `target_table` alias, not via any other alias of `{target_table_name}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_column_name}`), MIN(`{target_column_name}`), SUM(`{target_column_name}`) applied to `{target_table_name}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. Reading the target column to predict itself is circular and invalid. "
        "Rule 7: Write efficient SQL — use JOINs with GROUP BY instead of correlated subqueries; avoid SELECT COUNT(*) or ORDER BY+LIMIT inside a correlated subquery on large tables. "
        "Rule 8: Do NOT propose data-fitting formulas. Do not hardcode specific data instances — such as person names, numeric IDs, or enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. The formula must follow structural schema logic (FK-PK joins, aggregations, type constraints), not memorized training data. Example of a forbidden query: CASE WHEN FirstName IN ('Ken', 'Michael', 'Roberto', ...) THEN 'M' — this is data overfitting and is invalid. "
        "Provide me the computation query that shall be executed in MySQL. "
        "In addition, it is very important to make the computation query applies the textual formula without any variance. "
        "Finally, the computation sql queries shall not be semantically equivalent. For example, if you find 3 formulas that are reflected in 3 computation queries that are semantically equivalent, keep one formula and remove the other two formulas."
        "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explanations) such that I execute it immediately without parsing and modification. "
        "Be careful and make the computation query free-of-errors. "
        "Ensure SQL is valid MySQL syntax."
    )
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " write here the most potential formula e.g. x = average(y + z) where y and z are columns in another table of that of x ",
                "used_tables": " Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas",
                "used_columns": " Only the names of the columns that are used in the textual_formula do not add the joining columns",
                "confidence_score": " a number from 0 to 100",
                "computation_sql_query": " select T1.x as actual_value, AVG(T2.y + T2.z) as computed_value from tbl_1 T1 left join tbl_2 T2 on T1.id = T2.id group by T1.id, T1.x "
            },
            {
                "textual_formula": " write here the other candidate formula, if any e.g. x = y + z where y and z are columns in the same table of x ",
                "used_tables": " Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas ",
                "used_columns": " Only the names of the columns that are used in the textual_formula do not the joining columns",
                "confidence_score": " a number from 0 to 100",
                "computation_sql_query": " select x as actual_value, y + z as computed_value from tbl_1 "
            }
        ]
    }
    payload_example_1 = {
        "candidate_formulas": [
            {
                "textual_formula": " T.C = IF T1.A is True then T.C = SUM(T2.X) ELSE (i.e. T1.A is False) then T.C = SUM(T2.X - T2.Y) ",
                "used_tables": ["T1", "T2"],
                "used_columns": ["T1.A", "T2.X", "T2.Y"],
                "confidence_score": "70",
                "computation_sql_query": " SELECT T.C actual_value, SUM(CASE WHEN T1.A THEN T2.X ELSE T2.X - T2.Y END) FROM tbl T LEFT JOIN tbl_1 T1 ON T.id = T1.id LEFT JOIN tbl_2 T2 ON T.id = T2.id GROUP BY T.id, T.C"
            }
        ]
    }
    payload_example_2 = {"candidate_formulas": "NaN"}
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "In the above example, the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
        "If you do not find any formula, the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# ERROR RECOVERY PROMPTS
# ============================================================================

def prompt_diagnose_formula_mismatch(
    computation_sql_query: str,
    diagnoses_sql_query: str,
    diagnoses_sql_query_result_str: str,
    target_column_name: str,
    target_table_name: str
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL debugger analyzing why a formula produces incorrect results."
    context = initial_prompt_str
    focus = f"Diagnose why the SQL query for `{target_column_name}` in `{target_table_name}` is producing mismatches."
    task = (
        f"I used the computation query that you have provided to calculate the values of {target_column_name} column in {target_table_name} table and compare it with some non-null values. It seems that not all values match. "
        "Probably, it is a formatting or scaling issue or probably the formula needs modifications. "
        "Here is the computation query that you have provided me: " + computation_sql_query + ". "
        "Here is the diagnoses query that I prepared from the computation query that you have provided me: " + diagnoses_sql_query + ". "
        "Here is the result of the diagnoses query: " + diagnoses_sql_query_result_str + ". "
        "Identify the root cause of the mismatch and provide a corrected SQL computation query."
    )
    reasoning = (
        "Step 1: Compare the actual vs. computed values in the diagnosis result. "
        "Step 2: Identify the type of error (off-by-one, wrong JOIN, wrong aggregation, data type mismatch, etc.). "
        "Step 3: Trace back to the formula and pinpoint the incorrect assumption. "
        "Step 4: Propose a minimal correction."
    )
    constraints = (
        "Return only the corrected SQL query — do not change the overall formula approach unless it is fundamentally wrong. "
        "If you realize the reason of the mismatch, provide me an updated computation query. "
        "As mentioned earlier, I am a program, so I just need you to write me in your answer the computation query that I can run to verify the formula - only the SQL computation query such that I execute it immediately without parsing and modification. "
        "Be careful and make the validation query free-of-errors."
    )
    payload = {"computation_sql_query_after_diagnoses": "WRITE THE MODIFIED COMPUTATION QUERY HERE"}
    output = _get_json_prompt(payload)
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_fix_sql_query_error(query: str, error: str) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert MySQL developer fixing syntax and runtime errors in SQL queries."
    context = initial_prompt_str
    focus = f"Fix the SQL query that produced the following error: {error}"
    task = (
        f"I ran the query in MySQL database and it returns an error. Modify the SQL query and resolve the error and send it back to me. "
        f"As a reminder, here is the query: [[[START OF QUERY]]] {query} [[[END OF QUERY]]]. "
        f"It is very important to make the query compatible with the schema. "
        f"Here is the error message from MySQL engine: {error}. "
        "Correct the SQL query so it executes without errors while preserving its original intent."
    )
    reasoning = (
        "Step 1: Parse the error message to identify the error type and location. "
        "Step 2: Examine the query structure around the reported line/token. "
        "Step 3: Apply the minimal fix required."
    )
    constraints = (
        "Do not change the logic of the query — only fix the syntax or structural error. Return the complete corrected query. "
        "As I mentioned previously, I am a program, so I just need you to write me in your answer the SQL query as you did before. Only the SQL query such that I execute it immediately without parsing and modification."
    )
    payload = {"computation_sql_query": f" the computation SQL query to compute {config.target_column_name} that you shall provide to get error-free SQL query"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_fix_timeout_with_subset(query: str, error: str, target_table: str, target_column: str) -> str:
    role = "You are a MySQL performance expert rewriting timed-out queries to run on a representative subset."
    context = ""
    focus = f"The query timed out — rewrite it to validate on 1000 representative rows instead of the full table."
    task = (
        f"The following SQL query timed out (performance issue, not a syntax error).\n\n"
        f"Query: [[[START OF QUERY]]] {query} [[[END OF QUERY]]]\n\n"
        f"Error: {error}\n\n"
        f"Rewrite the query to validate on a subset of at most 1000 rows from `{target_table}` "
        f"where `{target_column}` IS NOT NULL and has diverse values (not all the same).\n\n"
        f"Keep the same formula logic — only limit which rows are validated."
    )
    reasoning = (
        f"Step 1: Build the subset subquery: SELECT * FROM `{target_table}` WHERE `{target_column}` IS NOT NULL LIMIT 1000. "
        f"Step 2: Apply the original formula validation logic on top of this subset. "
        f"Step 3: Preserve the actual_value / computed_value column aliases."
    )
    constraints = (
        f"Do not change what is being computed — only limit the rows. "
        f"The rewritten query must complete within 10 minutes on a large MySQL database."
    )
    payload = {"computation_sql_query": f"the rewritten SQL query that validates on a 1000-row subset of {target_table}"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_optimize_sql_query(computation_sql_query: str, explain_results: str) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are a MySQL performance expert rewriting expensive SQL queries."
    context = initial_prompt_str
    focus = "Rewrite the query to eliminate full table scans and correlated subqueries."
    task = (
        f"The following MySQL query is too expensive — EXPLAIN shows a full table scan or large cross-product. "
        f"Rewrite it to be efficient. If it cannot be made efficient, set computation_sql_query to null.\n\n"
        f"Query: [[[START]]] {computation_sql_query} [[[END]]]\n\n"
        f"EXPLAIN output:\n{explain_results}"
    )
    reasoning = (
        "Step 1: Identify the expensive operation in EXPLAIN (type=ALL on large table). "
        "Step 2: Replace correlated subqueries with JOINs + GROUP BY. "
        "Step 3: Verify the rewritten query preserves the original formula intent."
    )
    constraints = (
        "Use JOINs with GROUP BY instead of correlated subqueries. "
        "Avoid SELECT COUNT(*) or ORDER BY+LIMIT inside correlated subqueries. "
        "If no efficient rewrite exists, return null for computation_sql_query."
    )
    payload = {"computation_sql_query": f"efficient SQL to compute {config.target_column_name}, or null"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# DATA CLEANING PROMPTS (Rename Tables & Columns)
# ============================================================================

def prompt_rename_table(
    table_name: str,
    column_names_str: str,
    table_headers: str,
    table_sample_rows: str,
    include_data: bool = False
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are a database naming expert applying semantic naming conventions to database tables."
    context_parts = [initial_prompt_str]
    if include_data:
        context_parts.append(f"Table rows of `{table_name}`: {table_headers} {table_sample_rows}.")
    context = " ".join(context_parts)
    focus = f"Evaluate the name of the `{table_name}` table with columns: {column_names_str}."
    task = (
        f"Suggest a more representative singular noun name for `{table_name}` if its current name is unclear or abbreviated. "
        f"If the name is already representative, return 'representative_name'. "
        "Representative table name means without abbreviations, typos or ambiguities. "
        "Here is an example of ambiguity, a table named `HR` may refer to HumanResources or HeartRate. "
        f"Rule 1: Look on the columns names of the table `{table_name}`. For example, if the columns refer to medical domain (e.g. a column named patient_id) then it is HeartRate. "
        f"As a reminder, here are the columns names of table `{table_name}`: {column_names_str}. "
        + (
            f"Rule 2: Pay more attention to the rows of the `{table_name}` table that I have shared with you. "
            f"As a reminder, here are the rows of table `{table_name}`: {table_headers} {table_sample_rows}. "
            f"Rule 3: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "
            if include_data else
            f"Rule 2: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "
        )
        + "For example, If a table named `ords` and has a relationship with a table named `order_items`, then you can infer that `ords` can be replaced with `orders`. "
        "End of rules. "
        "Also, make the table name singular if it is plural. For example, instead of `Employees`, table name should be `Employee`."
    )
    reasoning = "Step 1: Assess whether the table name clearly describes its entity. Step 2: Consider the column names and any sample data to infer the domain. Step 3: Choose a concise, singular noun that best represents the entity."
    constraints = "Return exactly one word — the new name or 'representative_name'. No explanation."
    payload = {"table_name": "new_name_or_representative_name"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_rename_column(
    column_name: str,
    table_name: str,
    column_names_str: str,
    distinct_values_str: str,
    table_headers: str,
    table_sample_rows: str,
    include_data: bool = False,
    include_distinct_values: bool = False
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are a database naming expert applying semantic naming conventions to database columns."
    context_parts = [initial_prompt_str]
    if include_distinct_values:
        context_parts.append(f"Distinct values of `{column_name}`: {distinct_values_str}.")
    if include_data:
        context_parts.append(f"Table rows of `{table_name}`: {table_headers} {table_sample_rows}.")
    context = " ".join(context_parts)
    focus = f"Evaluate the name of column `{column_name}` in `{table_name}`."
    rule_index = 2
    task_parts = [
        f"Suggest a more representative name for `{column_name}` if its current name is unclear or abbreviated. "
        "Representative column name means without abbreviations, typos or ambiguities. "
        "Here is an example of ambiguity, a column named `BP` may refer to blood_pressure or boiling_point. "
        f"Rule 1: Look on the columns names of the same table i.e. `{table_name}` table. For example, if the columns refer to medical domain (e.g. a column named patient_id) then it is blood_pressure. "
        f"As a reminder, here are the columns names of table `{table_name}`: {column_names_str}. "
    ]
    if include_data:
        task_parts.append(
            f"Rule {rule_index}: Pay more attention to the rows of the `{table_name}` table that I have shared with you. "
            f"As a reminder, here are the rows of table `{table_name}`: {table_headers} {table_sample_rows}. "
        )
        rule_index += 1
    task_parts.append(
        f"Rule {rule_index}: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "
        f"For example, If a column named `ord_no` and `{table_name}` has a relationship with a table named `order`, then you can infer that `ord_no` can be replaced with `order_number`. "
    )
    if include_distinct_values:
        task_parts.append(
            f"As a reminder here are some distinct values of the column: {distinct_values_str}. "
            f"Add the following rule. Look at the data stored in the column `{column_name}` and make the column name representative of its data content. "
            "For example, if a column named `cars` and the data stored in it is integers like 1, 4 and 5, then it can be replaced with `number_of_cars` depending on the other factors like the schema, names of other tables and their columns, "
            "names of other columns in the same table, the name of the table that stores the column, the rows of the table, the distinct values of the column, etc. "
            "Also, some database designers might give a name to the column that is not fully representative. "
            "For example, a column named `return_ratio` shall be replaced with `return_percentage` if the column contains values between 0 and 100."
            "In the opposite case, a column named `return_percentage` shall be replaced with `return_ratio` if the column contains values between 0 and 1. "
        )
    task = "".join(task_parts)
    reasoning = "Step 1: Assess if the column name clearly describes its content. Step 2: Use distinct values or sample data to infer the column's semantic meaning. Step 3: Choose a concise, descriptive name."
    constraints = "Return exactly one word — the new name or 'representative_name'. No explanation."
    payload = {"column_name": "new_name_or_representative_name"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# SEMANTIC CLASSIFICATION PROMPTS
# ============================================================================

def prompt_detect_topic(items: list) -> str:
    items_str = ", ".join(items)
    role = "You are a semantic analyst identifying the topic or category of a list of values."
    focus = f"Analyze this list of values: {items_str}"
    task = "Identify the common semantic topic or category that best describes these values in 1 to 3 words."
    reasoning = "Step 1: Look for common themes across the values. Step 2: Identify the domain (geography, profession, status, etc.). Step 3: Choose the most concise and accurate label."
    constraints = "Return 1 to 3 words only. Do not explain."
    payload = {"topic": "one to three words"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# ============================================================================
# CHAINING TABLE PROMPTS
# ============================================================================

def prompt_identify_chaining_table_structure(
    target_table_description: str
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying chaining (sequential) table structures."
    context = initial_prompt_str + " " + target_table_description
    focus = f"Analyze whether `{config.target_table_name}` has a chaining table structure where rows form ordered sequences."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
        "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
        f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
        f"`{config.target_table_name}` is a chaining table. "
        f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
        f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
        f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
        f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
        "For example, to know the previous and next rows of R5. "
        "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
        "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = previous_row.C and current_row.C = next_row.B. "
        f"I want you to provide me the grouping columns and chaining columns in the `{config.target_column_name}` chaining table. "
        "Identify the grouping columns (that define each chain) and the chaining columns (that define the order within a chain)."
    )
    reasoning = (
        "Step 1: Look for columns that could represent order or sequence (e.g., date, sequence_number, next_id). "
        "Step 2: Identify columns that group rows into chains (e.g., customer_id, session_id). "
        "Step 3: Verify using the table description and schema."
    )
    constraints = "If the table is not a chaining table, return empty lists."
    payload = {
        "chaining_table_info": [
            {
                    "grouping_columns": ["used_column_1", "used_column_2"],
                    "chaining_columns": ["used_column_3", "used_column_4", "used_column_5"],
                    "same_group_condition": ["SQL condition"],
            }
        ]
    }
    payload_example_1 = {
        "chaining_table_info": [
            {
                    "grouping_columns": ["A", "B"],
                    "chaining_columns": ["C"],
                    "same_group_condition": [" where A = 'XXX' and B = 'XXX' "],
            }
        ]
    }
    payload_example_2 = {
        "chaining_table_info": [
            {
                    "grouping_columns": ["A"],
                    "chaining_columns": ["B", "C"],
                    "same_group_condition": [" where A = 'XXX' "],
            }
        ]
    }
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "In [Example 1], the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
        "In [Example 2], the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
        "Note that, some chaining tables have one group. So there is no grouping columns. In this case keep grouping_columns blank in the JSON. However, it is not accepted to have a chaining table without chaining columns. "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_chaining_table_candidate_formula(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    grouping_columns: str,
    chaining_columns: str
) -> str:
    from src.core.config import config

    role = "You are an expert SQL formula analyst identifying computed column formulas in chaining tables."
    context = f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]."
    focus = f"Find the formula to compute `{config.target_column_name}` in the chaining table `{config.target_table_name}` using the provided data samples."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
        "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
        f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
        f"`{config.target_table_name}` is a chaining table. "
        f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
        f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
        f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
        f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
        "For example, to know the previous and next rows of R5. "
        "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
        "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = previous_row.C and current_row.C = next_row.B. "
        f"Take the following data samples of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
        f"Based on the schema and these data samples, provide the formula to compute `{config.target_column_name}` from other columns and rows in `{config.target_table_name}`. "
        f"Also, to make the formula clear, use for the formula the grouping columns ({grouping_columns}) and the chaining columns ({chaining_columns}). "
        f"In addition, return the columns names that are needed for the formula to compute `{config.target_column_name}`."
    )
    reasoning = "Step 1: Examine the data samples to detect the pattern across rows. Step 2: Use the grouping and chaining columns to identify sequence relationships. Step 3: Express the pattern as a formula using current_row, previous_row, and next_row terms."
    constraints = (
        "Be concise and provide only one formula. The formula shall be completely compatible with the data samples. "
        "Use for the formula useful terms such as 'current_row', 'previous_row' and 'next_row'. "
        "If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. But, do not overdo it, if you find one just return it."
    )
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": f" write here the most potential formula to compute `{config.target_column_name}` ",
                "columns": ["X", "Y"]
            },
            {
                "textual_formula": f" write here the other candidate formula to compute `{config.target_column_name}`, if any ",
                "columns": ["A", "B"]
            }
        ]
    }
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_generate_sql_for_chaining_table(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    grouping_columns: str,
    chaining_columns: str,
    chaining_columns_str: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    from src.core.config import config

    role = "You are an expert SQL developer generating SQL queries for chaining table computed columns."
    context = f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]."
    focus = f"Generate a SQL computation query for `{config.target_column_name}` in the chaining table `{config.target_table_name}` using previous or next rows."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
        "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
        f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
        f"`{config.target_table_name}` is a chaining table. "
        f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
        f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
        f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
        f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
        "For example, to know the previous and next rows of R5. "
        "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
        "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
        f"Take the following sample rows of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
        f"Here is the textual formula to compute `{config.target_column_name}` from other rows: [[[FORMULA START]]] {formula_based_on_data_sharing} [[[FORMULA END]]]. "
        f"As an NL-to-SQL task, reflect the textual formula on an SQL query that computes {config.target_column_name} column in the {config.target_table_name} chaining table using previous or next rows. "
        "The computation query shall not modify or fill missing values. "
        "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "
        + (
            f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
            f"the actual value of {config.target_column_name} (alias it as actual_value). "
            if number_of_pks_in_target_table == 0
            else
            f"The computation query is a select query that returns {number_of_pks_in_target_table+2} columns which are the primary keys of `{config.target_table_name}` table {names_of_pk_columns_of_target_table}, computed_value which is "
            f"resulted from the textual formula and the actual value of {config.target_column_name} (alias it as actual_value). "
        )
        + f"In other words, computed_value is the predicted value of `{config.target_column_name}` based on the textual formula. "
        f"Avoid using `{config.target_column_name}` to calculate the computed_value of the same row. This is very important. Otherwise, we will have overfitting problem. "
        f"In addition, Please alias the {config.target_table_name} table in the outer query's FROM clause as target_table. "
        "Generate the SQL query for the chaining table formula."
    )
    reasoning = (
        "Step 1: Parse the textual formula to understand what previous/next row value is needed. "
        "Step 2: Build the nested subquery to access the previous or next row in the chain. "
        "Step 3: Apply grouping and chaining column conditions to locate the correct row. "
        "Step 4: Handle edge cases (first/last rows in chain that cannot be computed)."
    )
    constraints = (
        "To ensure the correctness of the query, consider the following rules: "
        f"Rule 1: As `{config.target_table_name}` is a chaining table, to calculate the value of '{config.target_column_name}' of a certain row, "
        f"the computed_value shall be a nested query that computes the value from next/previous row(s) table `{config.target_table_name}` in the computation query and return only one value. "
        "With this, self-join is not required. So, do not use self-join. "
        f"The nested query shall be in the outer select and returns ONLY one value as a computed value (aliased computed_value). "
        "Rule 2: Rounding is not required at all. "
        "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. "
        "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
        "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
        f"Rule 5: As `{config.target_table_name}` is a chaining table, some values cannot be computed. "
        f"Rule 6: Do not use `{config.target_column_name}` in the computed_value of the same row. "
        f"For example, avoid the following case: {config.target_column_name} = column_x + ({config.target_column_name} - column_x). "
        f"Also, do not use target_table.`{config.target_column_name}` in the computed_value at all. "
        f"For example [Case 1], if `{config.target_column_name}` of a row is calculated based on its previous row, then the value of `{config.target_column_name}` in the first row of the chain can not be computed. "
        f"In this case, the computation query shall exclude (in the WHERE clause) the first rows of chains i.e. any row that do not have a previous row. "
        f"Another example [Case 2], if `{config.target_column_name}` of a row is calculated based on its next row, then the value of `{config.target_column_name}` in the last row of the chain can not be computed. "
        f"In this case, the computation query shall exclude (in the WHERE clause) the last rows of chains i.e. any row that do not have a next row. "
        "Provide me the computation query that shall be executed in MySQL. "
        "Keep in mind that, MySQL doesn't allow nested aggregate functions directly. "
        "In addition, it is very important to make the computation query applies the textual formula without any variance. "
        f"Pay attention to the sample rows, especially when you determine the chaining criteria in the table (i.e. to know next and previous rows). See in the data, the values of {chaining_columns_str} across rows. "
        f"Pay attention to all rules, especially rule 5 to exclude rows that their `{config.target_column_name}` value cannot be computed. "
        f"Also, remember that the nested query of the computed_value shall return only one value. "
        "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explanations) such that I execute it immediately without parsing and modification. "
        "Be careful and make the computation query free-of-errors. The query shall be 100 percent compatible with the data samples that I sent you."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


def prompt_classify_chain_direction() -> str:
    from src.core.config import config

    role = "You are a sequence analyst determining the direction of chaining relationships in database tables."
    focus = f"Determine whether `{config.target_column_name}` uses previous or next rows in the chain."
    task = f"Is `{config.target_column_name}` using previous rows or next rows to compute its value?"
    reasoning = "Step 1: Review the formula and the data pattern. Step 2: Determine whether the computation references the preceding row or the following row in the sequence."
    constraints = "I am a program, so I just respond with one word - whether 'previous' or 'next'."
    payload = {"direction": "previous or next"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_diagnose_chaining_formula(
    target_table_description: str,
    current: str,
    grouping_columns: list,
    chaining_columns: list,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    accuracy: float,
    diagnoses_sql_query_result_str: str
) -> str:
    from src.core.config import config

    grouping_info = (
        f"The grouping columns in the `{config.target_table_name}` table are {grouping_columns}. "
        if len(grouping_columns) > 1
        else f"The grouping column in the `{config.target_table_name}` table is {grouping_columns[0]}. "
    )
    chaining_info = (
        f"And the chaining columns in the `{config.target_table_name}` table are {chaining_columns}. "
        if len(chaining_columns) > 1
        else f"And the chaining column in the `{config.target_table_name}` table is {chaining_columns[0]}. "
    )
    role = "You are an expert SQL debugger analyzing and correcting chaining table formula mismatches."
    context = f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]."
    focus = f"Diagnose why the formula for `{config.target_column_name}` in the chaining table `{config.target_table_name}` produces incorrect results."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
        "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
        f"Hence, to compute `{config.target_column_name}`, we need to access {current} rows of the same table with a specific criterion. "
        f"`{config.target_table_name}` is a chaining table. "
        f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
        f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
        f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
        f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
        "For example, to know the previous and next rows of R5. "
        "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
        "Sometimes the chaining columns are more than one column. "
        "[Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining columns. "
        + grouping_info + chaining_info
        + f"Take the following sample rows of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
        f"I tried to calculate the missing values of `{config.target_column_name}` using the following formula but the results show that the formula is incorrect (accuracy: {accuracy}%). "
        f"Here is the incorrect formula: [[[START OF INCORRECT FORMULA]]] {formula_based_on_data_sharing} [[[END OF INCORRECT FORMULA]]]. "
        f"Also, here is some random computation query results: {diagnoses_sql_query_result_str}. "
        f"These computation query results are randomly sampled (i.e. they do not form chains) and are useful for comparing the predicted value with the actual value to identify the error in the formula. "
        "Identify the root cause of the mismatch and provide a corrected formula. "
        f"Also, return the columns names that are needed for the formula to compute `{config.target_column_name}`."
    )
    reasoning = (
        "Step 1: Compare the actual vs. computed values in the diagnosis result. "
        "Step 2: Identify the type of error (wrong grouping, wrong chaining condition, off-by-one, etc.). "
        "Step 3: Trace back to the formula and pinpoint the incorrect assumption. "
        "Step 4: Propose a corrected formula."
    )
    constraints = (
        "The goal is to make the computation_value equals the actual_value. The actual_value is correct but the computation_value is not. "
        "Find the error in the formula that results in the mismatches. Probably the formula requires minor modifications. "
        "To do so, focus on the sample rows and computation query results."
    )
    payload = {
        "is_catched": " 'yes' if you find out the cause of the error and 'no' otherwise ",
        "cause_of_error": " explain the root cause of the error briefly ",
        "corrected_formula": " write the new correct formula here ",
        "columns": ["X", "Y"]
    }
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_generate_corrected_sql_for_chaining(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    corrected_formula: str,
    formula_based_on_data_sharing: str,
    cause_of_error: str,
    chaining_columns_str: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Generate prompt to create SQL query using corrected formula in a chaining table.

    Args:
        target_table_description: Description of the target table
        data_for_sharing_with_LLM_str: Sample data rows
        corrected_formula: The corrected textual formula
        formula_based_on_data_sharing: The previously incorrect formula
        cause_of_error: Explanation of the error
        chaining_columns_str: Chaining columns as string
        number_of_pks_in_target_table: Number of primary keys
        names_of_pk_columns_of_target_table: List of PK column names

    Returns:
        Prompt asking to regenerate SQL with corrected formula
    """
    from src.core.config import config

    role = "You are an expert SQL developer correcting a chaining-table computation formula."
    context = (
        f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
        f"`{config.target_table_name}` is a chaining table where each row has a previous row (except the first) and a next row (except the last). "
        f"Each chaining table is split into groups and in each group there is a chain. "
        f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        f"In this example, the table is split into two groups. Column A and column B are called 'grouping columns'. Column C is called 'chaining column'. "
        f"[Example 2] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        f"R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        f"In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
        f"Sample rows of `{config.target_table_name}`: {data_for_sharing_with_LLM_str}. "
        f"Correct formula: [[[CORRECT FORMULA START]]] {corrected_formula} [[[CORRECT FORMULA END]]]. "
        f"Previously incorrect formula: [[[INCORRECT FORMULA START]]] {formula_based_on_data_sharing} [[[INCORRECT FORMULA END]]]. "
        f"Reason for incorrectness: [[[REASON OF INCORRECTNESS START]]] {cause_of_error} [[[REASON OF INCORRECTNESS END]]]."
    )
    focus = f"Target column `{config.target_column_name}` in chaining table `{config.target_table_name}`."
    task = (
        f"Generate corrected SQL for the chaining table formula based on the diagnosed error. "
        f"As an NL-to-SQL task, reflect the corrected textual formula on an SQL query that computes `{config.target_column_name}` in `{config.target_table_name}` using previous or next rows. "
        f"The computation query is only to verify the formula — it shall not modify or fill missing values. "
        + (
            f"The computation query is a select query that returns two columns: computed_value (from the textual formula) and actual_value (the actual value of `{config.target_column_name}`). "
            if number_of_pks_in_target_table == 0
            else f"The computation query is a select query that returns {number_of_pks_in_target_table + 2} columns: primary keys {names_of_pk_columns_of_target_table}, computed_value (from the textual formula), and actual_value (the actual value of `{config.target_column_name}`). "
        )
        + f"computed_value is the predicted value of `{config.target_column_name}` based on the textual formula. "
        f"Please alias the `{config.target_table_name}` table in the outer query's FROM clause as target_table."
    )
    reasoning = (
        "Step 1: Apply the identified correction to the formula. "
        "Step 2: Rebuild the SQL using correct chaining column references. "
        "Step 3: Ensure the SQL handles all grouping and ordering correctly."
    )
    constraints = (
        f"Rule 1: Use a nested subquery (not self-join) to compute the value from next/previous row(s) — the nested query shall be in the outer SELECT and return ONLY one value (aliased computed_value). "
        f"Rule 2: Rounding is not required. "
        f"Rule 3: Only use columns that exist in the schema. "
        f"Rule 4: Cast UNSIGNED columns to SIGNED before arithmetic that may produce negative values. "
        f"Rule 5: Exclude rows that cannot be computed (first rows of chains if using previous row; last rows of chains if using next row) via the WHERE clause. "
        f"Rule 6: Do NOT read `{config.target_column_name}` from `{config.target_table_name}` anywhere in the SQL — not via `target_table`, not via any other alias of `{config.target_table_name}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{config.target_column_name}`), MIN(`{config.target_column_name}`), SUM(`{config.target_column_name}`) applied to `{config.target_table_name}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. "
        f"Avoid making the same mistake as the incorrect formula. "
        f"Pay attention to chaining criteria ({chaining_columns_str}) and ensure the nested query returns only one value. "
        f"MySQL doesn't allow nested aggregate functions directly. "
        f"Only output the executable SQL query without explanations."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


# ============================================================================
# HIERARCHICAL TABLE PROMPTS (continued)
# ============================================================================

def prompt_identify_hierarchical_table_structure(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Generate prompt to identify parent-reference relationships in a hierarchical table.

    Args:
        target_table_description: Description of the target table
        names_of_pk_columns_of_target_table: List of PK column names

    Returns:
        Prompt asking to identify hierarchical table structure
    """
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying parent-child (hierarchical/self-referencing) table structures."
    context = (
        initial_prompt_str + " " + target_table_description + " "
        f"`{config.target_table_name}` is a hierarchical table with a tree-like structure where each row has at most one parent row (except the root) and children rows (except leaves). "
        f"Each row stores the identifier of its parent row in one of its columns. "
        + (
            f"The identifier of rows in `{config.target_table_name}` is {names_of_pk_columns_of_target_table[0]}. "
            if len(names_of_pk_columns_of_target_table) == 1
            else (
                f"The identifier of rows in `{config.target_table_name}` is the following composite key: {names_of_pk_columns_of_target_table}. "
                if len(names_of_pk_columns_of_target_table) > 1
                else ""
            )
        )
        + f"[Example 1] Assume a hierarchical table T has more than 3 columns (A, B, C ...). "
        f"Column A is the identifier and Column C is the column that refers to the identifier of the parent row. "
        f"Assume the hierarchical table T stores rows where R1 is parent of R2 and R3, and R3 is parent of R4. "
        f"[Example 2] Assume a hierarchical table T has composite key (A, B) and columns C, D referring to parent (A, B)."
    )
    focus = f"`{config.target_table_name}` and its potential self-referencing foreign keys."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value derived from other rows in the same table. "
        "Identify the parent-reference columns — pairs of (parent column, child column) that define the hierarchical relationship. "
        + (
            "Provide the name of the parent-reference-column and the parent-referencing-column. "
            if len(names_of_pk_columns_of_target_table) == 0
            else (
                f"As `{config.target_table_name}` is a hierarchical table with identifier `{names_of_pk_columns_of_target_table[0]}`, provide the parent-referencing-column. "
                if len(names_of_pk_columns_of_target_table) == 1
                else f"As `{config.target_table_name}` is a hierarchical table with composite key, provide the parent-referencing-column for each identifier. "
            )
        )
    )
    reasoning = (
        "Step 1: Look for self-referencing foreign keys in the schema. "
        "Step 2: Identify which column holds the parent's identifier. "
        "Step 3: Verify by checking if any PK column is also referenced as a FK in the same table."
    )
    constraints = "If no hierarchical structure exists, return empty lists."
    payload = {"parent_reference_columns": [["parent_col", "referencing_col"]]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_hierarchical_table_candidate_formula(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str
) -> str:
    """Generate prompt to find candidate formulas in a hierarchical table.

    Args:
        target_table_description: Description of the target table
        names_of_pk_columns_of_target_table: List of PK column names
        parent_reference_columns_list: List of parent-reference relationships
        data_for_sharing_with_LLM_str: Sample data rows

    Returns:
        Prompt asking for candidate formulas in hierarchical table
    """
    from src.core.config import config

    parent_ref_info = (
        f"As `{config.target_table_name}` has one identifier, the parent-reference-column is `{parent_reference_columns_list[0][0]}` and its parent-referencing-column is {parent_reference_columns_list[0][1]}. "
        if len(names_of_pk_columns_of_target_table) == 1
        else (
            f"As `{config.target_table_name}` has composite key identifier, here are the parent-reference relationships: "
            + "".join(
                f"Parent-reference-column is `{pr[0]}`, parent-referencing-column is {pr[1]}. "
                for pr in parent_reference_columns_list
            )
        )
    )
    role = "You are an expert formula analyst working with hierarchical (parent-child) table computations."
    context = (
        f"`{config.target_table_name}` is a hierarchical table. "
        + parent_ref_info
        + f"Data samples of `{config.target_table_name}`: {data_for_sharing_with_LLM_str}."
    )
    focus = f"Target column `{config.target_column_name}` in hierarchical table `{config.target_table_name}`."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value derived from other rows in the same table. "
        f"Identify a formula for `{config.target_column_name}` that uses the parent-child relationship in the hierarchical table. "
        f"Based on the schema and data samples, provide the formula to compute `{config.target_column_name}` from other columns and rows. "
        f"Be concise. Use terms such as 'parent_row', 'children_rows', and 'child_row'. "
        f"If you suspect more than one candidate formula, provide them all with confidence scores summing to 100."
    )
    reasoning = (
        "Step 1: Understand the parent-child link defined by the reference columns. "
        "Step 2: Consider recursive or self-join patterns. "
        "Step 3: Test the formula concept against the provided data samples."
    )
    constraints = "Be concise and provide only concrete formulas. Use hierarchical row terms (parent_row, child_row, children_rows)."
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_generate_sql_for_hierarchical_table(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    number_of_pks_in_target_table: int
) -> str:
    """Generate prompt to create SQL query for computing values in a hierarchical table."""
    from src.core.config import config

    parent_ref_info = (
        f"The parent-reference-column is `{parent_reference_columns_list[0][0]}` and its parent-referencing-column is {parent_reference_columns_list[0][1]}. "
        if len(names_of_pk_columns_of_target_table) == 1
        else (
            "Parent-reference relationships: "
            + "".join(f"`{pr[0]}` - {pr[1]}; " for pr in parent_reference_columns_list)
        )
    )
    role = "You are an expert SQL developer generating self-join or recursive SQL for hierarchical table computations."
    context = (
        f"`{config.target_column_name}` in `{config.target_table_name}` is a computed value in a hierarchical table. "
        + parent_ref_info
        + f"Sample rows: {data_for_sharing_with_LLM_str}. "
        f"Textual formula: [[[FORMULA START]]] {formula_based_on_data_sharing} [[[FORMULA END]]]."
    )
    focus = f"Generate SQL that computes `{config.target_column_name}` using hierarchical self-join or recursive CTE patterns."
    task = (
        f"Generate the SQL computation expression for the hierarchical formula. "
        + (
            f"The query must return {number_of_pks_in_target_table} PK columns {names_of_pk_columns_of_target_table}, computed_value, and actual_value. "
            if number_of_pks_in_target_table > 0
            else "The query must return computed_value and actual_value. "
        )
        + "Use self-joins or recursive CTEs to access parent/child rows."
    )
    reasoning = (
        "Step 1: Set up the self-join using the parent reference columns. "
        "Step 2: Apply the formula logic to compute the target column. "
        "Step 3: Handle the PK structure correctly."
    )
    constraints = "Provide only the executable SQL query without explanations."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


# ============================================================================
# ROW-SCOPE PROMPTS
# ============================================================================

def prompt_find_row_scope_formulas(
    target_table_description: str
) -> str:
    """Generate prompt to find formulas for row-scope computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying row-scope computed column formulas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — computation depends only on columns in the same row."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
        f"`{config.target_column_name}` is a row-scope computed value where the computation depends only on other columns in the same row. "
        f"Find formulas that compute `{config.target_column_name}` using only other columns in the same row (no aggregation, no joins needed). "
        f"Use the schema and data metadata to explore potential formulas. "
        f"If you suspect more than one candidate formula, provide them all with confidence scores summing to 100."
    )
    reasoning = (
        "Step 1: Check for arithmetic relationships between columns in the same row. "
        "Step 2: Look for string concatenation or formatting patterns. "
        "Step 3: Check for conditional/CASE-based derivations."
    )
    constraints = "Only consider columns in the same row. No aggregation functions. No joins."
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_generate_sql_for_row_scope(
    target_table_description: str,
    formula: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Generate prompt to create SQL query for row-scope computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL developer generating row-scope SQL expressions."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — row-scope formula: {formula}."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` is a row-scope computed value. "
        f"Generate SQL that computes `{config.target_column_name}` using only same-row column values. "
        + (
            f"Return: {names_of_pk_columns_of_target_table}, computed_value, and actual_value. "
            if number_of_pks_in_target_table > 0
            else "Return: computed_value and actual_value. "
        )
    )
    reasoning = (
        "Step 1: Translate the formula into SQL expressions. "
        "Step 2: Handle data type conversions. "
        "Step 3: Add CASE statements for conditional logic."
    )
    constraints = (
        "No aggregation functions across rows. No joins. Simple column arithmetic only. "
        "Provide only the executable SQL query without explanations."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


# ============================================================================
# CROSS-TABLE PROMPTS
# ============================================================================

def prompt_is_count_or_exist(
    target_table_description: str
) -> str:
    """Generate prompt to determine if computed value is based on counting or existence in other tables."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying COUNT or EXISTS patterns in computed columns."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — determine if it is derived from counting or existence checks."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
        f"Determine if `{config.target_column_name}` of a certain row is derived from counting other rows or checking existence in related tables. "
        f"For example, 'number_of_passengers' in 'trip' table could be derived from COUNT of rows in 'tickets' table for that trip. "
        f"Or 'is_canceled' could be TRUE if a row exists in 'canceled_trips' table for that trip."
    )
    reasoning = (
        "Step 1: Check if the column's data type suggests a count or boolean. "
        "Step 2: Look for related tables that could be counted. "
        "Step 3: Consider WHERE conditions that would filter the count."
    )
    constraints = (
        "Answer `yes` ONLY if the column is clearly an integer count or a boolean existence flag. "
        "Answer `no` if the column is a decimal/float, a weighted average, a ratio, or any continuous numeric value — these are NOT count/exist patterns. "
        "I am a program. Respond strictly with the JSON below."
    )
    payload = {"is_count_or_exist": "yes or no"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_find_count_exists_formulas(
    target_table_description: str
) -> str:
    """Generate prompt to find COUNT or EXISTS based formulas across tables."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL developer generating COUNT/EXISTS SQL formulas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — COUNT or EXISTS cross-table formula discovery."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
        f"`{config.target_column_name}` can be computed by COUNTing or checking EXISTence of rows in other tables. "
        f"Generate SQL expressions that use COUNT or EXISTS subqueries to compute `{config.target_column_name}`. "
        f"Use COUNT(*), SUM(CASE WHEN EXISTS ...), or IF EXISTS patterns. "
        f"Use PK-FK relationships to determine join conditions. "
        f"Provide up to {config.max_candidate_formulas_count_exists} candidate formulas with confidence scores summing to 100. "
        f"Include: textual_formula, used_tables, used_columns, confidence_score, and computation_sql_query."
    )
    reasoning = (
        "Step 1: Identify the related table to count from. "
        "Step 2: Define the JOIN condition linking to the target table. "
        "Step 3: Add any filtering conditions. "
        "Step 4: Wrap in a subquery."
    )
    constraints = "Return strictly in JSON format."
    payload = {"candidate_formulas": [{"textual_formula": "...", "used_tables": [], "used_columns": [], "confidence_score": 100, "computation_sql_query": "..."}]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_identify_candidate_tables_for_count(
    target_table_description: str
) -> str:
    """Generate prompt to identify which tables to count/check for existence."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst finding tables that could contribute to a COUNT/EXISTS formula."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — identify candidate tables for COUNT/EXISTS."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` can be computed from other tables. "
        f"Identify which tables in the database are the best candidates for COUNT or EXISTS formulas for `{config.target_column_name}`. "
        f"For example, if `{config.target_column_name}` is 'number_of_orders', look for an 'orders' or 'order_items' table. "
        f"Provide the candidate table names with explanations."
    )
    reasoning = (
        "Step 1: Check foreign key relationships pointing to or from the target table. "
        "Step 2: Consider table sizes and relationship cardinality. "
        "Step 3: Look for tables whose row counts could logically relate to the target column values."
    )
    constraints = "Consider PK-FK relationships, table names, column meanings, and the nature of the target column."
    payload = {"candidate_tables": [{"table_name": "...", "reason": "..."}]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# PATTERN CLASSIFICATION PROMPTS
# ============================================================================

def prompt_generate_across_table_sql(
    target_table_description: str,
    formula: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Generate prompt to create SQL query for across-table computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL developer generating cross-table JOIN-based SQL formulas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — cross-table formula: {formula}."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` is computed from other tables. "
        f"Generate SQL that JOINs multiple tables to compute `{config.target_column_name}`. "
        + (
            f"Return {number_of_pks_in_target_table} PK columns {names_of_pk_columns_of_target_table}, computed_value, and actual_value. "
            if number_of_pks_in_target_table > 0
            else "Return computed_value and actual_value. "
        )
    )
    reasoning = (
        "Step 1: Build the JOIN chain from the target table to the source tables. "
        "Step 2: Apply the formula logic across the joined tables. "
        "Step 3: Ensure GROUP BY is used when aggregating."
    )
    constraints = (
        "Use proper join conditions based on PK-FK relationships. "
        "Use subqueries to avoid nested aggregates. "
        "Preserve all rows in the outer table. "
        "Provide only the executable SQL query."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


def prompt_find_common_formula_pattern(
    target_table_description: str,
    formula_list: list
) -> str:
    """Generate prompt to find the most common semantic formula pattern."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert formula analyst extracting recurring patterns from multiple formula candidates."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — find the dominant semantic pattern across candidates."
    task = (
        f"`{config.target_column_name}` in `{config.target_table_name}` is a computed value. "
        f"I have multiple candidate formulas but many may be semantically equivalent. "
        f"Here are the formulas: {formula_list}. "
        f"Identify the most common semantic formula pattern across the provided list of formulas."
    )
    reasoning = (
        "Step 1: Group formulas by semantic similarity. "
        "Step 2: Find the pattern that appears most frequently. "
        "Step 3: Express the pattern abstractly."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    payload = {"formula_pattern": "the common formula pattern"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_extract_semantic_formula(
    target_table_description: str,
    formula_list: str
) -> str:
    """Generate prompt to extract the semantic meaning of formulas."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert at distilling the semantic meaning of SQL formulas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — extract the dominant semantic formula."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
        f"I have a list of potential formulas: {formula_list}. "
        f"Some formulas are semantically the same. Extract and return the most frequent semantic formula from the list."
    )
    reasoning = (
        "Step 1: Group semantically equivalent formulas. "
        "Step 2: Identify the group with the highest count. "
        "Step 3: Return the canonical form of that group."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    payload = {"semantic_formula": "the most frequent semantic formula"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_classify_table_scope_type(
    target_table_description: str
) -> str:
    """Generate prompt to classify if computation is row-scope, single-table, or cross-table."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst classifying the computation scope of a derived column."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — classify computation scope."
    task = (
        f"`{config.target_column_name}` in `{config.target_table_name}` has missing values. "
        f"Classify whether `{config.target_column_name}`'s computation is row-scope, single-table-scope, or cross-table-scope. "
        f"Options: (1) row-scope: only using columns in the same row; "
        f"(2) single-table-scope: using other rows in the same table; "
        f"(3) cross-table-scope: using rows in other tables."
    )
    reasoning = (
        "Step 1: Check if computation uses only same-row values (row-scope). "
        "Step 2: Check if it requires aggregation within the same table (single-table-scope). "
        "Step 3: Check if it requires data from other tables (cross-table-scope)."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    payload = {"scope_type": "row-scope or single-table-scope or cross-table-scope"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# SINGLE TABLE SCOPE PROMPTS
# ============================================================================

def prompt_is_single_table_computed_value(
    target_table_description: str
) -> str:
    """Generate prompt to determine if a column is computed from other rows in same table."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst determining computation scope."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — single-table computation check."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` column has missing values. "
        f"Determine if `{config.target_column_name}` can be computed using only data within the same table (not cross-table). "
        f"Examples: cumulative sums, running totals, parent values in hierarchies, previous/next row values."
    )
    reasoning = (
        "Step 1: Check if the computation pattern matches same-table patterns (cumulative, hierarchical, chaining). "
        "Step 2: Check whether any cross-table data would be required. "
        "Step 3: Conclude yes or no based on the evidence."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    payload = {"is_computed": "yes or no"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_generate_single_table_formula(
    target_table_description: str
) -> str:
    """Generate prompt to find formula for single-table computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert SQL developer generating single-table aggregation formulas."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — single-table formula discovery."
    task = (
        f"In `{config.target_table_name}` table, `{config.target_column_name}` is computed from other rows in the same table. "
        f"Generate the SQL formula that computes `{config.target_column_name}` using only data from the same table. "
        f"Consider the table structure: is it hierarchical, chained, or cumulative? "
        f"Provide candidate formulas with descriptions of how other rows are accessed. "
        f"Use terms like 'previous_row', 'next_row', 'parent_row', 'children_rows', or 'all_rows'."
    )
    reasoning = (
        "Step 1: Identify the structure pattern (hierarchical, chaining, cumulative). "
        "Step 2: Determine how rows reference each other. "
        "Step 3: Express the formula using appropriate row-access terms."
    )
    constraints = "Only use data from within the same table. No cross-table joins."
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_classify_as_table_scope(
    target_table_description: str
) -> str:
    """Generate prompt to classify single-table computation as chaining, hierarchical, or other."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst classifying single-table computation types."
    context = initial_prompt_str + " " + target_table_description
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — classify single-table computation type."
    task = (
        f"`{config.target_column_name}` in `{config.target_table_name}` is computed from rows in the same table. "
        f"Classify the computation as chaining, hierarchical, or other. "
        f"Options: (1) chaining: each row has previous/next row (like transactions in sequence); "
        f"(2) hierarchical: tree structure with parent/child rows; "
        f"(3) other: cumulative, rolling window, or aggregation pattern."
    )
    reasoning = (
        "Step 1: Check if the formula requires ordered row sequences (chaining). "
        "Step 2: Check if it requires parent-child self-references (hierarchical). "
        "Step 3: Otherwise classify as other."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    payload = {"table_scope_type": "chaining or hierarchical or other"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def _get_json_prompt(payload: dict) -> str:
    """Helper to format JSON response instructions.

    Args:
        payload: Dictionary structure for expected JSON response

    Returns:
        Formatted instruction string for JSON responses
    """
    prompt_text = "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "Write all string values on a single line — do NOT include raw newlines or line breaks inside JSON string values. "
    prompt_text += "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


# --- Initial context / data-sharing prompts (used in llm_functions.py) ---

def prompt_schema_intro(database_name: str) -> str:
    prompt_text = f"I have a database in MySQL (named '{database_name}') with the following schema. "
    prompt_text += "Here is the database schema: "
    return prompt_text


def prompt_statistics_header() -> str:
    prompt_text = "Let me share with you metadata (i.e. statistics) of each column of each table (9 metadata tuple per column) as follows \" In table 'tbl_name' ('column_name', data_type, total_number_of_values, "
    prompt_text += "number_of_null_values, number_of_distinct_values, is_category, min_value, max_value, average_value)\". "
    prompt_text += "For string data types like char and varchar min_value, max_value and average_value are not provided and semantic_topic is provided instead i.e. 7 metadata tuple per column as follows "
    prompt_text += "\"In table 'tbl_name' ('column_name', data_type, total_number_of_values, number_of_null_values, number_of_distinct_values, is_category, semantic_topic)\". Let us start: "
    return prompt_text


def prompt_column_metadata_string(col_name, data_type, total, nulls, distinct, is_category, topic) -> str:
    return f"('{col_name}', {data_type}, {total}, {nulls}, {distinct}, {is_category}, {topic}) "


def prompt_column_metadata_numeric(col_name, data_type, total, nulls, distinct, is_category, min_val, max_val, avg_val) -> str:
    return f"('{col_name}', {data_type}, {total}, {nulls}, {distinct}, {is_category}, {min_val}, {max_val}, {avg_val}) "


def prompt_table_metadata_row(tbl_name: str, columns_metadata_str: str) -> str:
    return f"In table '{tbl_name}' {columns_metadata_str}. "


def prompt_distinct_values_header() -> str:
    prompt_text = "Let me share with you some distinct values of each column of each table. "
    prompt_text += "I will send the data as follows: \" In table 'tbl_name': ('column_1_name', [distinct_value_1, distinct_value_2, etc]) ('column_2_name', [distinct_value_1, distinct_value_2, etc]) ... etc. "
    prompt_text += "Let us start. "
    return prompt_text


def prompt_distinct_values_column_item(col_name: str, values_str: str) -> str:
    return f"('{col_name}', [{values_str}]) "


def prompt_distinct_values_table_row(tbl_name: str, values_str: str) -> str:
    return f"In table '{tbl_name}': {values_str}. "


def prompt_sample_rows_header() -> str:
    prompt_text = "In addition, let me send you a few sample rows of each table. I excluded some columns like longtext, blob, etc. "
    prompt_text += "I will send you the rows of each table as follows \" In table 'table_name' sample rows columns names are (columns_name_1, columns_name_2, etc) and rows values are ([(row_1), (row_2), (row_3), etc]) \". "
    prompt_text += "Note that, the number of items of a row e.g. row_1 is equal to the number of columns names items e.g. 3 if columns names are(columns_name_1, columns_name_2, columns_name_3). "
    prompt_text += "Let us start. "
    return prompt_text


def prompt_table_sample_rows(tbl_name: str, columns_names_str: str, result: str) -> str:
    return f"In table '{tbl_name}' sample rows columns names are ({columns_names_str}) and rows values are({result}). "


def prompt_data_sharing_section(target_table_name: str, data_sharing_str: str) -> str:
    prompt_text = f" Moreover, I will share with you rows from the table '{target_table_name}' with their joint rows of the parents tables of {target_table_name} with rows from their "
    prompt_text += f"(I mean the parents tables) other children tables (i.e. sibling tables of {target_table_name}) and "
    prompt_text += f"their joint rows of the children tables of {target_table_name} and joint rows from thier other parent tables. "
    prompt_text += f"Here are the rows: {data_sharing_str}"
    return prompt_text


def prompt_detect_topic_retry() -> str:
    role = "You are a semantic analyst identifying the topic of a list of values."
    task = "Your previous answer was too long. Return only 1 to 3 words identifying the topic."
    output = json.dumps({"topic": "one to three words"}, ensure_ascii=False)
    return _build_prompt(role=role, task=task, output=output)


def prompt_rename_table_retry() -> str:
    role = "You are a database naming expert."
    task = "Your previous answer contained multiple words. Return exactly one word: the new table name, or 'representative_name' if the current name is already good."
    output = json.dumps({"table_name": "new_name_or_representative_name"}, ensure_ascii=False)
    return _build_prompt(role=role, task=task, output=output)


def prompt_rename_column_retry() -> str:
    role = "You are a database naming expert."
    task = "Your previous answer contained multiple words. Return exactly one word: the new column name, or 'representative_name' if the current name is already good."
    output = json.dumps({"column_name": "new_name_or_representative_name"}, ensure_ascii=False)
    return _build_prompt(role=role, task=task, output=output)


# ============================================================================
# NEW EXTRACTED INLINE PROMPT FUNCTIONS
# ============================================================================

def prompt_diagnose_chaining_formula_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
    current: str,
    data_sharing_str: str,
    formula: str,
    accuracy: float,
    diagnoses_result_str: str,
    grouping_columns: list,
    chaining_columns: list
) -> str:
    """Diagnose an incorrect chaining formula and request a corrected one."""
    payload = {
        "is_catched": " 'yes' if you find out the cause of the error and 'no' otherwise ",
        "cause_of_error": " explain the root cause of the error briefly ",
        "corrected_formula": " write the new correct formula here ",
        "columns": ["X", "Y"]
    }

    grouping_info = (
        f"The grouping columns in the `{target_tbl}` table are {grouping_columns}. "
        if len(grouping_columns) > 1
        else f"The grouping column in the `{target_tbl}` table is {grouping_columns[0]}. "
    )
    chaining_info = (
        f"And the chaining columns in the `{target_tbl}` table are {chaining_columns}. "
        if len(chaining_columns) > 1
        else f"And the chaining column in the `{target_tbl}` table is {chaining_columns[0]}. "
    )

    role = "You are an expert SQL debugger analyzing and correcting chaining table formula mismatches."
    context = (
        f"Here is a description of the `{target_tbl}` table: [[[START OF DESCRIPTION]]] {target_tbl_description} [[[END OF DESCRIPTION]]]. "
        f"`{target_tbl}` is a chaining table. "
        "The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        "Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
        "[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        "In this example, the table is split into two groups. Column A and column B are called 'grouping columns'. Column C is called 'chaining column'. "
        "Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
        "[Example 2] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining columns. "
        + grouping_info + chaining_info
        + f"Sample rows of `{target_tbl}`: {data_sharing_str}."
    )
    focus = f"Diagnose why the formula for `{target_col}` in the chaining table `{target_tbl}` produces incorrect results (accuracy: {accuracy}%)."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value derived from {current} rows of the same table. "
        f"I tried to calculate the missing values of `{target_col}` using the following formula but the results show that the formula is incorrect ({accuracy}% accuracy). "
        f"Incorrect formula: [[[START OF INCORRECT FORMULA]]] {formula} [[[END OF INCORRECT FORMULA]]]. "
        f"Random computation query results for comparison: {diagnoses_result_str}. "
        "Identify the root cause of the mismatch and provide a corrected formula. "
        f"Also return the column names needed for the formula to compute `{target_col}`."
    )
    reasoning = (
        "Step 1: Compare actual_value vs. computed_value in the diagnosis results to identify the pattern of error. "
        "Step 2: Cross-reference with the sample rows to see how the chaining/grouping works in practice. "
        "Step 3: Identify the specific incorrect assumption in the formula (wrong grouping condition, off-by-one, wrong column, etc.). "
        "Step 4: Propose a minimal corrected formula that fixes the mismatch."
    )
    constraints = (
        "The goal is to make computed_value equal actual_value. The actual_value is correct but the computed_value is not. "
        "Focus on the sample rows and computation query results to find the error. "
        "These random computation query results are randomly selected (not forming chains) and are useful for comparing predicted vs actual values."
    )
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_corrected_sql_for_chaining_table(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
    data_sharing_str: str,
    incorrect_formula: str,
    corrected_formula: str,
    cause_of_error: str,
    grouping_columns: list,
    chaining_columns: list,
    chaining_columns_str: str,
    number_of_pks: int,
    pk_columns_names: list
) -> str:
    """Generate corrected SQL query for chaining table after diagnosing formula error."""
    role = "You are an expert SQL developer correcting a chaining-table computation formula."
    context = (
        f"Here is a description of the `{target_tbl}` table: [[[START OF DESCRIPTION]]] {target_tbl_description} [[[END OF DESCRIPTION]]]. "
        f"`{target_tbl}` is a chaining table where each row has a previous row (except the first) and a next row (except the last). "
        "Each chaining table is split into groups and in each group there is a chain. "
        "[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
        "Column A and column B are called 'grouping columns'. Column C is called 'chaining column'. "
        "[Example 2] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
        "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
        "In this example, A is the grouping column and B and C are the chaining columns. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
        f"Sample rows of `{target_tbl}`: {data_sharing_str}. "
        f"Correct formula: [[[CORRECT FORMULA START]]] {corrected_formula} [[[CORRECT FORMULA END]]]. "
        f"Previously incorrect formula: [[[INCORRECT FORMULA START]]] {incorrect_formula} [[[INCORRECT FORMULA END]]]. "
        f"Reason for incorrectness: [[[REASON OF INCORRECTNESS START]]] {cause_of_error} [[[REASON OF INCORRECTNESS END]]]."
    )
    focus = f"Generate corrected SQL for `{target_col}` in the chaining table `{target_tbl}` using previous or next rows."
    task = (
        f"As an NL-to-SQL task, reflect the corrected textual formula on an SQL query that computes `{target_col}` in `{target_tbl}` using previous or next rows. "
        "The computation query shall not modify or fill missing values — it is only to verify whether the formula is correct. "
        + (
            f"The computation query is a select query that returns two columns: computed_value (from the textual formula) and actual_value (the actual value of `{target_col}`). "
            if number_of_pks == 0
            else f"The computation query is a select query that returns {number_of_pks + 2} columns: the primary keys of `{target_tbl}` {pk_columns_names}, computed_value (from the textual formula), and actual_value (the actual value of `{target_col}`). "
        )
        + f"computed_value is the predicted value of `{target_col}` based on the textual formula. "
        f"Alias the `{target_tbl}` table in the outer query's FROM clause as target_table. "
        f"Avoid making the same mistake as the incorrect formula."
    )
    reasoning = (
        "Step 1: Apply the identified correction to the formula. "
        "Step 2: Build the nested subquery to access the previous or next row using the chaining column criteria. "
        "Step 3: Apply grouping column conditions to locate the correct row within the chain. "
        "Step 4: Handle edge cases — exclude first rows of chains if using previous row, or last rows if using next row."
    )
    constraints = (
        f"Rule 1: Use a nested subquery (not self-join) to compute the value from next/previous row(s) in `{target_tbl}` — the nested query shall be in the outer SELECT and return ONLY one value (aliased computed_value). "
        "Rule 2: Rounding is not required at all. "
        "Rule 3: Only use columns that exist in the schema. "
        "Rule 4: Cast UNSIGNED columns to SIGNED before arithmetic that may produce negative values. "
        f"Rule 5: Exclude rows that cannot be computed (first rows of chains if using previous row; last rows if using next row) via the WHERE clause. "
        f"Rule 6: Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias of `{target_tbl}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. "
        f"Pay attention to the sample rows, especially the chaining criteria ({chaining_columns_str}) across rows. "
        "MySQL doesn't allow nested aggregate functions directly. "
        "Only output the executable SQL query without explanations. Be careful and make the computation query free-of-errors. The query shall be 100 percent compatible with the data samples."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


def prompt_is_count_or_exist_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Determine whether the target column is derived from counting/existence in other tables."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst identifying COUNT or EXISTS patterns in computed columns."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — determine if it is derived from counting or existence checks in other tables."
    task = (
        f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
        f"I need to find a formula that derives the missing values of `{target_col}` from other tables (using joins). "
        f"Before exploring formulas, determine whether `{target_col}` of a certain row is derived from counting other rows or checking existence in other tables. "
        f"For example, if the missing value is 'number_of_passengers' in a 'trip' table, then it can be derived from the count of rows in the 'tickets' table for that trip. "
        f"Another example: a boolean 'is_canceled' in a 'trip' table is True if a row exists in 'canceled_trips' for that trip, False otherwise. "
        f"Return 'yes' if `{target_col}` can be derived from counting or checking existence in other tables, and 'no' otherwise."
    )
    reasoning = (
        "Step 1: Check if the column's data type and name suggest a count or boolean. "
        "Step 2: Look for related tables that could be counted or checked for existence. "
        "Step 3: Use PK-FK relationships to determine which tables are relevant. "
        "Step 4: Conclude yes or no based on the semantic analysis."
    )
    constraints = (
        "The schema (especially the PK-FK dependencies) is essential to explore this. "
        "I am a program. Respond strictly with the JSON below."
    )
    payload = {"is_count_or_exist": "yes or no"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_count_or_exist_with_data_sharing(
    target_col: str,
    target_tbl: str,
    given_table_name: str,
    target_tbl_description: str,
    data_sharing_str: str,
    number_of_pks: int,
    pk_columns_names: list
) -> str:
    """Generate SQL formula for count/exist computed column using data samples from another table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " write here the most potential formula ",
                "computation_sql_query": f" the computation SQL query to compute {target_col} based on the textual formula",
                "confidence_score": " a number from 0 to 100"
            },
            {
                "textual_formula": " write here the other candidate formula, if any ",
                "computation_sql_query": f" the computation SQL query to compute {target_col} based on the textual formula",
                "confidence_score": " a number from 0 to 100"
            }
        ]
    }

    pk_clause = (
        f"The computation query is a select query that returns two columns: computed_value (from the textual formula) and actual_value (the actual value of `{target_col}`). "
        if number_of_pks == 0
        else (
            f"The computation query is a select query that returns {number_of_pks + 2} columns: the primary keys of `{target_tbl}` {pk_columns_names}, "
            f"computed_value (from the textual formula), and actual_value (the actual value of `{target_col}`). "
        )
    )

    role = "You are an expert SQL developer generating COUNT/EXISTS-based SQL formulas for cross-table derived columns."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — refine the COUNT-based formula using data samples from `{given_table_name}`."
    task = (
        f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
        f"I need to find a formula that derives the missing values of `{target_col}` using joins with `{given_table_name}`. "
        f"`{target_col}` can be derived from counting rows in the `{given_table_name}` table. "
        f"However, a simple COUNT(*) is inaccurate — the formula likely has conditions or requires minor deviation. "
        f"Use the schema and the following sample data points to refine the formula: [[[START OF SAMPLE POINTS]]] {data_sharing_str} [[[END OF SAMPLE POINTS]]]. "
        f"As an NL-to-SQL task, reflect the textual formula on an SQL query that computes `{target_col}` in `{target_tbl}` from `{given_table_name}`. "
        "The computation query shall not modify or fill missing values — it is only to verify the formula. "
        + pk_clause
        + f"computed_value is the predicted value of `{target_col}`. "
        f"Alias the `{target_tbl}` table in the outer query's FROM clause as target_table. "
        f"If you suspect more than one candidate formula, provide them all with confidence scores summing to 100."
    )
    reasoning = (
        "Step 1: Examine the sample data points to understand why a simple COUNT(*) is insufficient. "
        "Step 2: Identify the condition or filter that should be applied to the COUNT. "
        "Step 3: Build the SQL using LEFT JOIN and the COUNT aggregation with the identified condition. "
        "Step 4: Verify the formula matches the sample data points."
    )
    constraints = (
        "Rule 1: The computation SQL shall compute the computed_value using left joins and the COUNT aggregation function. "
        "Rule 2: The computed value must be computed from the columns of the database provided in the schema. "
        "Rule 3: In case of string comparisons, do not use 'FIND_IN_SET' and 'REPLACE' functions — use the 'LIKE' function instead. "
        "Pay attention to the sample rows. Ensure SQL is valid MySQL syntax. "
        "Only output the executable SQL query without explanations."
    )
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_identify_candidate_table_for_count(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Identify which table to use when computing a count/exist formula for the target column."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    payload = {
        "candidates": [
            {
                "table_name": " write here the name of the most potential candidate table ",
                "confidence_score": " a number from 0 to 100"
            },
            {
                "table_name": " write here the name of other candidate table, if any ",
                "confidence_score": " a number from 0 to 100"
            }
        ]
    }
    role = "You are an expert database analyst finding tables that could contribute to a COUNT/EXISTS formula."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — identify the candidate table to count rows from."
    task = (
        f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
        f"`{target_col}` can be derived from counting other rows in other tables. "
        f"Identify which tables in the database are the best candidates for COUNT or EXISTS formulas for `{target_col}`. "
        f"Look at the schema and the data samples to determine which table's row count gives the missing values. "
        f"Provide the table name(s). If you suspect more than one candidate table, provide them all with confidence scores summing to 100. Do not over do it — if one table is obvious, just return it."
    )
    reasoning = (
        "Step 1: Check foreign key relationships pointing to or from the target table. "
        "Step 2: Consider table sizes and relationship cardinality. "
        "Step 3: Look for tables whose row counts could logically relate to the target column values."
    )
    constraints = "I am a program. Respond strictly with the JSON below."
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_across_tables_formula_with_data(
    target_col: str,
    target_tbl: str,
    other_used_tables_names_str: str,
    used_tables: list,
    data_sharing_str: str,
    target_tbl_description: str,
    number_of_pks: int,
    pk_columns_names: list
) -> str:
    """Generate formula and SQL for cross-table computation using shared data samples."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " write here the most potential formula ",
                "computation_sql_query": f" the computation SQL query to compute {target_col} based on the textual formula",
                "confidence_score": " a number from 0 to 100"
            },
            {
                "textual_formula": " write here the other candidate formula, if any ",
                "computation_sql_query": f" the computation SQL query to compute {target_col} based on the textual formula",
                "confidence_score": " a number from 0 to 100"
            }
        ]
    }

    pk_clause = (
        f"The computation query is a select query that returns two columns: computed_value (from the textual formula) and actual_value (the actual value of `{target_col}`). "
        if number_of_pks == 0
        else (
            f"The computation query is a select query that returns {number_of_pks + 2} columns: the primary keys of `{target_tbl}` {pk_columns_names}, "
            f"computed_value (from the textual formula), and actual_value (the actual value of `{target_col}`). "
        )
    )

    tables_clause = (
        f"`{target_col}` can be derived from other rows and columns (using joins) in `{other_used_tables_names_str}` table. "
        if len(used_tables) == 1
        else f"`{target_col}` can be derived from other rows and columns (using joins) in some of the following tables: {other_used_tables_names_str}. "
    )

    multi_table_note = (
        f"Some of the {other_used_tables_names_str} tables may be useless. "
        f"You need to look at the data points and see how the value of `{target_col}` in `{target_tbl}` can be calculated from the rows/columns of the {other_used_tables_names_str} tables. "
        if len(used_tables) > 1
        else ""
    )

    role = "You are an expert SQL developer generating cross-table JOIN-based SQL formulas for derived columns."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — cross-table formula using data samples from {other_used_tables_names_str}."
    task = (
        f"In `{target_tbl}` table, `{target_col}` column has some missing values derived from other tables using joins. "
        f"I already tested single-table formulas for `{target_col}` — they are insufficient. "
        f"The formula must use data from other tables. Do not provide a single-table formula even if one exists. "
        + tables_clause
        + f"Data samples (data points) of {target_tbl} and {other_used_tables_names_str}: [[[START OF DATA POINTS]]] {data_sharing_str} [[[END OF DATA POINTS]]]. "
        + multi_table_note
        + f"Based on the schema and data points, provide the textual formula to compute `{target_col}` from {other_used_tables_names_str}. "
        f"As an NL-to-SQL task, reflect the textual formula on an SQL query that computes `{target_col}` in `{target_tbl}` from {other_used_tables_names_str}. "
        "The computation query shall not modify or fill missing values — it is only to verify the formula. "
        + pk_clause
        + f"computed_value is the predicted value of `{target_col}`. "
        f"Alias the `{target_tbl}` table in the outer query's FROM clause as target_table. "
        "If you suspect more than one candidate formula, provide them all with confidence scores summing to 100. Multiple candidates are preferred."
    )
    reasoning = (
        "Step 1: Examine the data points to identify the relationship between `{target_col}` values and columns in the other tables. "
        "Step 2: Build the join chain from the target table to the source tables using PK-FK relationships. "
        "Step 3: Apply the formula logic across joined tables. "
        "Step 4: Use subqueries to compute aggregations before joining to avoid nested aggregate errors."
    )
    constraints = (
        "Rule 1: Do not use aggregation functions on values retrieved from left joins — put aggregation inside the join subquery. "
        "Example of wrong SQL: SELECT id, SUM(i.amount) - SUM(o.amount) as balance from account a left join (select account_id, amount from income) as i on a.id = i.account_id ... "
        "Example of correct SQL: SELECT id, total_income.computed_value - total_outcome.computed_value as balance from account a left join (select account_id, sum(amount) as computed_value from income group by account_id) as total_income on a.id = total_income.account_id ... "
        "Always alias the computed column as `computed_value` inside the subquery, then reference it as `subquery_alias.computed_value AS computed_value` in the outer SELECT. "
        "Avoid nesting aggregate functions; compute them in subqueries. Avoid creating temporary tables. "
        "Rule 2: Rounding is not required. "
        f"Rule 3: Only use columns from the schema. Only use the following tables: {other_used_tables_names_str}. "
        "Rule 4: Cast UNSIGNED columns to SIGNED before arithmetic that may produce negative values. "
        f"Rule 5: Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias or direct table reference to `{target_tbl}`, and not inside any subquery, CTE, or nested SELECT. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The computed_value must be derived entirely from columns of other tables ({other_used_tables_names_str}). "
        f"Rule 6: Do NOT create a self-join. `{target_tbl}` must appear EXACTLY ONCE in the entire SQL (as `target_table` in the outer FROM clause). Do NOT reference `{target_tbl}` inside a derived table (subquery) used in a JOIN — even if the subquery is aliased differently, it is still a self-join if it reads from `{target_tbl}`. The JOIN must connect `target_table` to real tables from: {other_used_tables_names_str}. A query that only reads from `{target_tbl}` — even via window functions, self-aggregation, or derived subqueries — is forbidden. "
        "Do NOT propose data-fitting formulas. Do not hardcode specific data instances — person names, IDs, enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. The formula must follow structural schema logic, not memorized training data. Example of forbidden: CASE WHEN FirstName IN ('Ken', 'Michael', ...) THEN 'M'. "
        "Pay attention to the sample data points. Ensure SQL is valid MySQL syntax. Only output the executable SQL query."
    )
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_across_tables_candidate_formulas(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Request candidate formulas for cross-table computation without data sharing."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " write here the most potential formula ",
                "used_tables": " Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas",
                "used_columns": " Only the names of the columns that are used in the textual_formula do not add the joining columns",
                "confidence_score": " a number from 0 to 100"
            },
            {
                "textual_formula": " write here the other candidate formula, if any ",
                "used_tables": " Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas ",
                "used_columns": " Only the names of the columns that are used in the textual_formula do not the joining columns",
                "confidence_score": " a number from 0 to 100"
            }
        ]
    }
    payload_example_1 = {
        "candidate_formulas": [
            {
                "textual_formula": " T.C = IF T1.A is True then T.C = SUM(T2.X) ELSE (i.e. T1.A is False) then T.C = SUM(T2.X - T2.Y) ",
                "used_tables": ["T1", "T2"],
                "used_columns": ["T1.A", "T2.X", "T2.Y"],
                "confidence_score": "70"
            }
        ]
    }
    payload_example_2 = {"candidate_formulas": "NaN"}

    role = "You are an expert database analyst discovering cross-table computed column formulas."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — cross-table formula discovery (schema only, no data samples)."
    task = (
        f"In `{target_tbl}` table, `{target_col}` column has some missing values derived from other tables using joins. "
        f"I already tested single-table formulas for `{target_col}` — they are insufficient. "
        f"The formula must use data from other tables. Do not provide a single-table formula even if one seems possible. "
        f"Provide the formula(s) that compute `{target_col}` from other tables using joins. "
        f"Expect up to {config.max_candidate_formulas_across_tables} realistic candidate formulas. Do not limit to single-hop joins — the formula may require 2-hop, 3-hop, or more. "
        "For each formula, provide the names of the tables and columns used. "
        "For example: table T has column C; T1 (parent of T) has columns A, B; T2 (child of T) has columns X, Y, Z. "
        "If the formula is: IF T1.A is True then T.C = SUM(T2.X) ELSE T.C = SUM(T2.X - T2.Y), then used_tables are [T1, T2] and used_columns are [T1.A, T2.X, T2.Y]. "
        "Provide confidence scores for each formula summing to 100."
    )
    reasoning = (
        "Step 1: Examine PK-FK relationships to find tables reachable from the target table. "
        "Step 2: Consider multi-hop join paths (2-hop, 3-hop, etc.). "
        "Step 3: For each candidate path, evaluate whether an aggregation or computation on the joined table could produce the target column values. "
        "Step 4: Rank candidates by plausibility and assign confidence scores."
    )
    constraints = (
        "The schema (especially PK-FK dependencies) is essential. "
        "Do not provide single-table formulas. Only cross-table formulas are accepted. "
        f"CRITICAL: Every candidate's `used_tables` MUST include at least one table other than `{target_tbl}`. "
        f"Do not return any formula whose `used_tables` consists solely of `{target_tbl}` (i.e. a self-join or self-aggregation on the target table) — these are strictly forbidden. "
        f"Also forbidden: any formula that computes `{target_col}` by reading `{target_col}` itself from `{target_tbl}` — e.g., MAX(`{target_tbl}`.`{target_col}`) GROUP BY pk — this is circular and must not be returned. "
        "Do NOT propose data-fitting formulas. Do not hardcode specific data instances — person names, IDs, enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. Formulas must follow structural schema logic, not memorized training data. "
        "List only the tables and columns directly used in the formula — not intermediate join tables unless they contribute data."
    )
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "In the above example, the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
        "If you do not find any formula, the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_common_formula_from_list(
    target_col: str,
    target_tbl: str,
    formula_list: list,
    target_tbl_description: str
) -> str:
    """Extract the most frequent semantic formula from a list of candidate formulas."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert formula analyst extracting the most frequent semantic formula from a list of candidates."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — find the dominant semantic formula from the candidate list."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
        f"I have a list of potential formulas to compute `{target_col}`. Some formulas in the list are semantically the same. "
        f"Here are the formulas: {formula_list}. "
        "Provide the most frequent semantic formula from the list."
    )
    reasoning = (
        "Step 1: Group semantically equivalent formulas together. "
        "Step 2: Count the size of each group. "
        "Step 3: Return the canonical form of the largest group."
    )
    constraints = "Return only the formula text without any explanation or justification."
    output = "Respond with only the formula text — no extra commentary."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_classify_table_type_chaining_or_hierarchical(
    target_col: str,
    target_tbl: str,
    common_formula: str,
    target_tbl_description: str
) -> str:
    """Classify the target table as a chaining table or a hierarchical table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst classifying single-table computation types."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — classify as chaining table or hierarchical table."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value derived from other rows in the same table. "
        f"A potential formula is: {common_formula}. "
        f"Classify `{target_tbl}` as either a 'chaining table' or a 'hierarchical table'. "
        "A chaining table is a table where each row has a previous row (except the first in the chain) and a next row (except the last in the chain). "
        "A hierarchical table is a table with a tree-like structure where each row has at most one parent row (except the root) and children rows (except leaves). "
        "Return only 'chaining table' or 'hierarchical table'."
    )
    reasoning = (
        "Step 1: Examine the formula to understand how rows reference each other. "
        "Step 2: Check if the table schema contains sequence/order columns (suggesting chaining) or parent-reference columns (suggesting hierarchical). "
        "Step 3: Cross-reference with the table description and column names to confirm."
    )
    constraints = "Return only 'chaining table' or 'hierarchical table' without any explanation or justification."
    payload = {"table_type": "chaining table or hierarchical table"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_row_scope_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list
) -> str:
    """Discover row-scope formulas for the target column using sample rows."""
    payload = {
        "formula_1": {
            "formula": f"{target_col} = X * 100 / square(Y) ... ",
            "columns": ["X", "Y"]
        },
        "formula_2": {
            "formula": f"{target_col} = A - (2 * B) ... ",
            "columns": ["A", "B"]
        }
    }

    role = "You are an expert database analyst identifying row-scope computed column formulas."
    focus = f"`{target_col}` in `{target_tbl}` — row-scope formula discovery using same-row column values."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value derived from other columns in the same row. "
        f"Provide the formula to compute `{target_col}` and the names of the columns in `{target_tbl}` needed for the formula. "
        f"Here are {len(result)} sample rows of `{target_tbl}`: columns names are ({columns_names_str}) and rows values are ({result}). "
        f"Provide all possible formulas to compute `{target_col}`."
    )
    reasoning = (
        "Step 1: Examine the sample rows and look for arithmetic, string, or conditional relationships between columns. "
        "Step 2: Test each candidate pattern against multiple rows to confirm consistency. "
        "Step 3: List all formulas that fit the data."
    )
    constraints = (
        f"`{target_col}` must be on the left side of the formula only — do not use `{target_col}` on the right side. "
        "Rely on the schema and the sample rows provided. No aggregation or cross-row access."
    )
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_row_scope_sql_generation(
    target_col: str,
    target_tbl: str,
    formula: str,
    columns_to_compute_str: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str,
    number_of_pks: int,
    pk_columns_names: list
) -> str:
    """Generate SQL query for a row-scope computed column formula."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)

    pk_clause = (
        f"The computation query is a select query that returns two columns: computed_value (from the textual formula) and actual_value (the actual value of `{target_col}`). "
        if number_of_pks == 0
        else (
            f"The computation query is a select query that returns {number_of_pks + 2} columns: the primary keys of `{target_tbl}` {pk_columns_names}, "
            f"computed_value (from the textual formula), and actual_value (the actual value of `{target_col}`). "
        )
    )

    role = "You are an expert SQL developer generating row-scope SQL expressions for computed columns."
    context = initial_prompt_str + " " + target_tbl_description
    focus = (
        f"`{target_col}` in `{target_tbl}` — row-scope formula: {formula}. "
        f"Sample rows: columns names are ({columns_names_str}) and rows values are ({result})."
    )
    task = (
        f"As an NL-to-SQL task, reflect the textual formula on an SQL query that computes `{target_col}` in `{target_tbl}` from {columns_to_compute_str}. "
        "The computation query shall not modify or fill missing values — it is only to verify the formula. "
        + pk_clause
        + f"computed_value is the predicted value of `{target_col}`. "
        f"Alias the `{target_tbl}` table in the outer query's FROM clause as target_table."
    )
    reasoning = (
        "Step 1: Translate the textual formula into a SQL expression using same-row column values only. "
        "Step 2: Handle any data type conversions required. "
        "Step 3: Add CASE statements for conditional logic if needed. "
        "Step 4: Verify the SQL expression matches the formula without introducing cross-row dependencies."
    )
    constraints = (
        f"Rule 1: The computation SQL shall compute the computed_value from `{target_tbl}` without any join or nested query. "
        "Rule 2: Rounding is not required. "
        "Rule 3: Only use columns that exist in the schema. "
        "Rule 4: Cast UNSIGNED columns to SIGNED before arithmetic that may produce negative values. "
        f"Rule 5: Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias of `{target_tbl}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. "
        "Pay attention to the sample rows. Ensure SQL is valid MySQL syntax. Only output the executable SQL query."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints)


def prompt_single_table_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str
) -> str:
    """Discover candidate formulas for a single-table computed column with sample data."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)

    sample_rows_note = (
        f"Here are {len(result)} sample rows of `{target_tbl}`: columns names are ({columns_names_str}) and rows values are ({result}). "
        f"These are randomly selected rows and the table is incomplete. "
        f"Use them to determine whether `{target_col}` of a certain row can be computed from other columns in the same row or requires accessing other rows."
        if len(result) > 0
        else ""
    )

    role = "You are an expert database analyst discovering single-table computed column formulas."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — single-table formula discovery."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value derived from other columns or rows in the same table. "
        f"Provide a formula (textual description, up to 200 characters) to compute `{target_col}` from other rows in `{target_tbl}`. "
        f"Clarify whether the formula requires accessing other rows from the table or not. "
        + sample_rows_note
        + " If you do not find a formula, respond with 'None'."
    )
    reasoning = (
        "Step 1: Examine each column in the same table for arithmetic or logical relationships with the target column. "
        "Step 2: Consider whether the formula needs cross-row access (e.g., cumulative sum, previous row reference). "
        "Step 3: Choose the most realistic and schema-compatible formula."
    )
    constraints = (
        "The formula shall be correct, realistic, and represent real cases. "
        "Return only the formula text without any explanation or justification. If no formula is found, return 'None'."
    )
    output = "Respond with only the formula text or 'None' — no extra commentary."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_table_scope_type_check(
    target_col: str,
    target_tbl: str,
    formula: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str
) -> str:
    """Determine if the single-table formula is table-scope or row-scope."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)

    sample_rows_note = (
        f"Also, here are {len(result)} sample rows of `{target_tbl}`: columns names are ({columns_names_str}) and rows values are ({result}). "
        if len(result) > 0
        else ""
    )

    role = "You are an expert database analyst classifying whether a computed column requires cross-row access or only same-row data."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — determine if the formula is table-scope or row-scope."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
        f"If `{target_col}` is computed from other rows in `{target_tbl}`, it is a table-scope computed column. "
        f"If it is computed from other columns in the same row only (no cross-row access), it is a row-scope computed column. "
        f"Example: if R2.x depends on function(R1.x) or function(R1.y), it is table-scope. "
        f"If R2.x depends only on function(R2.y) without using R1, it is row-scope. "
        f"Here is a textual description of the potential formula: {formula}. "
        + sample_rows_note
        + f"Return 'table-scope' if `{target_col}` in `{target_tbl}` requires cross-row access, or 'None' otherwise."
    )
    reasoning = (
        "Step 1: Analyze the formula to determine if it references values from other rows. "
        "Step 2: Cross-reference with the sample rows (if provided) to verify. "
        "Step 3: Classify as 'table-scope' if any other row's value is needed, 'None' if only same-row columns are used."
    )
    constraints = "Return only 'table-scope' or 'None' without any explanation or justification."
    payload = {"scope_type": "table-scope or None"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_is_single_table_computed_value_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Determine whether the target column can be computed from rows/columns in the same table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    role = "You are an expert database analyst determining whether a computed column requires cross-table joins or is derivable within its own table."
    context = initial_prompt_str + " " + target_tbl_description
    focus = f"`{target_col}` in `{target_tbl}` — determine if the formula requires only same-table data."
    task = (
        f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
        f"Determine whether `{target_col}` can be computed from other columns/rows in the same table `{target_tbl}` without joins to other tables. "
        f"To do so, find a formula that uses only columns from `{target_tbl}` to compute `{target_col}`. "
        f"Return 'yes' if such a formula exists, 'no' if accessing other tables is required."
    )
    reasoning = (
        "Step 1: Use the table name and all column names in `{target_tbl}` to explore potential formulas. "
        "Step 2: Expand abbreviations in column names to infer semantic meaning. "
        "Step 3: Consider reverse equations — e.g., if total_price = quantity * unit_price exists, then quantity = total_price / unit_price. "
        "Step 4: Consider three types of within-table computation: (a) row-wise — computed from same-row columns only; "
        "(b) chaining — each row has a previous/next row in sequence; "
        "(c) hierarchical — tree structure with parent/child rows. "
        "Step 5: Be realistic — neither overly pessimistic nor optimistic."
    )
    constraints = (
        "I am a program. Respond strictly with the JSON below. "
        "Return 'yes' only if a concrete single-table formula is plausible based on the schema."
    )
    payload = {"is_single_table_computed": "yes or no"}
    output = "Return the result STRICTLY in the JSON format described below, with no extra commentary. JSON format:" + json.dumps(payload, ensure_ascii=False) + ". Provide the JSON."
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_hierarchical_parent_reference_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Identify parent-reference columns for a hierarchical table (smartly-selected variant with full examples)."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)

    # Build identifier info
    if len(names_of_pk_columns_of_target_table) == 1:
        identifier_info = f"The identifier of rows in `{config.target_table_name}` is `{names_of_pk_columns_of_target_table[0]}`. "
    elif len(names_of_pk_columns_of_target_table) > 1:
        identifier_info = f"The identifier of rows in `{config.target_table_name}` is the following composite key: {names_of_pk_columns_of_target_table}. "
    else:
        identifier_info = ""

    # Build task instruction based on PK count
    if len(names_of_pk_columns_of_target_table) == 0:
        task_instruction = f"As `{config.target_table_name}` is a hierarchical table without a known identifier, provide the name of the parent-reference-column and the parent-referencing-column. "
    elif len(names_of_pk_columns_of_target_table) == 1:
        task_instruction = f"As `{config.target_table_name}` has one identifier `{names_of_pk_columns_of_target_table[0]}`, provide the name of the parent-referencing-column. "
    else:
        task_instruction = f"As `{config.target_table_name}` has a composite key identifier, provide the parent-referencing-column for each parent-reference-column. "

    payload = {
        "parent_reference_columns": [
            {
                "reference_1": ["identifier_1", "parent_reference_column_1"],
                "reference_2": ["identifier_2", "parent_reference_column_2"]
            }
        ]
    }
    payload_example_1 = {"parent_reference_columns": [{"reference_0": ["A", "C"]}]}
    payload_example_2 = {"parent_reference_columns": [{"reference_0": ["A", "C"], "reference_1": ["B", "D"]}]}

    role = "You are an expert database analyst identifying parent-child (hierarchical/self-referencing) table structures."
    context = (
        initial_prompt_str + " " + target_table_description + " "
        + identifier_info
        + f"`{config.target_table_name}` is a hierarchical table with a tree-like structure where each row has at most one parent row (except the root) and children rows (except leaves). "
        "Each row stores the identifier of its parent row in one of its columns. "
        "[Example 1] Assume a hierarchical table T has more than 3 columns (A, B, C ...). "
        "Column A is the identifier and Column C refers to the identifier of the parent row. "
        "Column C is called 'parent-referencing-column' and Column A is called 'parent-reference-column'. "
        "Sample rows: R1 (0, 'any', null, ...), R2 (1, 'any', 0, ...), R3 (2, 'any', 0, ...), R4 (3, 'any', 2, ...), R5 (4, 'any', null, ...), R6 (5, 'any', 4, ...). "
        "From the rows: R1 is parent of R2 and R3; R3 is parent of R4; R5 is parent of R6. R1 and R4 have no parents. "
        "[Example 2] Assume a hierarchical table T with composite primary key (A, B). "
        "Column C in child refers to Column A of the parent; Column D in child refers to Column B of the parent."
    )
    focus = f"`{config.target_column_name}` in `{config.target_table_name}` — identify parent-reference and parent-referencing columns."
    task = (
        f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value derived from other rows in the same hierarchical table. "
        + task_instruction
        + "Rely on the schema and the sample rows provided."
    )
    reasoning = (
        "Step 1: Look for self-referencing foreign keys in the schema. "
        "Step 2: Identify which column holds the parent row's identifier. "
        "Step 3: Verify by checking if any PK column is also referenced as a FK within the same table."
    )
    constraints = "If no hierarchical structure exists, return empty lists."
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "In [Example 1], the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
        "In [Example 2], the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


def prompt_hierarchical_candidate_formula_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str
) -> str:
    """Find candidate formulas for a hierarchical table (smartly-selected variant with full examples)."""
    from src.core.config import config

    # Build identifier info
    if len(names_of_pk_columns_of_target_table) == 1:
        identifier_info = f"The identifier of rows in `{config.target_table_name}` is `{names_of_pk_columns_of_target_table[0]}`. "
    elif len(names_of_pk_columns_of_target_table) > 1:
        identifier_info = f"The identifier of rows in `{config.target_table_name}` is the following composite key: {names_of_pk_columns_of_target_table}. "
    else:
        identifier_info = ""

    # Build parent reference info
    if len(parent_reference_columns_list) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            parent_ref_info = (
                f"The parent-reference-column is `{parent_reference_columns_list[0][0]}` "
                f"and its parent-referencing-column is `{parent_reference_columns_list[0][1]}`. "
            )
        else:
            parent_ref_info = (
                f"As `{config.target_table_name}` has a composite key identifier, "
                "here is the list of each pair of parent-reference-column and its parent-referencing-column: "
                + "".join(
                    f"Parent-reference-column is `{pr[0]}`, parent-referencing-column is `{pr[1]}`. "
                    for pr in parent_reference_columns_list
                )
            )
    else:
        parent_ref_info = ""

    payload = {
        "candidate_formulas": [
            {"textual_formula": f" write here the most potential formula to compute `{config.target_column_name}` "},
            {"textual_formula": f" write here the other candidate formula to compute `{config.target_column_name}`, if any "}
        ]
    }

    role = "You are an expert formula analyst working with hierarchical (parent-child) table computations."
    context = (
        f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
        + identifier_info
        + f"`{config.target_table_name}` is a hierarchical table with a tree-like structure where each row has at most one parent row (except the root) and children rows (except leaves). "
        "Each row stores the identifier of its parent row in one of its columns. "
        "[Example 1] Assume a hierarchical table T with columns (A, B, C ...). Column A is the identifier, Column C refers to the parent's identifier. "
        "Sample rows: R1 (0, 'any', null, ...), R2 (1, 'any', 0, ...), R3 (2, 'any', 0, ...), R4 (3, 'any', 2, ...). "
        "R1 is parent of R2 and R3; R3 is parent of R4. R1 and R4 have no parents. "
        "[Example 2] Hierarchical table T with composite key (A, B): Column C in child refers to Column A of the parent; Column D refers to Column B. "
        + parent_ref_info
        + f"Data samples of `{config.target_table_name}`: {data_for_sharing_with_LLM_str}."
    )
    focus = f"Target column `{config.target_column_name}` in hierarchical table `{config.target_table_name}`."
    task = (
        f"Based on the schema and data samples, provide the formula to compute `{config.target_column_name}` "
        f"from other columns and rows in `{config.target_table_name}`. "
        "The formula must be compatible with the data samples. "
        "Use terms such as 'parent_row', 'children_rows', and 'child_row'. "
        f"If you suspect more than one candidate formula, provide them all with confidence scores summing to 100. "
        "Do not overdo it — if one formula is clear, return just that one."
    )
    reasoning = (
        "Step 1: Understand the parent-child link defined by the reference columns. "
        "Step 2: Examine the data samples to identify how the target column value relates to parent or children rows. "
        "Step 3: Test the formula concept against the provided data samples. "
        "Step 4: Express the pattern using parent_row, child_row, or children_rows terms."
    )
    constraints = "Be concise. Provide only concrete formulas. The formula must be completely compatible with the data samples."
    output = (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON."
    )
    return _build_prompt(role=role, context=context, focus=focus, task=task, reasoning=reasoning, constraints=constraints, output=output)


# ============================================================================
# INITIAL PROMPT ASSEMBLY
# ============================================================================

def get_schema_prompt_text():
    db_schema_content = load_database_schema()
    return prompt_schema_intro(config.target_database_name) + " " + db_schema_content


def get_database_columns_metadata_prompt_text():
    db_columns_metadata = load_database_columns_metadata()
    return prompt_statistics_header() + " " + db_columns_metadata if db_columns_metadata != "" else ""


def get_database_distinct_values_prompt_text():
    db_distinct_values = load_database_distinct_values()
    return prompt_distinct_values_header() + " " + db_distinct_values if db_distinct_values != "" else ""


def get_database_sample_rows_prompt_text():
    db_sample_rows = load_database_sample_rows()
    return prompt_sample_rows_header() + " " + db_sample_rows if db_sample_rows != "" else ""


def get_initial_prompt_str(strategy: int):
    prompt_text = get_schema_prompt_text()
    if strategy == 1:
        return prompt_text
    prompt_text += get_database_columns_metadata_prompt_text()
    prompt_text += get_database_distinct_values_prompt_text()
    if strategy == 2:
        return prompt_text
    prompt_text += get_database_sample_rows_prompt_text()
    return prompt_text
