"""LLM Prompt Templates - Centralized prompt definitions for data imputation pipeline.

This module contains all prompt templates used by the pipeline to communicate with LLMs.
Prompts are organized by category: schema understanding, formula detection, SQL generation, etc.
Each function takes relevant parameters and returns a formatted prompt string.
"""

import json
from src.core.config import config
from src.steps.formula_common import load_database_columns_metadata, load_database_distinct_values, load_database_sample_rows, load_database_schema


# ============================================================================
# SCHEMA UNDERSTANDING PROMPTS
# ============================================================================

def prompt_get_table_description_columns(table_name: str) -> str:
    """Generate prompt to describe columns of a table.

    Args:
        table_name: Name of the table

    Returns:
        Prompt string asking for column descriptions
    """
    prompt_text = f"`{table_name}` contains multiple columns. Probably some columns names are not representative. "
    prompt_text += "Probably column names contain abbreviations. "
    prompt_text += "Provide a textual description of each column with fewer than 20 words. "
    prompt_text += f"Be concise. Do not explain columns whose names are clear. "
    prompt_text += f"Use the above information like the database schema, the table name (i.e. `{table_name}`), the names of other columns in the same table and other tables, the distinct values of the column and the random rows. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {
        "column_descriptions": [
            {"column_name": "...", "description": "..."}
        ]
    }
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_get_table_description_correlations(
    table_name: str,
    column_name: str,
    target_table_description: str,
) -> str:
    """Generate prompt to identify correlations within a table.

    Args:
        table_name: Name of the table
        column_name: Name of the column
        target_table_description: Previously generated table description

    Returns:
        Prompt string asking for in-table correlations
    """
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = f"In `{table_name}` table, probably `{column_name}` is correlated or can be derived/computed from other columns in the same table i.e. `{table_name}`. "
    prompt_text += f"Use the above information like the database schema, the table name (i.e. `{table_name}`), the names of other columns in the same table and other tables, the distinct values of the column and the random rows. "
    prompt_text += f"Describe only in-table correlations. Avoid, cross-table correlations i.e. avoid correlations between `{column_name}` and columns in other tables (other than `{table_name}`). "
    prompt_text += f"Be concise and do not overdo it. Maybe, `{column_name}` has no correlated column in `{table_name}`."
    prompt_text += f"Also, use the following table description: {target_table_description}. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {
        "correlations": "describe correlations here or None if none"
    }
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return initial_prompt_str + " " + prompt_text


# ============================================================================
# FORMULA DETECTION PROMPTS
# ============================================================================

def prompt_is_computed_column(
    target_table_description: str,
    target_column_name: str,
    target_table_name: str,
    strategy: int = 1
) -> str:
    """Generate prompt to determine if a column is computed/derived.

    Args:
        target_table_description: Table description with column details
        target_column_name: Target column name
        target_table_name: Target table name
        strategy: Data sharing strategy (1=schema only, 2=+statistics, 3=+rows)

    Returns:
        Prompt string asking if column can be computed
    """
    initial_prompt_str = get_initial_prompt_str(strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{target_table_name}` table, `{target_column_name}` column has some missing values. "
    prompt_text += f"How the `{target_column_name}` column in the `{target_table_name}` table can be calculated? Provide a formula (i.e. equation). "
    prompt_text += "Probably the formula include values of other columns in the same table or in other tables. "
    prompt_text += "Use the schema (especially the PK-FK dependencies) to explore this. "

    if strategy >= 2:
        prompt_text += f"Also, use the metadata and statistics of each column that I have already sent you. "
        prompt_text += f"In addition, use the distinct values of each column that I have already sent you. "
    if strategy >= 3:
        prompt_text += f"Moreover, use the sample rows of tables that I have already sent you to understand the correlation between columns. "

    prompt_text += f"If you found a potential computation formula, please provide it. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all. "

    payload = {
        "candidate_formulas": [
            {"textual_formula": f" write here the most potential formula to compute `{target_column_name}` "},
            {"textual_formula": f" write here the other candidate formula to compute `{target_column_name}`, if any "}
        ]
    }

    prompt_text += "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "If you do not find any formula, just write 'None' in the JSON. "

    payload_None = {"candidate_formulas": "None"}
    prompt_text += "JSON format example when no potential formula is found:" + json.dumps(payload_None, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_semantic_plausibility_check(
    textual_formula: str,
    computation_sql_query: str,
    target_column_name: str,
    target_table_name: str,
) -> str:
    prompt_text = (
        f"We have a candidate formula to compute `{target_column_name}` in `{target_table_name}`. "
        f"Formula: {textual_formula}. "
        f"SQL: {computation_sql_query}. "
        f"Is this formula semantically plausible for `{target_column_name}`? "
        "Consider: domain appropriateness, correct data type/scale, and meaningful derivation. "
        "Accept if any reasonable derivation path exists. "
        "Reject only if clearly domain-nonsensical, type-incompatible, or structurally wrong. "
    )
    payload = {"is_plausible": True, "reason": "<brief reason>"}
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON."
    return prompt_text


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
    """Generate prompt to find candidate formulas and convert to SQL.

    Args:
        target_table_description: Table description
        target_column_name: Target column name
        target_table_name: Target table name
        number_of_pks_in_target_table: Count of primary key columns
        names_of_pk_columns_of_target_table: List of PK column names

    Returns:
        Comprehensive prompt for formula discovery and SQL generation
    """
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "

    prompt_text += f"In `{target_table_name}` table, `{target_column_name}` column has some missing values. "
    prompt_text += f"How the `{target_column_name}` column in the `{target_table_name}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_column_name}` from other columns and rows whether in the same table or in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "

    prompt_text += f"I am a program, so I just need you to write me the formula that will give us the missing values of the `{target_column_name}` column in the `{target_table_name}` table using stored values in the database. "

    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. "
    prompt_text += f"I expect having multiple candidate formulas. Try to bring at max {config.max_candidate_formulas_single_table} realistic formulas. "
    prompt_text += f"Also, do not limit the search single-hop join tables. Maybe the formula requires accessing tables that require 2-hop or 3-hop joins (or even more). "
    prompt_text += "In addition, provide the names of the tables and columns that are used in the formula. "
    prompt_text += "For example, assume a table T contains column C (among other columns in T) and we want to find a formula to compute C from other tables and table T1 (a parent of table T) contains columns A and B (among other columns in T1) "
    prompt_text += "and another table T2 (a child of table T) contains columns X, Y and Z (among other columns in T2). "
    prompt_text += "Assume the textual formula to compute column C in table T is: IF T1.A is True then T.C = SUM(T2.X) ELSE (i.e. T1.A is False) then T.C = SUM(T2.X - T2.Y). "
    prompt_text += "In this example the used tables for the above formula are T1 and T2 and the used columns are T1.A, T2.X and T2.Y. "

    prompt_text += f"Moreover, as NL-to-SQL task, I want you to reflect the textual formula on an SQL query that computes {target_column_name} column in the {target_table_name}. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks_in_target_table == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {target_column_name} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks_in_target_table+2} columns which are the primary keys of `{target_table_name}` table {names_of_pk_columns_of_target_table}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {target_column_name} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{target_column_name}` based on the textual formula. "

    prompt_text += f"Also, please alias the {target_table_name} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "

    prompt_text += "Rule 1: Do not use aggregation functions that include values retrieved from left joins. Rather, the left join clause shall include the aggregation functions inside it. "
    prompt_text += "Example of wrong SQL: SELECT id, SUM(i.amount) - SUM(o.amount) as balance from account a left join (select account_id, amount from income) as i on a.id = i.account_id left join (select account_id, amount from outcome) as o on a.id = o.account_id; "
    prompt_text += "Example of correct SQL: SELECT id, total_income.value - total_outcome.value as balance from account a left join (select account_id, sum(amount) as value from income group by account_id) as total_income on a.id = total_income.account_id left join (select account_id, sum(amount) as value from outcome group by account_id) as total_outcome on a.id = total_outcome.account_id; "
    prompt_text += "Avoid nesting aggregate functions; compute them in subqueries before comparison. "
    prompt_text += "Avoid creating temporary tables. "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += "Rule 5: In case of string comparisions, do not use 'FIND_IN_SET' and 'REPLACE' functions. Rather use the 'LIKE' function. "
    prompt_text += f"Rule 6: Do NOT read `{target_column_name}` from `{target_table_name}` anywhere in the SQL — not via the `target_table` alias, not via any other alias of `{target_table_name}`, not inside subqueries or CTEs. The formula must derive the value from other columns only. Reading the target column to predict itself is circular and invalid. "
    prompt_text += "Rule 7: Write efficient SQL — use JOINs with GROUP BY instead of correlated subqueries; avoid SELECT COUNT(*) or ORDER BY+LIMIT inside a correlated subquery on large tables. "

    prompt_text += "Provide me the computation query that shall be executed in MySQL. "

    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += "Finally, the computation sql queries shall not be semantically equivalent. For example, if you find 3 formulas that are reflected in 3 computation queries that are semantically equivalent, keep one formula and remove the other two formulas."
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explanations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors."

    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

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

    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "In the above example, the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
    prompt_text += "If you do not find any formula, the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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
    """Generate prompt to diagnose why computed values don't match actual values.

    Args:
        computation_sql_query: The computation query being tested
        diagnoses_sql_query: Query that extracts mismatches
        diagnoses_sql_query_result_str: Results showing mismatches
        target_column_name: Target column name
        target_table_name: Target table name

    Returns:
        Prompt asking for formula refinement based on mismatches
    """
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " "
    prompt_text += f"I used the computation query that you have provided to calculate the values of {target_column_name} column in {target_table_name} table and compare it with some non-null values. It seems that not all values match. "
    prompt_text += "Probably, it is a formatting or scaling issue or probably the formula needs modifications. "

    prompt_text += "Here is the computation query that you have provided me: " + computation_sql_query + ". "
    prompt_text += "Here is the diagnoses query that I prepared from the computation query that you have provided me: " + diagnoses_sql_query + ". "
    prompt_text += "Here is the result of the diagnoses query: " + diagnoses_sql_query_result_str + ". "
    prompt_text += "If you realize the reason of the mismatch, provide me an updated computation query. "
    prompt_text += "As mentioned earlier, I am a program, so I just need you to write me in your answer the computation query that I can run to verify the formula - only the SQL computation query such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the validation query free-of-errors."

    payload = {"computation_sql_query_after_diagnoses": "WRITE THE MODIFIED COMPUTATION QUERY HERE"}
    prompt_text += _get_json_prompt(payload)

    return prompt_text


def prompt_fix_sql_query_error(query: str, error: str) -> str:
    """Generate prompt to fix SQL query errors.

    Args:
        query: The failed SQL query
        error: The error message from the database

    Returns:
        Prompt asking to fix the query and return corrected SQL in JSON
    """
    prompt_text = f"I ran the query in MySQL database and it returns an error. Modify the SQL query and resolve the error and send it back to me."
    prompt_text += f"As a reminder, here is the query: [[[START OF QUERY]]] {query} [[[END OF QUERY]]]. "
    prompt_text += f"It is very important to make the query compatible with the schema. "

    prompt_text += "As I mentioned previously, I am a program, so I just need you to write me in your answer the SQL query as you did before. Only the SQL query such that I execute it immediately without parsing and modification. "
    prompt_text += f"Here is the error message from MySQL engine: {error}."

    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"computation_sql_query": f" the computation SQL query to compute {config.target_column_name} that you shall provide to get error-free SQL query"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_fix_timeout_with_subset(query: str, error: str, target_table: str, target_column: str) -> str:
    prompt_text = (
        f"The following SQL query timed out because it runs on the full table which has too many rows. "
        f"This is a performance issue, not a syntax error.\n\n"
        f"Query: [[[START OF QUERY]]] {query} [[[END OF QUERY]]]\n\n"
        f"Error: {error}\n\n"
        f"Rewrite the query to validate on a subset of at most 1000 rows from `{target_table}`. "
        f"Build the subset as: SELECT * FROM `{target_table}` WHERE `{target_column}` IS NOT NULL LIMIT 1000. "
        f"The subset must have diverse values in `{target_column}` (not all the same). "
        f"Apply the original formula logic on top of this subset — do not change what is being computed. "
        f"Preserve the actual_value / computed_value column aliases required by the validation framework. "
        f"The rewritten query must complete within 10 minutes on a large MySQL database."
    )
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    payload = {"computation_sql_query": f"the rewritten SQL query that validates on a 1000-row subset of {target_table}"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_optimize_sql_query(computation_sql_query: str, explain_results: str) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str
    prompt_text += (
        f"The following MySQL query is too expensive to execute — EXPLAIN shows a full table scan "
        f"or large cross-product. Rewrite it to be efficient (use indexed JOINs with GROUP BY, "
        f"avoid correlated subqueries). If it cannot be made efficient, set computation_sql_query to null.\n\n"
        f"Query: [[[START]]] {computation_sql_query} [[[END]]]\n\n"
        f"EXPLAIN output:\n{explain_results}\n\n"
        f"Rule: Use JOINs with GROUP BY instead of correlated subqueries. "
        f"Avoid SELECT COUNT(*) or ORDER BY+LIMIT inside correlated subqueries on large tables. "
        f"Preserve the original formula intent.\n\n"
    )
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    payload = {"computation_sql_query": f"efficient SQL to compute {config.target_column_name}, or null"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON."
    return prompt_text


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
    """Generate prompt to evaluate and suggest table names.

    Args:
        table_name: Current table name
        column_names_str: Comma-separated column names
        table_headers: Column headers/metadata
        table_sample_rows: Sample row data
        include_data: Whether to include sample data in prompt

    Returns:
        Prompt asking to evaluate table name representativeness
    """
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = f"Based on the schema and the metadata I have provided you, check if the name of `{table_name}` table is representative. "
    prompt_text += "Representative table name means without abbreviations, typos or ambiguities. "
    prompt_text += "Here is an example of ambiguity, a table named `HR` may refer to HumanResources or HeartRate. "
    prompt_text += "To solve this you may need to apply the following rules. "
    prompt_text += f"Rule 1: Look on the columns names of the table `{table_name}`. For example, if the columns refer to medical domain (e.g. a column named patient_id) then it is HeartRate. "
    prompt_text += f"As a reminder, here are the columns names of table `{table_name}`: {column_names_str}. "

    if include_data:
        prompt_text += f"Rule 2: Pay more attention to the rows of the `{table_name}` table that I have shared with you. "
        prompt_text += f"As a reminder, here are the rows of table `{table_name}`: {table_headers} {table_sample_rows}. "
        prompt_text += f"Rule 3: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "
    else:
        prompt_text += f"Rule 2: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "

    prompt_text += "For example, If a table named `ords` and has a relationship with a table named `order_items`, then you can infer that `ords` can be replaced with `orders`. "
    prompt_text += "End of rules. "
    prompt_text += "Also, make the table name singular if it is plural. For example, instead of `Employees`, table name should be `Employee`. "
    prompt_text += "I am a program, so just return me only the new table name (without additions like ` ' () , etc as I will take the response as is to rename the column) if you find a better name for the table or return representative_name otherwise. "

    return initial_prompt_str + " " + prompt_text


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
    """Generate prompt to evaluate and suggest column names.

    Args:
        column_name: Current column name
        table_name: Name of the table
        column_names_str: Other column names in table
        distinct_values_str: Distinct values in the column
        table_headers: Column headers
        table_sample_rows: Sample data rows
        include_data: Whether to include sample data
        include_distinct_values: Whether to include distinct values

    Returns:
        Prompt asking to evaluate column name representativeness
    """
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = f"Based on the schema and the metadata I have provided you, check whether the column name of `{column_name}` column in `{table_name}` table is representative. "
    prompt_text += "Representative column name means without abbreviations, typos or ambiguities. "
    prompt_text += "Here is an example of ambiguity, a column named `BP` may refer to blood_pressure or boiling_point. "
    prompt_text += "To solve this you may need to apply the following rules. "
    prompt_text += f"Rule 1: Look on the columns names of the same table i.e. `{table_name}` table. For example, if the columns refer to medical domain (e.g. a column named patient_id) then it is blood_pressure. "
    prompt_text += f"As a reminder, here are the columns names of table `{table_name}`: {column_names_str}. "

    rule_index = 2
    if include_data:
        prompt_text += f"Rule {rule_index}: Pay more attention to the rows of the `{table_name}` table that I have shared with you. "
        prompt_text += f"As a reminder, here are the rows of table `{table_name}`: {table_headers} {table_sample_rows}. "
        rule_index += 1

    prompt_text += f"Rule {rule_index}: Look on the schema and the names of other tables, the names of their columns and their data that I have shared with you, especially those that have a PK-FK relationships with `{table_name}` table. "
    prompt_text += f"For example, If a column named `ord_no` and `{table_name}` has a relationship with a table named `order`, then you can infer that `ord_no` can be replaced with `order_number`. "

    if include_distinct_values:
        prompt_text += f"As a reminder here are some distinct values of the column: {distinct_values_str}. "
        prompt_text += f"Add the following rule. Look at the data stored in the column `{column_name}` and make the column name representative of its data content. "
        prompt_text += "For example, if a column named `cars` and the data stored in it is integers like 1, 4 and 5, then it can be replaced with `number_of_cars` depending on the other factors like the schema, names of other tables and their columns, "
        prompt_text += "names of other columns in the same table, the name of the table that stores the column, the rows of the table, the distinct values of the column, etc. "
        prompt_text += "Also, some database designers might give a name to the column that is not fully representative. "
        prompt_text += "For example, a column named `return_ratio` shall be replaced with `return_percentage` if the column contains values between 0 and 100."
        prompt_text += "In the opposite case, a column named `return_percentage` shall be replaced with `return_ratio` if the column contains values between 0 and 1. "

    prompt_text += "I am a program, so just return me now only the new column name (without additions like ` ' () , etc as I will take the response as is to rename the column) if you find a better representative name for the column or return just representative_name otherwise. "

    return initial_prompt_str + " " + prompt_text


# ============================================================================
# SEMANTIC CLASSIFICATION PROMPTS
# ============================================================================

def prompt_detect_topic(items: list) -> str:
    """Generate prompt to detect the topic/category of a list of items.

    Args:
        items: List of items to classify

    Returns:
        Prompt asking to identify the semantic category
    """
    items_str = ", ".join(items)
    prompt_text = f"I have the following list of items: {items_str}. "
    prompt_text += "What is the semantic category or topic that all these items belong to? "
    prompt_text += "Provide only one word or at most 3 words that describe the category. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"topic": "one to three words"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

# ============================================================================
# CHAINING TABLE PROMPTS
# ============================================================================

def prompt_identify_chaining_table_structure(
    target_table_description: str
) -> str:
    """Generate prompt to identify grouping and chaining columns in a chaining table.

    Args:
        target_table_description: Description of the target table

    Returns:
        Prompt asking to identify chaining table structure
    """
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
    prompt_text += f"`{config.target_table_name}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text +=  "For example, to know the previous and next rows of R5. "
    prompt_text +=  "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = previous_row.C and current_row.C = next_row.B. "
    prompt_text += f"I want you to provide me the grouping columns and chaining columns in the `{config.target_column_name}` chaining table. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

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

    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "In [Example 1], the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
    prompt_text += "In [Example 2], the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
    prompt_text += "Note that, some chaining tables have one group. So there is no grouping columns. In this case keep grouping_columns blank in the JSON. However, it is not accepted to have a chaining table without chaining columns. "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_chaining_table_candidate_formula(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    grouping_columns: str,
    chaining_columns: str
) -> str:
    """Generate prompt to find candidate formulas in a chaining table based on data samples.

    Args:
        target_table_description: Description of the target table
        data_for_sharing_with_LLM_str: Sample data rows
        grouping_columns: Grouping column names
        chaining_columns: Chaining column names

    Returns:
        Prompt asking for candidate formulas with data samples
    """
    from src.core.config import config

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
    prompt_text += f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
    prompt_text += f"`{config.target_table_name}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text +=  "For example, to know the previous and next rows of R5. "
    prompt_text +=  "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = previous_row.C and current_row.C = next_row.B. "
    prompt_text += f"Take the following data samples of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Based on the schema and these data samples, provide the formula to compute `{config.target_column_name}` from other columns and rows in `{config.target_table_name}`. "
    prompt_text += "Be concise and provide only one formula. The formula shall be completely compatible with the data samples. Use for the formula useful terms such as 'current_row', 'previous_row' and 'next_row'. "
    prompt_text += f"Also, to make the formula clear, use for the formula the grouping columns ({grouping_columns}) and the chaining columns ({chaining_columns}). "
    prompt_text += f"In addition, return the columns names that are needed for the formula to compute `{config.target_column_name}`. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. But, do not overdo it, if you find one just return it. "

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

    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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
    """Generate prompt to create SQL query for computing values in a chaining table.

    Args:
        target_table_description: Description of the target table
        data_for_sharing_with_LLM_str: Sample data rows
        formula_based_on_data_sharing: The textual formula to convert to SQL
        grouping_columns: Grouping column names
        chaining_columns: Chaining column names
        chaining_columns_str: Chaining columns as string
        number_of_pks_in_target_table: Number of primary keys
        names_of_pk_columns_of_target_table: List of PK column names

    Returns:
        Comprehensive prompt for SQL generation with detailed rules
    """
    from src.core.config import config

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
    prompt_text += f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
    prompt_text += f"`{config.target_table_name}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text +=  "For example, to know the previous and next rows of R5. "
    prompt_text +=  "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
    prompt_text += f"Take the following sample rows of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Here is the textual formula to compute `{config.target_column_name}` from other rows: [[[FORMULA START]]] {formula_based_on_data_sharing} [[[FORMULA END]]]. "

    prompt_text += f" As an NL-to-SQL task, I want you to reflect the textual formula on an SQL query that computes {config.target_column_name} column in the {config.target_table_name} chaining table using previous or next rows. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks_in_target_table == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {config.target_column_name} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks_in_target_table+2} columns which are the primary keys of `{config.target_table_name}` table {names_of_pk_columns_of_target_table}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {config.target_column_name} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{config.target_column_name}` based on the textual formula. "
    prompt_text += f"Avoid using `{config.target_column_name}` to calculate the computed_value of the same row. This is very important. Otherwise, we will have overfitting problem. "
    prompt_text += f"In addition, Please alias the {config.target_table_name} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "

    prompt_text += f"Rule 1: As `{config.target_table_name}` is a chaining table, to calculate the value of '{config.target_column_name}' of a certain row, "
    prompt_text += f"the computed_value shall be a nested query that computes the value from next/previous row(s) table `{config.target_table_name}` in the computation query and return only one value. "
    prompt_text += "With this, self-join is not required. So, do not use self-join. "
    prompt_text += f"The nested query shall be in the outer select and returns ONLY one value as a computed value (aliased computed_value). "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. "
    prompt_text += "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += f"Rule 5: As `{config.target_table_name}` is a chaining table, some values cannot be computed. "
    prompt_text += f"Rule 6: Do not use `{config.target_column_name}` in the computed_value of the same row. "
    prompt_text += f"For example, avoid the following case: {config.target_column_name} = column_x + ({config.target_column_name} - column_x). "
    prompt_text += f"Also, do not use target_table.`{config.target_column_name}` in the computed_value at all. "

    prompt_text += f"For example [Case 1], if `{config.target_column_name}` of a row is calculated based on its previous row, then the value of `{config.target_column_name}` in the first row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the first rows of chains i.e. any row that do not have a previous row. "
    prompt_text += f"Another example [Case 2], if `{config.target_column_name}` of a row is calculated based on its next row, then the value of `{config.target_column_name}` in the last row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the last rows of chains i.e. any row that do not have a next row. "

    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "Keep in mind that, MySQL doesn't allow nested aggregate functions directly. "

    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample rows, especially when you determine the chaining criteria in the table (i.e. to know next and previous rows). See in the data, the values of {chaining_columns_str} across rows. "
    prompt_text += f"Pay attention to all rules, especially rule 5 to exclude rows that their `{config.target_column_name}` value cannot be computed. "
    prompt_text += f"Also, remember that the nested query of the computed_value shall return only one value. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explanations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors. The query shall be 100 percent compatible with the data samples that I sent you. "

    return prompt_text


def prompt_classify_chain_direction() -> str:
    """Generate simple prompt to determine if chaining uses previous or next rows.

    Returns:
        Prompt asking whether previous or next rows are used
    """
    from src.core.config import config

    prompt_text = f"Is `{config.target_column_name}` using previous rows or next rows. "
    prompt_text += "I am a program, so I just respond with one word - whether 'previous' or 'next'. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"direction": "previous or next"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


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
    """Generate prompt to diagnose and fix incorrect chaining formulas.

    Args:
        target_table_description: Description of the target table
        current: Current/previous/next indicator
        grouping_columns: List of grouping columns
        chaining_columns: List of chaining columns
        data_for_sharing_with_LLM_str: Sample data rows
        formula_based_on_data_sharing: The incorrect formula
        accuracy: Accuracy percentage
        diagnoses_sql_query_result_str: Query results showing mismatches

    Returns:
        Prompt asking to diagnose and fix the formula
    """
    from src.core.config import config

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access {current} rows of the same table with a specific criterion. "
    prompt_text += f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
    prompt_text += f"`{config.target_table_name}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text +=  "For example, to know the previous and next rows of R5. "
    prompt_text +=  "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. "
    prompt_text += "[Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chaining columns. "

    if len(grouping_columns) > 1:
        prompt_text += f"The grouping columns in the `{config.target_table_name}` table are {grouping_columns}. "
    else:
        prompt_text += f"The grouping column in the `{config.target_table_name}` table is {grouping_columns[0]}. "

    if len(chaining_columns) > 1:
        prompt_text += f"And the chaining columns in the `{config.target_table_name}` table are {chaining_columns}. "
    else:
        prompt_text += f"And the chaining column in the `{config.target_table_name}` table is {chaining_columns[0]}. "

    prompt_text += f"Take the following sample rows of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"I tried to calculate the missing values of `{config.target_column_name}` using the following formula but the results show that the formula is incorrect (accuracy: {accuracy}%). "
    prompt_text += f"Here is the incorrect formula: [[[START OF INCORRECT FORMULA]]] {formula_based_on_data_sharing} [[[END OF INCORRECT FORMULA]]]. "
    prompt_text += f"Also, here is some random computation query results: {diagnoses_sql_query_result_str}. "
    prompt_text += f"These computation query results are randomly sampled (i.e. they do not form chains) and are useful for comparing the predicted value with the actual value to identify the error in the formula. "
    prompt_text += "The goal is to make the computation_value equals the actual_value. The actual_value is correct but the computation_value is not. "
    prompt_text += "Find the error in the formula that results in the mismatches. Probably the formula requires minor modifications. "
    prompt_text += "To do so, focus on the sample rows and computation query results. "
    prompt_text += f"Also, return the columns names that are needed for the formula to compute `{config.target_column_name}`. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {
        "is_catched": " 'yes' if you find out the cause of the error and 'no' otherwise ",
        "cause_of_error": " explain the root cause of the error briefly ",
        "corrected_formula": " write the new correct formula here ",
        "columns": ["X", "Y"]
    }

    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
    prompt_text += f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[END OF DESCRIPTION]]]. "
    prompt_text += f"`{config.target_table_name}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chaining table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) of rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text +=  "For example, to know the previous and next rows of R5. "
    prompt_text +=  "Firstly we use the grouping columns to know the other rows that belong to the same group (i.e. R4 and R6) and from the chaining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chaining column. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
    prompt_text += f"Take the following sample rows of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Here is the textual formula to compute `{config.target_column_name}` from other rows: [[[CORRECT FORMULA START]]] {corrected_formula} [[[CORRECT FORMULA END]]]. "
    prompt_text += f"Previously, I tried with the following formula but it was incorrect: [[[INCORRECT FORMULA START]]] {formula_based_on_data_sharing} [[[INCORRECT FORMULA END]]]. "
    prompt_text += f"The reason of the incorrectness was as follows: [[[REASON OF INCORRECTNESS START]]] {cause_of_error} [[[REASON OF INCORRECTNESS END]]]. "
    prompt_text += f"Therefore, avoid making the same mistake of the incorrect formula. "

    prompt_text += f" As an NL-to-SQL task, I want you to reflect the textual formula on an SQL query that computes {config.target_column_name} column in the {config.target_table_name} chaining table using previous or next rows. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks_in_target_table == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {config.target_column_name} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks_in_target_table+2} columns which are the primary keys of `{config.target_table_name}` table {names_of_pk_columns_of_target_table}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {config.target_column_name} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{config.target_column_name}` based on the textual formula. "
    prompt_text += f"Avoid using `{config.target_column_name}` to calculate the computed_value of the same row. This is very important. Otherwise, we will have overfitting problem. "
    prompt_text += f"In addition, Please alias the {config.target_table_name} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "

    prompt_text += f"Rule 1: As `{config.target_table_name}` is a chaining table, to calculate the value of '{config.target_column_name}' of a certain row, "
    prompt_text += f"the computed_value shall be a nested query that computes the value from next/previous row(s) table `{config.target_table_name}` in the computation query and return only one value. "
    prompt_text += "With this, self-join is not required. So, do not use self-join. "
    prompt_text += f"The nested query shall be in the outer select and returns ONLY one value as a computed value (aliased computed_value). "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. "
    prompt_text += "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += f"Rule 5: As `{config.target_table_name}` is a chaining table, some values cannot be computed. "
    prompt_text += f"For example [Case 1], if `{config.target_column_name}` of a row is calculated based on its previous row, then the value of `{config.target_column_name}` in the first row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the first rows of chains i.e. any row that do not have a previous row. "
    prompt_text += f"Another example [Case 2], if `{config.target_column_name}` of a row is calculated based on its next row, then the value of `{config.target_column_name}` in the last row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the last rows of chains i.e. any row that do not have a next row. "
    prompt_text += f"Rule 6: Do not use `{config.target_column_name}` in the computed_value of the same row. "
    prompt_text += f"For example, avoid the following case: {config.target_column_name} = column_x + ({config.target_column_name} - column_x). "
    prompt_text += f"Also, do not use target_table.`{config.target_column_name}` in the computed_value at all. "

    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "Keep in mind that, MySQL doesn't allow nested aggregate functions directly. "

    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample rows, especially when you determine the chaining criteria in the table (i.e. to know next and previous rows). See in the data, the values of {chaining_columns_str} across rows. "
    prompt_text += f"Pay attention to all rules, especially rule 5 to exclude rows that their `{config.target_column_name}` value cannot be computed. "
    prompt_text += f"Also, remember that the nested query of the computed_value shall return only one value. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explanations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors. The query shall be 100 percent compatible with the data samples that I sent you. "

    return prompt_text


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
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific criterion. "
    prompt_text += f"`{config.target_table_name}` is a hierarchical table. "
    prompt_text += f"The hierarchical table is a table that has a tree-like structure such that each row has at most one parent row (except the root row) and children rows (except the leaf rows). "
    prompt_text += f"Each row in the hierarchical table refers to its parent row, if any, i.e. stores the identifier of its parent row in one of its columns. "

    if len(names_of_pk_columns_of_target_table) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is {names_of_pk_columns_of_target_table[0]}. "
        else:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is the following composite key: {names_of_pk_columns_of_target_table}. "

    prompt_text += f"[Example 1] Assume a hierarchical table T has more than 3 columns (A, B, C ...). "
    prompt_text += "Column A is the identifier and Column C is the column that refers to the identifier of the parent row. "
    prompt_text += "Assume the hierarchical table T stores rows where R1 is parent of R2 and R3, and R3 is parent of R4. "
    prompt_text += f"[Example 2] Assume a hierarchical table T has composite key (A, B) and columns C, D referring to parent (A, B). "

    if len(names_of_pk_columns_of_target_table) == 0:
        prompt_text += f"As `{config.target_table_name}` is a hierarchical table, "
        prompt_text += "I want you to provide me the name of the parent-reference-column and the parent-referencing-column. "
    else:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table with identifier `{names_of_pk_columns_of_target_table[0]}`, I want you to provide the parent-referencing-column. "
        else:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table with composite key, provide the parent-referencing-column for each identifier. "

    prompt_text += "Return in JSON format with parent_reference_columns array. "
    prompt_text += "Provide the JSON. "

    return prompt_text


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

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"`{config.target_table_name}` is a hierarchical table. "

    if len(names_of_pk_columns_of_target_table) == 1:
        prompt_text += f"As `{config.target_table_name}` has one identifier, the parent-reference-column is `{parent_reference_columns_list[0][0]}` and its parent-referencing-column is {parent_reference_columns_list[0][1]}. "
    else:
        prompt_text += f"As `{config.target_table_name}` has composite key identifier, here are the parent-reference relationships: "
        for parent_reference_columns in parent_reference_columns_list:
            prompt_text += f"Parent-reference-column is `{parent_reference_columns[0]}`, parent-referencing-column is {parent_reference_columns[1]}. "

    prompt_text += f"Take the following data samples of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Based on the schema and these data samples, provide the formula to compute `{config.target_column_name}` from other columns and rows. "
    prompt_text += "Be concise and provide only one formula. Use terms such as 'parent_row', 'children_rows' and 'child_row'. "
    prompt_text += "Return in JSON format with candidate_formulas array. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide confidence scores summing to 100. "

    return prompt_text


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

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value in a hierarchical table. "

    if len(names_of_pk_columns_of_target_table) == 1:
        prompt_text += f"The parent-reference-column is `{parent_reference_columns_list[0][0]}` and its parent-referencing-column is {parent_reference_columns_list[0][1]}. "
    else:
        prompt_text += f"Parent-reference relationships: "
        for parent_reference_columns in parent_reference_columns_list:
            prompt_text += f"`{parent_reference_columns[0]}` - {parent_reference_columns[1]}; "

    prompt_text += f"Take the following sample rows: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Here is the textual formula: [[[FORMULA START]]] {formula_based_on_data_sharing} [[[FORMULA END]]]. "
    prompt_text += f"Convert this to an SQL query that computes {config.target_column_name} using hierarchical joins or recursive CTEs. "

    if number_of_pks_in_target_table > 0:
        prompt_text += f"Return {number_of_pks_in_target_table} PK columns, computed_value, and actual_value. "
    else:
        prompt_text += "Return computed_value and actual_value. "

    prompt_text += "Use self-joins or recursive CTEs to access parent/child rows. "
    prompt_text += "Provide only the executable SQL query without explanations. "

    return prompt_text


# ============================================================================
# ROW-SCOPE PROMPTS
# ============================================================================

def prompt_find_row_scope_formulas(
    target_table_description: str
) -> str:
    """Generate prompt to find formulas for row-scope computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
    prompt_text += f"The `{config.target_column_name}` column is a computed value where the computation depends only on other columns in the same row (row-scope). "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{config.target_column_name}` from other columns in the same row. "
    prompt_text += "Use the schema and the data metadata to explore potential formulas. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all with confidence scores that sum to 100. "
    prompt_text += "Return result in JSON format with candidate_formulas array. "

    return prompt_text


def prompt_generate_sql_for_row_scope(
    target_table_description: str,
    formula: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Generate prompt to create SQL query for row-scope computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` column is a row-scope computed value. "
    prompt_text += f"Here is the textual formula: {formula}. "
    prompt_text += f"Convert this to an SQL query that computes {config.target_column_name} for all rows using simple column arithmetic. "

    if number_of_pks_in_target_table > 0:
        prompt_text += f"Return: {names_of_pk_columns_of_target_table}, computed_value, and actual_value. "
    else:
        prompt_text += f"Return: computed_value and actual_value. "

    prompt_text += "Rules: No aggregation functions across rows. No joins. Simple column arithmetic only. "
    prompt_text += "Provide only the executable SQL query without explanations. "

    return prompt_text


# ============================================================================
# CROSS-TABLE PROMPTS
# ============================================================================

def prompt_is_count_or_exist(
    target_table_description: str
) -> str:
    """Generate prompt to determine if computed value is based on counting or existence in other tables."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
    prompt_text += f"However, before finding the full formula, tell me whether `{config.target_column_name}` of a certain row is derived from counting other rows or checking existence. "
    prompt_text += f"For example, if 'number_of_passengers' in 'trip' table can be derived from COUNT of rows in 'tickets' table for that trip. "
    prompt_text += f"Or if 'is_canceled' can be TRUE if a row exists in 'canceled_trips' table for that trip. "
    prompt_text += f"I am a program, respond with 'yes' if derived from counting/existence, 'no' otherwise. "

    return prompt_text


def prompt_find_count_exists_formulas(
    target_table_description: str
) -> str:
    """Generate prompt to find COUNT or EXISTS based formulas across tables."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` column has some missing values. "
    prompt_text += f"The `{config.target_column_name}` column can be computed by COUNTing or checking EXISTence of rows in other tables. "
    prompt_text += "Find candidate formulas using COUNT(*), SUM(CASE WHEN EXISTS ...), or IF EXISTS patterns. "
    prompt_text += "Use PK-FK relationships to determine join conditions. "
    prompt_text += f"Provide up to {config.max_candidate_formulas_count_exists} candidate formulas with confidence scores summing to 100. "
    prompt_text += "Include: textual_formula, used_tables, used_columns, confidence_score, and computation_sql_query. "
    prompt_text += "Return strictly in JSON format. "

    return prompt_text


def prompt_identify_candidate_tables_for_count(
    target_table_description: str
) -> str:
    """Generate prompt to identify which tables to count/check for existence."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` can be computed from other tables. "
    prompt_text += "Identify which tables could be used for COUNTing rows or checking row EXISTence. "
    prompt_text += "Consider: PK-FK relationships, table names, column meanings, and the nature of `{config.target_column_name}`. "
    prompt_text += f"For example, if `{config.target_column_name}` is 'number_of_orders', look for an 'orders' or 'order_items' table. "
    prompt_text += "Provide the candidate table names with explanations. "
    prompt_text += "Return in JSON format with candidate_tables array containing table names and reasons. "

    return prompt_text


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
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` is computed from other tables. "
    prompt_text += f"Textual formula: {formula}. "
    prompt_text += "Convert to SQL using JOINs with proper aggregations and grouping. "

    if number_of_pks_in_target_table > 0:
        prompt_text += f"Return {number_of_pks_in_target_table} PK columns, computed_value, and actual_value. "
    else:
        prompt_text += "Return computed_value and actual_value. "

    prompt_text += "Rules for joins: Use proper join conditions based on PK-FK relationships. "
    prompt_text += "For aggregations: Use subqueries to avoid nested aggregates. "
    prompt_text += "Ensure accuracy by preserving all rows in the outer table. "
    prompt_text += "Provide only the executable SQL query. "

    return prompt_text


def prompt_find_common_formula_pattern(
    target_table_description: str,
    formula_list: list
) -> str:
    """Generate prompt to find the most common semantic formula pattern."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"`{config.target_column_name}` in `{config.target_table_name}` is a computed value. "
    prompt_text += "I have multiple candidate formulas but many may be semantically equivalent. "
    prompt_text += f"Here are the formulas: {formula_list}. "
    prompt_text += "Identify and return the most common semantic formula pattern. "
    prompt_text += "Group semantically similar formulas and return the most frequent one. "
    prompt_text += "I am a program, respond only with the most common semantic formula. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"formula_pattern": "the common formula pattern"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_extract_semantic_formula(
    target_table_description: str,
    formula_list: str
) -> str:
    """Generate prompt to extract the semantic meaning of formulas."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += f"I have a list of potential formulas: {formula_list}. "
    prompt_text += f"Some formulas are semantically the same. Provide the most frequent semantic formula. "
    prompt_text += f"I am a program, respond only with the formula without any additions. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"semantic_formula": "the most frequent semantic formula"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_classify_table_scope_type(
    target_table_description: str
) -> str:
    """Generate prompt to classify if computation is row-scope, single-table, or cross-table."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"`{config.target_column_name}` in `{config.target_table_name}` has missing values. "
    prompt_text += "Is the computation: "
    prompt_text += "1. ONLY using columns in the same row (row-scope)? "
    prompt_text += "2. Using other rows in the same table (single-table-scope)? "
    prompt_text += "3. Using rows in other tables (cross-table-scope)? "
    prompt_text += "Respond with ONLY one word: 'row-scope', 'single-table-scope', or 'cross-table-scope'. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"scope_type": "row-scope or single-table-scope or cross-table-scope"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


# ============================================================================
# SINGLE TABLE SCOPE PROMPTS
# ============================================================================

def prompt_is_single_table_computed_value(
    target_table_description: str
) -> str:
    """Generate prompt to determine if a column is computed from other rows in same table."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` column has missing values. "
    prompt_text += f"Can `{config.target_column_name}` be computed or derived from other columns or rows in the same table (NOT from other tables)? "
    prompt_text += "Examples: cumulative sums, running totals, parent values in hierarchies, previous/next row values. "
    prompt_text += "Respond with ONLY 'yes' or 'no'. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"is_computed": "yes or no"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_generate_single_table_formula(
    target_table_description: str
) -> str:
    """Generate prompt to find formula for single-table computed values."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"In `{config.target_table_name}` table, `{config.target_column_name}` is computed from other rows in the same table. "
    prompt_text += f"Find the formula to compute `{config.target_column_name}`. "
    prompt_text += "Consider the table structure: is it hierarchical, chained, or cumulative? "
    prompt_text += "Provide candidate formulas with descriptions of how other rows are accessed. "
    prompt_text += "Use terms like 'previous_row', 'next_row', 'parent_row', 'children_rows', or 'all_rows'. "
    prompt_text += "Return in JSON format with candidate_formulas array. "

    return prompt_text


def prompt_classify_as_table_scope(
    target_table_description: str
) -> str:
    """Generate prompt to classify single-table computation as chaining, hierarchical, or other."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"`{config.target_column_name}` in `{config.target_table_name}` is computed from rows in the same table. "
    prompt_text += "What is the relationship structure? "
    prompt_text += "1. CHAINING: each row has previous/next row (like transactions in sequence) "
    prompt_text += "2. HIERARCHICAL: tree structure with parent/child rows "
    prompt_text += "3. OTHER: cumulative, rolling window, or aggregation pattern "
    prompt_text += "Respond with ONLY one word: 'chaining', 'hierarchical', or 'other'. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"table_scope_type": "chaining or hierarchical or other"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def _get_json_prompt(payload: dict) -> str:
    """Helper to format JSON response instructions.

    Args:
        payload: Dictionary structure for expected JSON response

    Returns:
        Formatted instruction string for JSON responses
    """
    prompt_text = "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
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
    prompt_text = "The semantic meaning you have responded contains more than 3 words. The semantic meaning shall consist of ONLY 3 words at maximum "
    prompt_text += "I am a program, so I just need you to write me the semantic meaning of the list items without any explaination. Do not return anything else. Only respond with 4 words at maximum. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"topic": "one to three words"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_rename_table_retry() -> str:
    prompt_text = "You provided me multiple words while I asked you only to send me one word. Please send me only the new table name if you find a better name for the table or return just representative_name otherwise. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"table_name": "new name or representative_name"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_rename_column_retry() -> str:
    prompt_text = "You provided me multiple words while I asked you only to send me one word. Please send me only the new column name if you find a better representative name for the column or return just representative_name otherwise. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"column_name": "new name or representative_name"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


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
        #"columns": f" write here the column names that are needed for the formula to compute `{target_col}` ",
        "columns": ["X", "Y"]
    }

    prompt_text = f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{target_col}`, we need to access {current} rows of the same table with a specific creteria. "
    prompt_text += f"Here is a description of the `{target_tbl}` table: [[[START OF DESCRIPTION]]] {target_tbl_description} [[[START OF DESCRIPTION]]]. "
    prompt_text += f"`{target_tbl}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chainig table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) or rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text += "For example, to know the previous and rows of R5. "
    prompt_text += "Firstly we use the grouping columns to know the other rows that belong to the same groupe (i.e. R4 and R6) and from the chining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. "
    prompt_text += "[Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chiaining columns. "

    if len(grouping_columns) > 1:
        prompt_text += f"The grouping columns in the `{target_tbl}` table are {grouping_columns}. "
    else:
        prompt_text += f"The grouping column in the `{target_tbl}` table is {grouping_columns[0]}. "

    if len(chaining_columns) > 1:
        prompt_text += f"And the chaining columns in the `{target_tbl}` table are {chaining_columns}. "
    else:
        prompt_text += f"And the chaining column in the `{target_tbl}` table is {chaining_columns[0]}. "

    prompt_text += f"Take the following sample rows of `{target_tbl}` table: {data_sharing_str}. "
    prompt_text += f"I tried to calculate the missing values of `{target_col}` using the following formula but the results show that the formula is incorrect ({accuracy} percent of accuracy). "

    prompt_text += f"Here is the incorrect formula: [[[START OF INCORRECT FORMULA]]] {formula} [[[END OF INCORRECT FORMULA]]]. "
    prompt_text += f"Also, here is some random computation query results: {diagnoses_result_str}. "
    prompt_text += f"These random computation query results are randomly selected (i.e. are not forming chains) and are useful for you to compare the predicted value and the acutal value to catch the error in the formula. "
    prompt_text += "The goal is to make the computation_value equals the actual_value. The actual_value is correct but the computation_value is not. "
    prompt_text += "Find the error in the formula that resutls the mismatches. Probably the formula requires minor modifications. "
    prompt_text += "To do so, focus on the sample rows and computation query results. "
    prompt_text += f"Also, return the columns names that are needed for the formula to compute `{target_col}`. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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
    prompt_text = f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{target_col}`, we need to access other rows with a specific creteria. "
    prompt_text += f"Here is a description of the `{target_tbl}` table: [[[START OF DESCRIPTION]]] {target_tbl_description} [[[START OF DESCRIPTION]]]. "
    prompt_text += f"`{target_tbl}` is a chaining table. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"Each chainig table is split into groups and in each group there is a chain. Let me clarify with the following example. "
    prompt_text += f"[Example 1] Assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: R1 (0, 'f', 1, ...), R2 (0, 'f', 2, ...), R3 (0, 'f', 3, ...), R4 (5, 'x', 1, ...), R5 (5, 'x', 2, ...), R6 (5, 'x', 3, ...). "
    prompt_text += f"In this example, the table is split into two groups. In the first group all rows have A = 0 and B = 'f' and in the second group all rows have A = 5 and B = 'x'. Column A and column B are called 'grouping columns'. "
    prompt_text += f"In each group, column C determines the chain (i.e. order) or rows within the group. Column C is called 'chaining column'. "
    prompt_text += f"Grouping columns and chaining columns are important to know the previous row and the next row of a certain row. "
    prompt_text += "For example, to know the previous and rows of R5. "
    prompt_text += "Firstly we use the grouping columns to know the other rows that belong to the same groupe (i.e. R4 and R6) and from the chining column we know that R4 is a previous row to R5 and R6 is a next row to R5. "
    prompt_text += "Sometimes the chaining columns are more than one column. [Example 2] For example, assume a chaining table has more than 3 columns (A, B, C ...) and have the following 6 rows: "
    prompt_text += "R1(1, 1, 5, ....), R2(1, 6, 12, ....), R3(1, 13, 15, ....), R4(2, 0, 15, ....), R4(2, 16, 22, ....), R5(2, 23, 25, ....). "
    prompt_text += "In this example, A is the grouping column and B and C are the chiaining column. Hence, current_row.B = (previous_row.C - 1) and current_row.C = (next_row.B + 1). "
    prompt_text += f"Take the following sample rows of `{target_tbl}` table: {data_sharing_str}. "
    prompt_text += f"Here is the textual formula to compute `{target_col}` from other rows: [[[CORRECT FORMULA START]]] {corrected_formula} [[[CORRECT FORMULA END]]]. "
    prompt_text += f"Previously, I tried with the following formula but it was incorrect: [[[INCORRECT FORMULA START]]] {incorrect_formula} [[[INCORRECT FORMULA END]]]. "
    prompt_text += f"The reason of the incorrectness was as follows: [[[REASON OF INCORRECTNESS START]]] {cause_of_error} [[[REASON OF INCORRECTNESS END]]]. "
    prompt_text += f"Therefore, avoid making the same mistake of the incorrect formula. "

    prompt_text += f" As NL-to_SQL task, I want you to reflect the textual formula on an SQL query that computes {target_col} column in the {target_tbl} chaining table using previous or next rows. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {target_col} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks+2} columns which are the primary keys of `{target_tbl}` table {pk_columns_names}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {target_col} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{target_col}` based on the textual formula. "
    prompt_text += f"Avoid using `{target_col}` to calculate the computed_value of the same row. This is very important. Otherwise, we will have overfitting problem. "
    prompt_text += f"In addition, Please alias the {target_tbl} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "

    prompt_text += f"Rule 1: As `{target_tbl}` is a chaining table, to calculate the value of '{target_col}' of a certain row, "
    prompt_text += f"the computed_value shall be a nested query that computes the value from next/previos row(s) table `{target_tbl}` in the computation query and return only one value. "
    prompt_text += "With this, self-join is not required. So, do not use selft-join. "
    prompt_text += f"The nested query shall be in the outer select and returns ONLY one value as a computed value (aliased computed_value). "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. "
    prompt_text += "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += f"Rule 5: As `{target_tbl}` is a chaining table, some values cannot be computed. "
    prompt_text += f"For example [Case 1], if `{target_col}` of a row is calculated based on its previos row, then the value of `{target_col}` in the first row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the first rows of chains i.e. any row that do not have a previous row. "
    prompt_text += f"Another example [Case 2], if `{target_col}` of a row is calculated based on its next row, then the value of `{target_col}` in the last row of the chain can not be computed. "
    prompt_text += f"In this case, the computation query shall exclude (in the WHERE clause) the last rows of chains i.e. any row that do not have a next row. "
    prompt_text += f"Rule 6: Do not use `{target_col}` in the computed_value of the same row. "
    prompt_text += f"For example, avoid the following case: {target_col} = column_x + ({target_col} - column_x). "
    prompt_text += f"Also, do not use target_table.`{target_col}` in the computed_value at all. "

    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "Keep in mind that, MySQL doesn't allow nested aggregate functions directly. "

    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample rows, especially when you determine the chaining criteria in the table (i.e. to know next and previous rows). See in the data, the values of {chaining_columns_str} across rows. "
    prompt_text += f"Pay attention to all rules, especially rule 5 to exclude rows that their `{target_col}` value cannot be computed. "
    prompt_text += f"Also, remember that the nested query of the computed_value shall return only one value. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explainations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors. The query shall be 100 percent compatible with the data samples that I sent you. "

    return prompt_text


def prompt_is_count_or_exist_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Determine whether the target column is derived from counting/existence in other tables."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
    prompt_text += f"How the `{target_col}` column in the `{target_tbl}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_col}` from other columns and rows in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "
    prompt_text += f"However, before that I want you to tell me whether `{target_col}` of a certain row is derived from counting other rows or not. "
    prompt_text += f"For example, if the missing value is 'number_of_passengers' in a 'trip' table, then the 'number_of_passengers' of a trip '0001X' can be derived from the count of rows in the 'tickets' table of trip '0001X'. "
    prompt_text += f"Another example, if the missing value is a boolean 'is_canceled' in a 'trip' table, then the value of 'is_canceled' of a trip '0002X' is 'True' (or 1 or 'yes', etc) if there is a row in 'canceled_trips' table of trip '0002X' "
    prompt_text += "and the value of 'is_canceled' of a trip '0003X' is 'False' (or 0 or 'no', etc) if there is no row in 'canceled_trips' table of trip '0003X'. "
    prompt_text += f"I am a program, so I just need you to write me 'yes' if the `{target_col}` column in the `{target_tbl}` table can be derived from counting other rows in other tables and 'no' otherwise. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"is_count_or_exist": "yes or no"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


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

    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
    prompt_text += f"How the `{target_col}` column in the `{target_tbl}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_col}` from other columns and rows in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "
    prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from counting rows in the {given_table_name} table. However, it is not a simple COUNT(*) - I tried it and it is inaccurate. "
    prompt_text += "Probably the formula has some conditions or require minor deviation. "
    prompt_text += f"To do so, you need to look at the schema and the following data samples (called sample points): [[[START OF SAMPLE POINTS]]] {data_sharing_str} [[[END OF SAMPLE POINTS]]]. "
    prompt_text += f"I am a program, so I just need you to write me the formula that will give us the missing values of the `{target_col}` column in the `{target_tbl}` table. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. But, do not over do it, if you find one just return it. "
    prompt_text += f" As NL-to_SQL task, I want you to reflect the textual formula on an SQL query that computes {target_col} column in the {target_tbl} table from {given_table_name}. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {target_col} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks+2} columns which are the primary keys of `{target_tbl}` table {pk_columns_names}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {target_col} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{target_col}` based on the textual formula. "
    prompt_text += f"Also, Please alias the {target_tbl} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "
    prompt_text += f"Rule 1: The computation SQL shall compute the computed_value using left joins and the COUNT aggregation function. "
    prompt_text += "Rule 2: The computed value must be computed from the columns of the database, provided in the schema. "
    prompt_text += "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 3: In case of string comparisions, do not use 'FIND_IN_SET' and 'REPLACE' functions. Rather use the 'LIKE' function. "
    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample rows. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explainations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors."
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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

    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
    prompt_text += f"How the `{target_col}` column in the `{target_tbl}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_col}` from other columns and rows in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "
    prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from counting other rows in other tables. But, I do not know which table. Provide me the table name. "
    prompt_text += f"To do so, you need to look at the schema and the data samples I am sending you. "
    prompt_text += f"I am a program, so I just need you to write me the name of the table that counting its rows will give us the missing values of the `{target_col}` column in the `{target_tbl}` table. "
    prompt_text += f"If you suspect more than one candidate table, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. But, do not over do it, if you find one just return it. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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

    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
    prompt_text += f"How the `{target_col}` column in the `{target_tbl}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_col}` from other columns and rows in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "
    prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from a other rows and columns in other tables (using joins). "
    prompt_text += f"I already tested formulas to compute the `{target_col}` column using only columns from `{target_tbl}`. "
    prompt_text += f"Therefore, the formula shall not only use columns from `{target_tbl}`. Rather, the formula shall compute/derive `{target_col}` from other tables as well. "
    prompt_text += f"Even if you find that `{target_col}` can be computed/derived from other columns in `{target_tbl}` only without the need for other tables, "
    prompt_text += "do not provide this 'single-table' formula and search for 'across-tables formula'. "

    if len(used_tables) == 1:
        prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from a other rows and columns (using joins) in {other_used_tables_names_str} table. "
    else:
        prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from a other rows and columns (using joins) in some of the following tables: {other_used_tables_names_str} . "

    prompt_text += f"Take the following data samples (data points) of {target_tbl}, {other_used_tables_names_str} tables: [[[START OF DATA POINTS]]] {data_sharing_str} [[[END OF DATA POINTS]]]. "
    prompt_text += f"Based on the schema and these data points, provide the formula (textual formula) to compute `{target_col}` from other columns and rows in {other_used_tables_names_str} tables. "

    if len(used_tables) > 1:
        prompt_text += f"Some of the {other_used_tables_names_str} tables may be useless. I am not sure. You need to look at the data points and see how the value of `{target_col}` in `{target_tbl}` can be calculated from "
        prompt_text += f"the rows/columns of the {other_used_tables_names_str} tables. "

    prompt_text += f"As NL-to_SQL task, I want you to reflect the textual formula on an SQL query that computes {target_col} column in the {target_tbl} table from {other_used_tables_names_str}. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {target_col} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks+2} columns which are the primary keys of `{target_tbl}` table {pk_columns_names}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {target_col} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{target_col}` based on the textual formula. "
    prompt_text += f"Also, Please alias the {target_tbl} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "
    prompt_text += "Rule 1: Do not use aggregation functions that include values retrieved from left joins. Rather, the left join clause shall include the aggregation functions inside it. "
    prompt_text += "Example of wrong SQL: SELECT id, SUM(i.amount) - SUM(o.amount) as balance from account a left join (select account_id, amount from income) as i on a.id = i.account_id left join (select account_id, amount from outcome) as o on a.id = o.account_id; "
    prompt_text += "Example of correct SQL: SELECT id, total_income.value - total_outcome.value as balance from account a left join (select account_id, sum(amount) as value from income group by account_id) as total_income on a.id = total_income.account_id left join (select account_id, sum(amount) as value from outcome group by account_id) as total_outcome on a.id = total_outcome.account_id; "
    prompt_text += "Avoid nesting aggregate functions; compute them in subqueries before comparison. "
    prompt_text += "Avoid creating temporary tables. "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += f"Only use the following tables: {other_used_tables_names_str}. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += f"Rule 5: Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias or direct table reference to `{target_tbl}`, and not inside any subquery, CTE, or nested SELECT. The computed_value must be derived entirely from other tables' columns. "
    prompt_text += f"Rule 6: Do NOT create a self-join — the SQL must not join `{target_tbl}` (aliased as `target_table` or any other alias) with itself. All joined tables in the FROM and JOIN clauses must be different from `{target_tbl}`. "
    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample data points. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explainations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors."
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. "
    prompt_text += "It is always preferable to have multiple candidate formulas so that we can test multiple ones. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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
                "used_tables": f" Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas",
                "used_columns": " Only the names of the columns that are used in the textual_formula do not add the joining columns",
                "confidence_score": " a number from 0 to 100"
            },
            {
                "textual_formula": " write here the other candidate formula, if any ",
                "used_tables": f" Only the names of the tables that are used in the textual_formula do not add the intermediate tables that are required for joins unless they have columns used for the formulas ",
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
    payload_example_2 = {
        "candidate_formulas": "NaN"
    }

    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"In `{target_tbl}` table, `{target_col}` column has some missing values. "
    prompt_text += f"How the `{target_col}` column in the `{target_tbl}` table can be calculated? "
    prompt_text += f"I need to find a formula (i.e. equation) that derives or computes the missing values of `{target_col}` from other columns and rows in other tables (using joins) in the database. "
    prompt_text += "The schema (especially the PK-FK dependencies) is essential to explore this. "
    prompt_text += f"The `{target_col}` column in the `{target_tbl}` table can be derived from a other rows and columns in other tables (using joins). "
    prompt_text += "However, I do not know the formula and I want you to provide me the formula. "
    prompt_text += f"I already tested formulas to compute the `{target_col}` column using only columns from `{target_tbl}`. "
    prompt_text += f"Therefore, the formula shall not only use columns from `{target_tbl}`. Rather, the formula shall compute/derive `{target_col}` from other tables as well. "
    prompt_text += f"Even if you find that `{target_col}` can be computed/derived from other columns in `{target_tbl}` only without the need for other tables, do not provide this 'single-table' formula and search for 'across-tables formula'. "
    prompt_text += f"CRITICAL: Every candidate's `used_tables` MUST include at least one table that is NOT `{target_tbl}`. A formula whose `used_tables` contains only `{target_tbl}` (i.e. a self-join on the target table) is strictly forbidden and must not be returned. "
    prompt_text += f"I am a program, so I just need you to write me the formula that will give us the missing values of the `{target_col}` column in the `{target_tbl}` table using stored values in the database. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. "
    prompt_text += f"I expect having multiple candidate formulas. Try to bring {config.max_candidate_formulas_across_tables} realistic formulas. "
    prompt_text += f"Also, do not limit the search single-hob join tables. Maybe the formula requires accessing tables that require 2-hob or 3-hob joins (or even more). "
    prompt_text += "In addition, Provide the names of the tables and columns that are used in the formula. "
    prompt_text += "For example, assume a table T contains column C (among other columns in T) and we want to find a formual to compute C from other tables and table T1 (a parent of table T) contains colums A and B (among other columns in T1) "
    prompt_text += "and another table T2 (a child of table T) contains columns X, Y and Z (among other columns in T2). "
    prompt_text += "Assume the textual formula to compute column C in table T is: IF T1.A is True then T.C = SUM(T2.X) ELSE (i.e. T1.A is False) then T.C = SUM(T2.X - T2.Y). "
    prompt_text += "In this example the used tables for the above formula are T1 and T2 and the used columns are T1.A, T2.X and T2.Y. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "In the above example, the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
    prompt_text += "In you do not find any formula, the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


def prompt_common_formula_from_list(
    target_col: str,
    target_tbl: str,
    formula_list: list,
    target_tbl_description: str
) -> str:
    """Extract the most frequent semantic formula from a list of candidate formulas."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns or rows in the same table. "
    prompt_text += f"I have a list of potential formulas to compute `{target_col}`. Some formulas in the list are the same semantically. "
    prompt_text += f"Here are the formulas: {formula_list}. "
    prompt_text += f"Provide me the most frequent semantic formula. "
    prompt_text += f"I am a program, so only response with the formula without any addition or justification. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"common_formula": "the most frequent formula"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_classify_table_type_chaining_or_hierarchical(
    target_col: str,
    target_tbl: str,
    common_formula: str,
    target_tbl_description: str
) -> str:
    """Classify the target table as a chaining table or a hierarchical table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Here is a potential formula: {common_formula}. "
    prompt_text += f"Hence, to compute `{target_col}`, we need to access other rows with a specific creteria. "
    prompt_text += f"There are two types of tables in this context. "
    prompt_text += f"The first one is the 'chaining table' and the second one is the 'hierarchical table'. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"The hierarchical table is a table that has a tree-like structure such that each row in it has at one parent row (except the root row) and children rows (except the leaf rows). "
    prompt_text += f"From the shecma and the formula (beside others), I want you to say whether `{target_tbl}` is a chaining table or a hierarchical table. "
    prompt_text += f"I am a program, so only response with 'chaining table' or 'hierarchical table' without any addition or justification. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"table_type": "chaining table or hierarchical table"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_row_scope_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list
) -> str:
    """Discover row-scope formulas for the target column using sample rows."""
    payload = {
        "formula_1":
        {
            "formula": f"{target_col} = X * 100 / square(Y) ... ",
            "columns": ["X", "Y"]
        },
        "formula_2": {
            "formula": f"{target_col} = A - (2 * B) ... ",
            "columns": ["A", "B"]
        }
    }

    prompt_text = f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns in the same table. "
    prompt_text += f"I want you to provide me the formula to compute `{target_col}` and the names of the columns in `{target_tbl}` that are needed to compute/derive the `{target_col}` column in the formula. "
    prompt_text += f"Here are {len(result)} sample rows of {target_tbl} table: columns names are ({columns_names_str}) and rows values are ({result}). "
    prompt_text += f"As `{target_col}` will be in the left side of the formula, it is very imporant to avoid a formula that has `{target_col}` in the right side of the formula. "
    prompt_text += f"It is possible to have more than one formula to compute `{target_col}`. Provide all possible formulas. "
    prompt_text += f"You shall rely on the schema and the sample rows that I have provided you above. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "

    return prompt_text


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
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns in the same table. "
    prompt_text += f"Here is a description of the `{target_tbl}` table: [[[START OF DESCRIPTION]]] {target_tbl_description} [[[START OF DESCRIPTION]]]. "
    prompt_text += f"Here are {len(result)} sample rows of {target_tbl} table: columns names are ({columns_names_str}) and rows values are ({result}). "
    prompt_text += f"Also, here is the textual formula to compute `{target_col}`: {formula}. "
    prompt_text += f" As NL-to_SQL task, I want you to reflect the textual formula on an SQL query that computes {target_col} column in the {target_tbl} table from {columns_to_compute_str}. "
    prompt_text += "The computation query shall not modify or fill missing values. "
    prompt_text += "The computation query is only to run it in the database to confirm whether the formula (i.e. equation) is correct or not. "

    if number_of_pks == 0:
        prompt_text += f"The computation query is a select query that returns two columns which are the computed_value which is resulted from the textual formula and "
        prompt_text += f"the actual value of {target_col} (alias it as actual_value). "
    else:
        prompt_text += f"The computation query is a select query that returns {number_of_pks+2} columns which are the primary keys of `{target_tbl}` table {pk_columns_names}, computed_value which is "
        prompt_text += f"resulted from the textual formula and the actual value of {target_col} (alias it as actual_value). "

    prompt_text += f"In other words, computed_value is the predicted value of `{target_col}` based on the textual formula. "
    prompt_text += f"Avoid using `{target_col}` to calculate the computed_value of the same row. This is very important. Otherwise, we will have overfitting problem. "
    prompt_text += f"In addition, Please alias the {target_tbl} table in the outer query's FROM clause as target_table. "
    prompt_text += "To ensure the correctness of the query, consider the following rules: "
    prompt_text += f"Rule 1: The computation SQL shall compute the computed_value from `{target_tbl}` without any join or a nested query. "
    prompt_text += "Rule 2: Rounding is not required at all. "
    prompt_text += "Rule 3: The computed value must be computed from the columns of the database, provided in the schema. "
    prompt_text += "So, do not consider a column as a computed column just because it might be computed by a formula that do not apply to the schema. "
    prompt_text += "Rule 4: When performing arithmetic operations that may result in negative values, ensure all operands — especially UNSIGNED columns — are cast to SIGNED before the operation to prevent overflow errors. "
    prompt_text += f"Rule 5: Do not use `{target_col}` in the computed_value of the same row. "
    prompt_text += f"For example, avoid the following case: {target_col} = column_x + ({target_col} - column_x). "
    prompt_text += f"Also, do not use target_table.`{target_col}` in the computed_value at all. "
    prompt_text += "Provide me the computation query that shall be executed in MySQL. "
    prompt_text += "In addition, it is very important to make the computation query applies the textual formula without any variance. "
    prompt_text += f"Pay attention to the sample rows. "
    prompt_text += "I am a program, so I just need you to write me in your answer the SQL query that I can run to verify the formula. Only the SQL query (without explainations) such that I execute it immediately without parsing and modification. "
    prompt_text += "Be careful and make the computation query free-of-errors."

    return prompt_text


def prompt_single_table_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str
) -> str:
    """Discover candidate formulas for a single-table computed column with sample data."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns or rows in the same table. "
    prompt_text += f"Provide me a formula to compute the `{target_col}` from other rows in `{target_tbl}` table. "
    prompt_text += f"The formula shall be a textual description with 200 characters at max. The formula shall be correct, realistic and represent the real cases. "
    prompt_text += f"Clarify whether the the formula requires accessing other rows from the table or not. "
    if len(result) > 0:
        prompt_text += f"Here are {len(result)} sample rows of {target_tbl} table: columns names are ({columns_names_str}) and rows values are ({result}). "
        prompt_text += f"I am sending you the data so that you can see each row individually and can decide whether the value of {target_col} of a certain row can be computed from other column in the same row or requires accessing other rows. "
        prompt_text += f"Keep in mind that these are randomly selected rows and the table I am providing you is incomplete. "
        prompt_text += f"Pay attention to the data and clarify in the formula if other row in the table are required to compute {target_col} of a certain row or not. "
    prompt_text += f"I am a program, so only response with the formula without any addition or justification. If you do not find a formula respond with 'None' "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"formula": "the formula or None"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


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
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns or rows in the same table. "
    prompt_text += f"If `{target_col}` is computed from other rows in `{target_tbl}` table, then it is a table-scope computed column. "
    prompt_text += f"To make it clearer, let me give an example. "
    prompt_text += f"Assume in `{target_tbl}` we have two rows R1 and R2 and x and y columns. If R2.x is computed/derived from function(R1.x) or function(R1.y) or function(R1.x, R1.y) or function(R1.x, R2.y) or function(R1.y, R2.y) "
    prompt_text += "or function(R1.x, R1.y, R2.y), then it is a table-scope computed column because to compute a the column y in R2 it needs at least one value stored in other rows (R1 in the example) in the table. "
    prompt_text += f"Otherwise, if `{target_col}` is computed from other columns in `{target_tbl}` table without the need to access other rows in the same table, then it is a row-scope computed column. "
    prompt_text += f"For example, if R2.x is computed/derived from function(R2.y [without having R1 at all in the function]), then it is row-scope computed column because the column can be computed/derived relying on the row content only. "
    prompt_text += f"Here is a textual description of the potential formula: {formula}"
    if len(result) > 0:
        prompt_text += f"Also, here are {len(result)} sample rows of {target_tbl} table: columns names are ({columns_names_str}) and rows values are ({result}). "
    prompt_text += f"I am a program, so I just need you to write me 'table-scope' if `{target_col}` column in the `{target_tbl}` table is a table-scope computed column and 'None' otherwise. "
    prompt_text += f"I am a program, so only response with 'table-scope' or 'None' without any addition or justification. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"scope_type": "table-scope or None"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_is_single_table_computed_value_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str
) -> str:
    """Determine whether the target column can be computed from rows/columns in the same table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_tbl_description + " "
    prompt_text += f"The `{target_col}` column in table `{target_tbl}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other columns in the database. "
    prompt_text += f"However, I am not sure if join with other tables are required to compute `{target_col}`. "
    prompt_text += f"`{target_col}` might be computed from other columns/rows in the same table i.e. `{target_tbl}` without the need to access other tables. "
    prompt_text += f"I want you to confirm whether `{target_col}` can be computed from other columns/rows in the same table (i.e. `{target_tbl}`) or not. "
    prompt_text += f"To do so, you need to expect a formula that requires columns from only `{target_tbl}` table to compute/derive `{target_col}`. Try to figure out the correlation between columns and rows. "
    prompt_text += f"Be realistic. Do not be very pessimistic and do not be very optimistic. "
    prompt_text += f"Use the table name (i.e. `{target_tbl}`) and the names of all columns in `{target_tbl}`. "
    prompt_text += "Note, some column names are abbreviations. So, you should predict the complete name of all columns. "
    prompt_text += "Also, some columns are part of an equation and you need to extract the reverse equation. "
    prompt_text += "For example, assume we have a table that contains total_price, quantity and unit_price columns. The equation that all of us know is total_price = quantity * unit_price. "
    prompt_text += "If we ask whether quantity is computed from the same table or not, then the answer shall be 'yes' because quantity = total_price / unit_price. "
    prompt_text += f"If the `{target_col}` column is computed/derived from other coulmns/rows of `{target_tbl}`, consider are three types of tables in this context. "
    prompt_text += f"The first one is the 'row-wise table'. The second one is the 'chaining table' and the third one is the 'hierarchical table'. "
    prompt_text += f"The row-wise table a table that each row is independent and not related to other rows. In this case, `{target_col}` might be computed from other columns in the same row. "
    prompt_text += f"The chaining table is a table that each row in it has a previous row (except the first in the chain) and a next row (except the last in the chain). "
    prompt_text += f"The hierarchical table is a table that has a tree-like structure such that each row in it has at one parent row (except the root row) and children rows (except the leaf rows). "
    prompt_text += f"I am a program, so I just need you to write me 'yes' if you found a formula to calculate/derive the `{target_col}` column in the `{target_tbl}` table from columns/rows in the same table and 'no' if accessing other tables is needed. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

    payload = {"is_computed": "yes or no"}
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_hierarchical_parent_reference_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list
) -> str:
    """Identify parent-reference columns for a hierarchical table (smartly-selected variant with full examples)."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + target_table_description + " "
    prompt_text += f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific creteria. "
    prompt_text += f"`{config.target_table_name}` is a hierarchical table. "
    prompt_text += f"The hierarchical table is a table that has a tree-like structure such that each row in it has at one parent row (except the root row) and children rows (except the leaf rows). "
    prompt_text += f"Each row in the hierarchical table refers to its parent row, if any, i.e. stores the identifier of its parent row in one of its columns. "

    if len(names_of_pk_columns_of_target_table) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is {names_of_pk_columns_of_target_table[0]}. "
        else:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is the follwoing composite key: {names_of_pk_columns_of_target_table}. "

    prompt_text += f"[Example 1] Assume a hierarchical table T has more than 3 columns (A, B, C ...). "
    prompt_text += "Column A is the identifier and Column C is the column that refers to the identifier of the parent row. We call column C as 'parent-referencing-column' and we call column A as 'parent-reference-column'. "
    prompt_text += "Assume the hierarchical table T stores the following 6 rows:"
    prompt_text += "R1 (0, 'any', null, ...), R2 (1, 'any', 0, ...), R3 (2, 'any', 0, ...), R4 (3, 'any', 2, ...), R5 (4, 'any', null, ...), R6 (5, 'any', 4, ...). "
    prompt_text += "From the rows and relying on Column A and Column C, we can find that R1 is a parent of R2 and R3 while R3 is a parent of R4 and R5 is a parent of R6. "
    prompt_text += "Also, we can see that R1 and R4 do not have parents. "
    prompt_text += f"[Example 2] Assume a hierarchical table T has more than 5 columns (A, B, C, D, E ...) and it has a composite primary key A and B. "
    prompt_text += f"Each child refers to its parent as follows: Column C in child refers to (equal) Column A of the parent and Column D in child refers to (equal) Column B of the parent. "

    if len(names_of_pk_columns_of_target_table) == 0:
        prompt_text += f"As `{config.target_table_name}` is a hierarchical table and as it does not have identifier i.e. column `{names_of_pk_columns_of_target_table[0]}`, "
        prompt_text += "I want you to provide me the name of the parent-reference-column and the parent-referencing-column. "
    else:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table and as it has one identifier i.e. column `{names_of_pk_columns_of_target_table[0]}`, I want you to provide me the name of the parent-referencing-column. "
        else:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table and as it has composite key identifier i.e. column `{names_of_pk_columns_of_target_table[0]}`, "
            prompt_text += "I want you to provide me the name of the parent-referencing-column of each parent-reference-column. "

    prompt_text += f"You shall rely on the schema and the sample rows that I have provided you above. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "

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

    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "In [Example 1], the expected JSON is:" + json.dumps(payload_example_1, ensure_ascii=False) + ". "
    prompt_text += "In [Example 2], the expected JSON is:" + json.dumps(payload_example_2, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


def prompt_hierarchical_candidate_formula_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str
) -> str:
    """Find candidate formulas for a hierarchical table (smartly-selected variant with full examples)."""
    from src.core.config import config

    prompt_text = f"The `{config.target_column_name}` column in table `{config.target_table_name}` is a computed value. "
    prompt_text += "A computed value means that the data of the column can be computed or derived from other rows in the same table. "
    prompt_text += f"Hence, to compute `{config.target_column_name}`, we need to access other rows with a specific creteria. "
    prompt_text += f"Here is a description of the `{config.target_table_name}` table: [[[START OF DESCRIPTION]]] {target_table_description} [[[START OF DESCRIPTION]]]. "
    prompt_text += f"`{config.target_table_name}` is a hierarchical table. "
    prompt_text += f"The hierarchical table is a table that has a tree-like structure such that each row in it has at one parent row (except the root row) and children rows (except the leaf rows). "
    prompt_text += f"Each row in the hierarchical table refers to its parent row, if any, i.e. stores the identifier of its parent row in one of its columns. "

    if len(names_of_pk_columns_of_target_table) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is {names_of_pk_columns_of_target_table[0]}. "
        else:
            prompt_text += f" The identifier of rows in `{config.target_table_name}` is the follwoing composite key: {names_of_pk_columns_of_target_table}. "

    prompt_text += f"[Example 1] Assume a hierarchical table T has more than 3 columns (A, B, C ...). "
    prompt_text += "Column A is the identifier and Column C is the column that refers to the identifier of the parent row. We call column C as 'parent-referencing-column' and we call column A as 'parent-reference-column'. "
    prompt_text += "Assume the hierarchical table T stores the following 6 rows:"
    prompt_text += "R1 (0, 'any', null, ...), R2 (1, 'any', 0, ...), R3 (2, 'any', 0, ...), R4 (3, 'any', 2, ...), R5 (4, 'any', null, ...), R6 (5, 'any', 4, ...). "
    prompt_text += "From the rows and relying on Column A and Column C, we can find that R1 is a parent of R2 and R3 while R3 is a parent of R4 and R5 is a parent of R6. "
    prompt_text += "Also, we can see that R1 and R4 do not have parents. "
    prompt_text += f"[Example 2] Assume a hierarchical table T has more than 5 columns (A, B, C, D, E ...) and it has a composite primary key A and B. "
    prompt_text += f"Each child refers to its parent as follows: Column C in child refers to (equal) Column A of the parent and Column D in child refers to (equal) Column B of the parent. "

    if len(parent_reference_columns_list) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table and as it has one identifier, the parent-reference-column is `{parent_reference_columns_list[0][0]}` and its parent-referencing-column is {parent_reference_columns_list[0][1]}. "
        else:
            prompt_text += f"As `{config.target_table_name}` is a hierarchical table and as it has composite key identifier i.e. column `{names_of_pk_columns_of_target_table[0]}`, here is the list of each pair of parent-reference-column and its parent-referencing-column: "
            for parent_reference_columns in parent_reference_columns_list:
                prompt_text += f"The parent-reference-column is `{parent_reference_columns[0]}`, and its parent-referencing-column is {parent_reference_columns[1]}. "

    prompt_text += f"Take the following data samples of `{config.target_table_name}` table: {data_for_sharing_with_LLM_str}. "
    prompt_text += f"Based on the schema and these data samples, provide the formula to compute `{config.target_column_name}` from other columns and rows in `{config.target_table_name}`. "
    prompt_text += "Be consise and provide only one formula. The formula shall be completely compatible with the data samples. Use for the formula useful terms such as 'parent_row', 'children_rows' and 'child_row'. "
    prompt_text += "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
    prompt_text += f"If you suspect more than one candidate formula, provide them all and provide a confidence score to each - the sum of all confidence scores shall be 100. But, do not over do it, if you find one just return it. "

    payload = {
        "candidate_formulas": [
            {"textual_formula": f" write here the most potential formula to compute `{config.target_column_name}` "},
            {"textual_formula": f" write here the other candidate formula to compute `{config.target_column_name}`, if any "}
        ]
    }
    prompt_text += "JSON format:" + json.dumps(payload, ensure_ascii=False) + ". "
    prompt_text += "Provide the JSON. "
    return prompt_text


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
