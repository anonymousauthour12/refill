"""LLM Prompt Templates (Skills Style) — Template 3.

Concise, markdown-structured prompts using bullet rules, XML tags for variable
content, and imperative voice. 30-50% shorter than template_2.
Each function has the same signature and return type as template_1/template_2.
"""

import json
from src.core.config import config
from src.steps.formula_common import (
    load_database_columns_metadata,
    load_database_distinct_values,
    load_database_sample_rows,
    load_database_schema,
)


# ============================================================================
# HELPER: _build_skill_prompt
# ============================================================================

def _build_skill_prompt(
    role: str = "",
    context: str = "",
    task: str = "",
    rules: list = None,
    output: str = "",
) -> str:
    """Assemble a skills-style prompt from semantic sections."""
    parts = []
    if role:
        parts.append(f"**Role:** {role}")
    if context:
        parts.append(f"# Context\n{context}")
    if task:
        parts.append(f"# Task\n{task}")
    if rules:
        rules_str = "\n".join(f"- {r}" for r in rules)
        parts.append(f"## Rules\n{rules_str}")
    if output:
        parts.append(f"# Output Format\n{output}")
    return "\n\n".join(p for p in parts if p)


# ============================================================================
# HELPER: _get_json_prompt
# ============================================================================

def _get_json_prompt(payload: dict) -> str:
    """Format a strict JSON output instruction."""
    return (
        "Return the result STRICTLY in the JSON format described below, with no extra commentary. "
        "Write all string values on a single line — do NOT include raw newlines or line breaks inside JSON string values. "
        "JSON format example:" + json.dumps(payload, ensure_ascii=False) + ". "
        "Provide the JSON. "
    )


# ============================================================================
# SCHEMA UNDERSTANDING PROMPTS
# ============================================================================

def prompt_get_table_description_columns(table_name: str) -> str:
    role = "Database analyst specializing in relational schema semantics."
    task = (
        f"Describe every ambiguous or abbreviated column in <table>{table_name}</table>.\n"
        "Skip columns whose names are already self-explanatory."
    )
    rules = [
        "Keep each description under 20 words.",
        "Use sibling column names, FK relationships, and domain context to resolve abbreviations.",
        "Only include columns that need clarification.",
    ]
    payload = {"column_descriptions": [{"column_name": "...", "description": "..."}]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(role=role, task=task, rules=rules, output=output)


def prompt_get_table_description_correlations(
    table_name: str,
    column_name: str,
    target_table_description: str,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\nTable description: " + target_table_description
    task = (
        f"Identify in-table correlations between <column>{column_name}</column> "
        f"and other columns inside <table>{table_name}</table> only."
    )
    rules = [
        "Describe mathematical, categorical, or logical relationships only.",
        "Do not speculate about cross-table relationships.",
        f"If no in-table correlations exist for `{column_name}`, return None.",
    ]
    payload = {"correlations": "describe correlations here or None if none found"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(role="Database analyst identifying intra-table correlations.", context=context, task=task, rules=rules, output=output)


# ============================================================================
# FORMULA DETECTION PROMPTS
# ============================================================================

def prompt_is_computed_column(
    target_table_description: str,
    target_column_name: str,
    target_table_name: str,
    strategy: int = 1,
) -> str:
    initial_prompt_str = get_initial_prompt_str(strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"Determine whether <column>{target_column_name}</column> in "
        f"<table>{target_table_name}</table> is a computed/derived column.\n"
        f"If yes, identify the formula. Provide multiple candidates with confidence scores summing to 100 if uncertain."
    )
    rules = [
        "Use PK-FK dependencies in the schema to explore derivation paths.",
        "Look for aggregation (SUM, COUNT, AVG), arithmetic, string, date, and conditional patterns.",
        "Bias towards computed: if any plausible derivation path exists via joined tables, report it as a candidate even if uncertain.",
        "Do NOT return None just because you are unsure — propose the most likely formula with a low confidence score instead.",
    ]
    if strategy >= 2:
        rules.append("Use provided column statistics and distinct values to confirm patterns.")
    if strategy >= 3:
        rules.append("Use sample rows to verify the formula against real data.")
    rules.append("Return None in `candidate_formulas` only if absolutely no derivation path exists.")
    payload = {
        "candidate_formulas": [
            {"textual_formula": f" most likely formula to compute `{target_column_name}` "},
            {"textual_formula": f" alternative formula to compute `{target_column_name}`, if any "},
        ]
    }
    payload_none = {"candidate_formulas": "None"}
    output = (
        "JSON format example: " + json.dumps(payload, ensure_ascii=False) + "\n"
        "If no formula found: " + json.dumps(payload_none, ensure_ascii=False) + "\n"
        "Provide the JSON."
    )
    return _build_skill_prompt(
        role="Database engineer reverse-engineering computed columns from relational schemas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_semantic_plausibility_check(
    textual_formula: str,
    computation_sql_query: str,
    target_column_name: str,
    target_table_name: str,
) -> str:
    task = (
        f"Assess whether the proposed formula for <column>{target_column_name}</column> "
        f"in <table>{target_table_name}</table> is semantically plausible."
    )
    context = (
        f"Proposed formula: {textual_formula}\n"
        f"SQL: {computation_sql_query}"
    )
    rules = [
        "Accept if any reasonable derivation path exists for the column.",
        "Reject if the formula is domain-nonsensical (e.g., dividing name strings).",
        "Reject if the formula produces a type or scale mismatch.",
        "Reject if the formula circularly references the target column itself.",
        "Reject if the SQL or formula uses hardcoded lists of specific data instances — e.g., FirstName IN ('Ken', 'Rob', 'Michael', ...) or ID IN (1, 3, 7, ...) — to derive the computed value. This is data overfitting from training data, not a schema-derived formula.",
        "When in doubt, accept — only hard rejections should return false.",
    ]
    payload = {"is_plausible": True, "reason": "<brief reason>"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# SQL GENERATION PROMPTS
# ============================================================================

def prompt_find_formulas_and_computation_sql(
    target_table_description: str,
    target_column_name: str,
    target_table_name: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description

    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = (
            f"SELECT actual_value (= `{target_column_name}`) and computed_value."
        )
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{target_column_name}`), and actual_value (= `{target_column_name}`)."
        )

    task = (
        f"Find up to {config.max_candidate_formulas_single_table} realistic candidate formulas that derive <column>{target_column_name}</column> "
        f"in <table>{target_table_name}</table> from other columns (same table or joined tables).\n"
        "For each candidate, also write a MySQL computation SQL query that returns actual_value vs computed_value "
        "so the formula can be verified — do not modify or fill data.\n"
        f"{select_desc}\n"
        f"Alias <table>{target_table_name}</table> as `target_table` in the outer FROM clause.\n"
        "Assign a confidence score to each candidate (scores sum to 100). "
        "Include used_tables and used_columns (only formula-relevant ones, not join-only intermediates). "
        "Explore 1-hop, 2-hop, and 3-hop+ joins."
    )
    rules = [
        "Do not use aggregation on values from LEFT JOIN directly — put aggregation inside the subquery.",
        (
            "Correct: SELECT id, total_income.value - total_outcome.value AS balance FROM account a "
            "LEFT JOIN (SELECT account_id, SUM(amount) AS value FROM income GROUP BY account_id) AS total_income "
            "ON a.id = total_income.account_id ..."
        ),
        "Rounding is not required.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        "Use LIKE for string comparisons — never FIND_IN_SET or REPLACE.",
        "Discard semantically equivalent formulas — keep only one representative.",
        f"Do NOT read `{target_column_name}` from `{target_table_name}` anywhere in the SQL — not via `target_table`, not via any other alias of `{target_table_name}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_column_name}`), MIN(`{target_column_name}`), SUM(`{target_column_name}`) applied to `{target_table_name}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. Reading the target column to predict itself is circular and invalid.",
        "Write efficient SQL: use JOINs with GROUP BY instead of correlated subqueries; avoid SELECT COUNT(*) or ORDER BY+LIMIT inside a correlated subquery on large tables.",
        "Do NOT propose data-fitting formulas. Do not hardcode specific data instances — person names, IDs, enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. The formula must follow structural schema logic (FK-PK joins, aggregations, type constraints), not memorized training data. Example of a forbidden query: CASE WHEN FirstName IN ('Ken', 'Michael', 'Roberto', ...) THEN 'M' — this is data overfitting and is invalid.",
        "Return only valid MySQL syntax; no explanations outside the JSON.",
    ]

    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " most potential formula, e.g. x = AVG(y + z) from another table ",
                "used_tables": " table names used in the formula (not mere join intermediates) ",
                "used_columns": " column names used in the formula (not mere join keys) ",
                "confidence_score": " 0–100 ",
                "computation_sql_query": (
                    " SELECT T1.x AS actual_value, AVG(T2.y + T2.z) AS computed_value "
                    "FROM tbl_1 T1 LEFT JOIN tbl_2 T2 ON T1.id = T2.id GROUP BY T1.id, T1.x "
                ),
            },
            {
                "textual_formula": " alternative formula, if any, e.g. x = y + z ",
                "used_tables": " table names ",
                "used_columns": " column names ",
                "confidence_score": " 0–100 ",
                "computation_sql_query": " SELECT x AS actual_value, y + z AS computed_value FROM tbl_1 ",
            },
        ]
    }
    payload_example_1 = {
        "candidate_formulas": [
            {
                "textual_formula": " T.C = IF T1.A is True then SUM(T2.X) ELSE SUM(T2.X - T2.Y) ",
                "used_tables": ["T1", "T2"],
                "used_columns": ["T1.A", "T2.X", "T2.Y"],
                "confidence_score": "70",
                "computation_sql_query": (
                    " SELECT T.C AS actual_value, "
                    "SUM(CASE WHEN T1.A THEN T2.X ELSE T2.X - T2.Y END) AS computed_value "
                    "FROM tbl T LEFT JOIN tbl_1 T1 ON T.id = T1.id LEFT JOIN tbl_2 T2 ON T.id = T2.id "
                    "GROUP BY T.id, T.C "
                ),
            }
        ]
    }
    payload_example_nan = {"candidate_formulas": "NaN"}

    output = (
        "JSON format: " + json.dumps(payload, ensure_ascii=False) + "\n"
        "Example result: " + json.dumps(payload_example_1, ensure_ascii=False) + "\n"
        "If no formula found: " + json.dumps(payload_example_nan, ensure_ascii=False) + "\n"
        "Provide the JSON."
    )
    return _build_skill_prompt(
        role="SQL developer generating verification queries for derived columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# ERROR RECOVERY PROMPTS
# ============================================================================

def prompt_diagnose_formula_mismatch(
    computation_sql_query: str,
    diagnoses_sql_query: str,
    diagnoses_sql_query_result_str: str,
    target_column_name: str,
    target_table_name: str,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str
    task = (
        f"The computation query for <column>{target_column_name}</column> in "
        f"<table>{target_table_name}</table> produces mismatches against actual values.\n\n"
        f"Computation query: {computation_sql_query}\n\n"
        f"Diagnoses query: {diagnoses_sql_query}\n\n"
        f"Diagnoses result: {diagnoses_sql_query_result_str}\n\n"
        "Identify the root cause and return a corrected computation SQL query."
    )
    rules = [
        "Compare actual_value vs computed_value in the diagnoses result to spot the error type.",
        "Apply the minimal fix — do not redesign the formula unless it is fundamentally wrong.",
        "Return only the corrected SQL query, executable immediately without modification.",
        "Query must be free of errors and valid MySQL syntax.",
    ]
    payload = {"computation_sql_query_after_diagnoses": "WRITE THE MODIFIED COMPUTATION QUERY HERE"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL debugger diagnosing formula-to-actual mismatches.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_fix_sql_query_error(query: str, error: str) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str
    task = (
        f"Fix the MySQL query below so it executes without errors.\n\n"
        f"Query: [[[START]]] {query} [[[END]]]\n\n"
        f"Error: {error}"
    )
    rules = [
        "Preserve the original query intent — only fix the syntax or structural error.",
        "Return only the complete corrected SQL query, no explanations.",
        "Ensure schema compatibility.",
    ]
    payload = {
        "computation_sql_query": (
            f" error-free SQL query to compute {config.target_column_name} "
        )
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="MySQL developer fixing syntax and runtime query errors.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_fix_timeout_with_subset(query: str, error: str, target_table: str, target_column: str) -> str:
    task = (
        f"The query below timed out — this is a performance issue, not a syntax error.\n\n"
        f"Query: [[[START]]] {query} [[[END]]]\n\n"
        f"Error: {error}\n\n"
        f"Rewrite it to validate on a subset of at most 1000 rows from <table>{target_table}</table> "
        f"where <column>{target_column}</column> IS NOT NULL and has diverse values."
    )
    rules = [
        f"Build the subset as: SELECT * FROM `{target_table}` WHERE `{target_column}` IS NOT NULL LIMIT 1000.",
        "Apply the original formula logic on top of this subset — do not change what is being computed.",
        "Preserve the actual_value / computed_value column aliases required by the validation framework.",
        "The rewritten query must complete within 10 minutes on a large MySQL database.",
    ]
    payload = {"computation_sql_query": f"the rewritten SQL query that validates on a 1000-row subset of {target_table}"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="MySQL performance expert rewriting timed-out queries to use a representative subset.",
        context="",
        task=task,
        rules=rules,
        output=output,
    )


def prompt_optimize_sql_query(computation_sql_query: str, explain_results: str) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str
    task = (
        f"The MySQL query below is too expensive to execute (full table scan or large cross-product "
        f"detected by EXPLAIN).\n\n"
        f"Query: [[[START]]] {computation_sql_query} [[[END]]]\n\n"
        f"EXPLAIN output:\n{explain_results}\n\n"
        f"Rewrite the query to be efficient: eliminate full table scans, use indexed joins, "
        f"avoid correlated subqueries. If it cannot be made efficient, return null."
    )
    rules = [
        "Use JOINs with GROUP BY instead of correlated subqueries in SELECT or WHERE.",
        "Avoid SELECT COUNT(*) or ORDER BY+LIMIT inside correlated subqueries on large tables.",
        "Preserve the original formula intent — only change the execution strategy.",
        "If no efficient rewrite is possible, set computation_sql_query to null.",
    ]
    payload = {"computation_sql_query": f"efficient SQL to compute {config.target_column_name}, or null"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="MySQL performance expert rewriting expensive queries.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# DATA CLEANING PROMPTS (Rename Tables & Columns)
# ============================================================================

def prompt_rename_table(
    table_name: str,
    column_names_str: str,
    table_headers: str,
    table_sample_rows: str,
    include_data: bool = False,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context_parts = [initial_prompt_str]
    if include_data:
        context_parts.append(
            f"Sample rows of <table>{table_name}</table>: {table_headers} {table_sample_rows}"
        )
    context = "\n\n".join(context_parts)

    task = (
        f"Rename <table>{table_name}</table> (columns: {column_names_str}) "
        "to a clear, singular, unambiguous noun — or return `representative_name` if the current name is already clear."
    )
    rules = [
        "Use column names and FK relationships to resolve ambiguity (e.g., <table>HR</table> with `patient_id` → HeartRate).",
        "Return `representative_name` if the name is already clear.",
    ]
    if include_data:
        rules.append(f"Use the sample rows of <table>{table_name}</table> to confirm the entity type.")
    rules += [
        "Use FK-linked table names to infer abbreviations (e.g., `ords` linked to `order_items` → `orders`).",
        "Make the name singular (e.g., `Employees` → `Employee`).",
        "Return exactly one word — no explanation.",
    ]
    payload = {"table_name": "new_name_or_representative_name"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database naming expert applying semantic naming conventions.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_rename_column(
    column_name: str,
    table_name: str,
    column_names_str: str,
    distinct_values_str: str,
    table_headers: str,
    table_sample_rows: str,
    include_data: bool = False,
    include_distinct_values: bool = False,
) -> str:
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context_parts = [initial_prompt_str]
    if include_distinct_values:
        context_parts.append(
            f"Distinct values of <column>{column_name}</column>: {distinct_values_str}"
        )
    if include_data:
        context_parts.append(
            f"Sample rows of <table>{table_name}</table>: {table_headers} {table_sample_rows}"
        )
    context = "\n\n".join(context_parts)

    task = (
        f"Rename <column>{column_name}</column> in <table>{table_name}</table> "
        "to a clear, unambiguous name — or return `representative_name` if the current name is already clear."
    )
    rules = [
        f"Use sibling column names in <table>{table_name}</table> to resolve domain ambiguity "
        f"(e.g., `BP` with `patient_id` → `blood_pressure`).",
        "Return `representative_name` if the name needs no change.",
    ]
    if include_data:
        rules.append(f"Use the sample rows of <table>{table_name}</table> to confirm meaning.")
    rules.append(
        f"Use FK-linked tables and their columns to infer abbreviations "
        f"(e.g., `ord_no` in a table linked to `order` → `order_number`)."
    )
    if include_distinct_values:
        rules += [
            f"Use the distinct values of <column>{column_name}</column> to infer semantic meaning.",
            "Correct scale mismatches: e.g., rename `return_ratio` to `return_percentage` if values are 0–100.",
        ]
    rules.append("Return exactly one word — no explanation.")
    payload = {"column_name": "new_name_or_representative_name"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database naming expert applying semantic naming conventions.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# SEMANTIC CLASSIFICATION PROMPTS
# ============================================================================

def prompt_detect_topic(items: list) -> str:
    items_str = ", ".join(items)
    task = f"Identify the common semantic topic or category of: {items_str}"
    rules = [
        "Return 1 to 3 words that best label the shared theme (geography, profession, status, etc.).",
        "No explanation.",
    ]
    payload = {"topic": "one to three words"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Semantic analyst identifying the topic of a list of values.",
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# RETRY PROMPTS
# ============================================================================

def prompt_detect_topic_retry() -> str:
    task = "Your previous answer was too long. Return only 1 to 3 words identifying the topic."
    output = json.dumps({"topic": "one to three words"}, ensure_ascii=False)
    return _build_skill_prompt(
        role="Semantic analyst identifying the topic of a list of values.",
        task=task,
        output=output,
    )


def prompt_rename_table_retry() -> str:
    task = (
        "Your previous answer contained multiple words. "
        "Return exactly one word: the new table name, or `representative_name` if the current name is already good."
    )
    output = json.dumps({"table_name": "new_name_or_representative_name"}, ensure_ascii=False)
    return _build_skill_prompt(role="Database naming expert.", task=task, output=output)


def prompt_rename_column_retry() -> str:
    task = (
        "Your previous answer contained multiple words. "
        "Return exactly one word: the new column name, or `representative_name` if the current name is already good."
    )
    output = json.dumps({"column_name": "new_name_or_representative_name"}, ensure_ascii=False)
    return _build_skill_prompt(role="Database naming expert.", task=task, output=output)


# ============================================================================
# CHAINING TABLE PROMPTS
# ============================================================================

def prompt_identify_chaining_table_structure(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"<table>{config.target_table_name}</table> is a chaining table. "
        f"Identify its grouping columns and chaining columns so that previous/next rows can be located.\n\n"
        "**Chaining table definition:** Each row has a previous row (except the first) and a next row (except the last). "
        "Rows are split into groups; within each group the chaining column(s) impose an order.\n\n"
        "[Example 1] Rows: R1(0,'f',1), R2(0,'f',2), R3(0,'f',3), R4(5,'x',1), R5(5,'x',2), R6(5,'x',3). "
        "Grouping columns: [A, B]. Chaining column: [C].\n\n"
        "[Example 2] Rows: R1(1,1,5), R2(1,6,12), R3(1,13,15), R4(2,0,15), R5(2,16,22), R6(2,23,25). "
        "Grouping column: [A]. Chaining columns: [B, C] — current_row.B = previous_row.C."
    )
    rules = [
        "Look for sequence/order columns (dates, sequence numbers, next_id).",
        "Look for grouping columns that partition rows into independent chains.",
        "If no grouping is needed (one global chain), return an empty grouping_columns list.",
        "Chaining columns must always be non-empty.",
        "Return empty lists if the table is not a chaining table.",
    ]
    payload = {
        "chaining_table_info": [
            {
                "grouping_columns": ["used_column_1", "used_column_2"],
                "chaining_columns": ["used_column_3", "used_column_4"],
                "same_group_condition": ["SQL condition"],
            }
        ]
    }
    payload_ex1 = {
        "chaining_table_info": [
            {
                "grouping_columns": ["A", "B"],
                "chaining_columns": ["C"],
                "same_group_condition": [" where A = 'XXX' and B = 'XXX' "],
            }
        ]
    }
    payload_ex2 = {
        "chaining_table_info": [
            {
                "grouping_columns": ["A"],
                "chaining_columns": ["B", "C"],
                "same_group_condition": [" where A = 'XXX' "],
            }
        ]
    }
    output = (
        "JSON format: " + json.dumps(payload, ensure_ascii=False) + "\n"
        "[Example 1] expected: " + json.dumps(payload_ex1, ensure_ascii=False) + "\n"
        "[Example 2] expected: " + json.dumps(payload_ex2, ensure_ascii=False) + "\n"
        "Provide the JSON."
    )
    return _build_skill_prompt(
        role="Database analyst identifying chaining (sequential) table structures.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_chaining_table_candidate_formula(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    grouping_columns: str,
    chaining_columns: str,
) -> str:
    from src.core.config import config

    context = (
        f"Table description of <table>{config.target_table_name}</table>:\n"
        f"{target_table_description}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}"
    )
    task = (
        f"Find the formula to compute <column>{config.target_column_name}</column> "
        f"in the chaining table <table>{config.target_table_name}</table> "
        f"using previous or next rows.\n"
        f"Grouping columns: {grouping_columns}. Chaining columns: {chaining_columns}."
    )
    rules = [
        "Use terms `current_row`, `previous_row`, `next_row` in the formula.",
        "The formula must be fully compatible with the provided sample rows.",
        "Provide multiple candidates with confidence scores summing to 100 if uncertain — but do not overdo it.",
        f"Return the column names required to compute `{config.target_column_name}`.",
    ]
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": f" most likely formula to compute `{config.target_column_name}` ",
                "columns": ["X", "Y"],
            },
            {
                "textual_formula": f" alternative formula to compute `{config.target_column_name}`, if any ",
                "columns": ["A", "B"],
            },
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL formula analyst identifying computed column formulas in chaining tables.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_sql_for_chaining_table(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    grouping_columns: str,
    chaining_columns: str,
    chaining_columns_str: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list,
) -> str:
    from src.core.config import config

    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = (
            f"SELECT actual_value (= `{config.target_column_name}`) and computed_value."
        )
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{config.target_column_name}`), and actual_value (= `{config.target_column_name}`)."
        )

    context = (
        f"Table description of <table>{config.target_table_name}</table>:\n"
        f"{target_table_description}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}\n\n"
        f"Formula: [[[START]]] {formula_based_on_data_sharing} [[[END]]]"
    )
    task = (
        f"Generate a MySQL computation SQL query for <column>{config.target_column_name}</column> "
        f"in the chaining table <table>{config.target_table_name}</table>.\n"
        f"The query verifies the formula — it must not modify or fill data.\n"
        f"{select_desc}\n"
        f"Alias <table>{config.target_table_name}</table> as `target_table` in the outer FROM clause.\n"
        f"Grouping columns: {grouping_columns}. Chaining columns: {chaining_columns}."
    )
    rules = [
        f"Use a nested subquery (NOT self-join) to access the previous/next row — place it in the outer SELECT, return ONE value aliased `computed_value`.",
        f"Exclude rows that cannot be computed: if using previous row, exclude first rows of chains in WHERE; if using next row, exclude last rows.",
        f"Do NOT read `{config.target_column_name}` from `{config.target_table_name}` anywhere in the SQL — not via `target_table`, not via any other alias of `{config.target_table_name}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{config.target_column_name}`), MIN(`{config.target_column_name}`), SUM(`{config.target_column_name}`) applied to `{config.target_table_name}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only. Reading the target column to predict itself is circular and invalid.",
        "Alias target table as `target_table` in the outer FROM clause.",
        "Rounding is not required.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        "MySQL does not allow nested aggregate functions — compute aggregates in subqueries first.",
        f"Pay attention to chaining criteria ({chaining_columns_str}) to correctly identify previous/next rows.",
        "Return only valid executable MySQL — no explanations.",
    ]
    return _build_skill_prompt(
        role="SQL developer generating chaining-table computation queries.",
        context=context,
        task=task,
        rules=rules,
    )


def prompt_classify_chain_direction() -> str:
    from src.core.config import config

    task = (
        f"Determine whether <column>{config.target_column_name}</column> "
        "uses previous rows or next rows to compute its value."
    )
    rules = [
        "Review the formula and data pattern discussed so far.",
        "Return exactly one word: `previous` or `next`.",
    ]
    payload = {"direction": "previous or next"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Sequence analyst determining chaining direction.",
        task=task,
        rules=rules,
        output=output,
    )


def prompt_diagnose_chaining_formula(
    target_table_description: str,
    current: str,
    grouping_columns: list,
    chaining_columns: list,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    accuracy: float,
    diagnoses_sql_query_result_str: str,
) -> str:
    from src.core.config import config

    grouping_info = (
        f"Grouping columns: {grouping_columns}. "
        if grouping_columns
        else "No grouping columns (single global chain). "
    )
    chaining_info = (
        f"Chaining columns: {chaining_columns}."
        if len(chaining_columns) > 1
        else f"Chaining column: {chaining_columns[0]}."
    )

    context = (
        f"Table description of <table>{config.target_table_name}</table>:\n"
        f"{target_table_description}\n\n"
        f"{grouping_info}{chaining_info}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}\n\n"
        f"Incorrect formula (accuracy {accuracy}%): [[[START]]] {formula_based_on_data_sharing} [[[END]]]\n\n"
        f"Diagnoses query results (random sample): {diagnoses_sql_query_result_str}"
    )
    task = (
        f"The formula for <column>{config.target_column_name}</column> in "
        f"<table>{config.target_table_name}</table> is wrong (accuracy: {accuracy}%).\n"
        f"It uses {current} rows. Diagnose the root cause and provide a corrected formula."
    )
    rules = [
        "Compare actual_value vs computed_value in the diagnoses results to identify the error type.",
        "Focus on grouping and chaining logic — wrong condition, off-by-one, or wrong column are common causes.",
        "Propose a corrected formula and list the required column names.",
        "Be concise about the cause of error.",
    ]
    payload = {
        "is_catched": " 'yes' if you found the cause, 'no' otherwise ",
        "cause_of_error": " brief explanation of the root cause ",
        "corrected_formula": " the corrected textual formula ",
        "columns": ["X", "Y"],
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL debugger diagnosing incorrect chaining-table formula.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_corrected_sql_for_chaining(
    target_table_description: str,
    data_for_sharing_with_LLM_str: str,
    corrected_formula: str,
    formula_based_on_data_sharing: str,
    cause_of_error: str,
    chaining_columns_str: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list,
) -> str:
    from src.core.config import config

    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = (
            f"SELECT actual_value (= `{config.target_column_name}`) and computed_value."
        )
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{config.target_column_name}`), and actual_value (= `{config.target_column_name}`)."
        )

    context = (
        f"Table description of <table>{config.target_table_name}</table>:\n"
        f"{target_table_description}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}\n\n"
        f"Correct formula: [[[CORRECT START]]] {corrected_formula} [[[CORRECT END]]]\n"
        f"Previous incorrect formula: [[[INCORRECT START]]] {formula_based_on_data_sharing} [[[INCORRECT END]]]\n"
        f"Reason for incorrectness: {cause_of_error}"
    )
    task = (
        f"Generate a corrected MySQL computation SQL query for <column>{config.target_column_name}</column> "
        f"in chaining table <table>{config.target_table_name}</table> using the corrected formula.\n"
        f"The query verifies the formula — it must not modify or fill data.\n"
        f"{select_desc}\n"
        f"Alias <table>{config.target_table_name}</table> as `target_table` in the outer FROM clause."
    )
    rules = [
        "Use a nested subquery (NOT self-join) to access the previous/next row — it goes in the outer SELECT and returns ONE value aliased `computed_value`.",
        f"Exclude rows that cannot be computed (first rows if using previous row; last rows if using next row) via WHERE.",
        f"Do NOT read `{config.target_column_name}` from `{config.target_table_name}` anywhere in the SQL — not via `target_table`, not via any other alias of `{config.target_table_name}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{config.target_column_name}`), MIN(`{config.target_column_name}`), SUM(`{config.target_column_name}`) applied to `{config.target_table_name}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only.",
        "Rounding is not required.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        "MySQL does not allow nested aggregate functions — use subqueries.",
        f"Pay attention to chaining criteria ({chaining_columns_str}).",
        "Do not repeat the mistake from the incorrect formula.",
        "Return only the executable SQL query — no explanations.",
    ]
    return _build_skill_prompt(
        role="SQL developer correcting a chaining-table computation formula.",
        context=context,
        task=task,
        rules=rules,
    )


# === END OF PART 1 ===


# ============================================================================
# HIERARCHICAL TABLE PROMPTS
# ============================================================================

def prompt_identify_hierarchical_table_structure(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)

    # Build PK description for context
    if len(names_of_pk_columns_of_target_table) == 1:
        pk_desc = f"The row identifier of <table>{config.target_table_name}</table> is <column>{names_of_pk_columns_of_target_table[0]}</column>."
    elif len(names_of_pk_columns_of_target_table) > 1:
        pk_desc = f"The row identifier of <table>{config.target_table_name}</table> is the composite key {names_of_pk_columns_of_target_table}."
    else:
        pk_desc = ""

    context = (
        f"{initial_prompt_str}\n\n"
        f"{target_table_description}\n\n"
        f"<table>{config.target_table_name}</table> is hierarchical: each row stores the identifier of its parent row. "
        f"{pk_desc}\n\n"
        "[Example 1] Table T with columns (A, B, C, ...): A is the identifier; C refers to the parent's A. "
        "R1 is parent of R2, R3; R3 is parent of R4.\n"
        "[Example 2] Table T with composite key (A, B): C refers to parent A; D refers to parent B."
    )

    if len(names_of_pk_columns_of_target_table) == 0:
        task_suffix = "Provide both the parent-reference column and the parent-referencing column."
    elif len(names_of_pk_columns_of_target_table) == 1:
        task_suffix = (
            f"<table>{config.target_table_name}</table> has one identifier "
            f"(<column>{names_of_pk_columns_of_target_table[0]}</column>). "
            "Provide the parent-referencing column."
        )
    else:
        task_suffix = (
            f"<table>{config.target_table_name}</table> has a composite key. "
            "Provide the parent-referencing column for each key part."
        )

    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is derived from other rows using a parent-child hierarchy. "
        f"Identify parent-reference column pairs (parent_col, referencing_col). {task_suffix}"
    )
    rules = [
        "Look for self-referencing FK columns in the schema.",
        "Verify: a PK column is also referenced as a FK in the same table.",
        "If no hierarchical structure exists, return empty lists.",
    ]
    payload = {"parent_reference_columns": [["parent_col", "referencing_col"]]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying hierarchical (self-referencing) table structures.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_hierarchical_table_candidate_formula(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str,
) -> str:
    from src.core.config import config

    if len(names_of_pk_columns_of_target_table) == 1:
        parent_ref_info = (
            f"<table>{config.target_table_name}</table> has one identifier. "
            f"Parent-reference column: <column>{parent_reference_columns_list[0][0]}</column>; "
            f"parent-referencing column: {parent_reference_columns_list[0][1]}."
        )
    else:
        pairs = " ".join(
            f"<column>{pr[0]}</column> → {pr[1]};"
            for pr in parent_reference_columns_list
        )
        parent_ref_info = (
            f"<table>{config.target_table_name}</table> has a composite key. "
            f"Parent-reference relationships: {pairs}"
        )

    context = (
        f"{parent_ref_info}\n\n"
        f"Table description:\n{target_table_description}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}"
    )
    task = (
        f"Find the formula to compute <column>{config.target_column_name}</column> "
        f"in hierarchical table <table>{config.target_table_name}</table> "
        "using the parent-child relationship."
    )
    rules = [
        "Use terms `parent_row`, `child_row`, `children_rows` in the formula.",
        "Validate the formula against the provided sample rows.",
        "Provide multiple candidates with confidence scores summing to 100 if uncertain.",
    ]
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL formula analyst identifying computed column formulas in hierarchical tables.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_sql_for_hierarchical_table(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str,
    formula_based_on_data_sharing: str,
    number_of_pks_in_target_table: int,
) -> str:
    from src.core.config import config

    if len(names_of_pk_columns_of_target_table) == 1:
        parent_ref_info = (
            f"Parent-reference column: <column>{parent_reference_columns_list[0][0]}</column>; "
            f"parent-referencing column: {parent_reference_columns_list[0][1]}."
        )
    else:
        pairs = " ".join(
            f"<column>{pr[0]}</column> → {pr[1]};"
            for pr in parent_reference_columns_list
        )
        parent_ref_info = f"Parent-reference relationships: {pairs}"

    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = "SELECT computed_value and actual_value."
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{config.target_column_name}`), and actual_value (= `{config.target_column_name}`)."
        )

    context = (
        f"Table description of <table>{config.target_table_name}</table>:\n"
        f"{target_table_description}\n\n"
        f"{parent_ref_info}\n\n"
        f"Sample rows: {data_for_sharing_with_LLM_str}\n\n"
        f"Formula: [[[FORMULA START]]] {formula_based_on_data_sharing} [[[FORMULA END]]]"
    )
    task = (
        f"Generate a MySQL computation SQL query for <column>{config.target_column_name}</column> "
        f"in hierarchical table <table>{config.target_table_name}</table>. "
        "The query verifies the formula — it must not modify or fill data.\n"
        f"{select_desc}\n"
        "Use a self-join or recursive CTE to access parent/child rows."
    )
    rules = [
        "Use self-join aliasing (e.g., parent AS p, child AS c) or WITH RECURSIVE for recursive CTEs.",
        "Return only executable MySQL — no explanations.",
        "Handle composite key structure correctly in JOIN conditions.",
    ]
    return _build_skill_prompt(
        role="SQL developer generating self-join or recursive CTE queries for hierarchical tables.",
        context=context,
        task=task,
        rules=rules,
    )


# ============================================================================
# ROW-SCOPE PROMPTS
# ============================================================================

def prompt_find_row_scope_formulas(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is a row-scope computed value. Find formulas that use ONLY columns in the same row.\n"
        "Provide multiple candidates with confidence scores summing to 100 if uncertain."
    )
    rules = [
        "No aggregation functions (SUM, COUNT, AVG, etc.).",
        "No joins — same-row columns only.",
        "Consider arithmetic, string, date, and conditional (CASE) patterns.",
    ]
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying row-scope computed column formulas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_sql_for_row_scope(
    target_table_description: str,
    formula: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = "SELECT computed_value and actual_value."
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{config.target_column_name}`), and actual_value (= `{config.target_column_name}`)."
        )

    context = (
        f"{initial_prompt_str}\n\n"
        f"Table description:\n{target_table_description}\n\n"
        f"Formula: [[[START]]] {formula} [[[END]]]"
    )
    task = (
        f"Generate a row-scope MySQL computation SQL query for <column>{config.target_column_name}</column> "
        f"in <table>{config.target_table_name}</table> using the formula above.\n"
        f"{select_desc}"
    )
    rules = [
        "No aggregation across rows — same-row arithmetic only.",
        "No joins.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        "Return only the executable SQL query — no explanations.",
    ]
    return _build_skill_prompt(
        role="SQL developer generating row-scope computation queries.",
        context=context,
        task=task,
        rules=rules,
    )


# ============================================================================
# CROSS-TABLE PROMPTS
# ============================================================================

def prompt_is_count_or_exist(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"Determine if <column>{config.target_column_name}</column> in "
        f"<table>{config.target_table_name}</table> is derived from counting rows or checking "
        "existence in other tables.\n"
        "Examples: `number_of_passengers` = COUNT of rows in `tickets`; "
        "`is_canceled` = EXISTS in `canceled_trips`."
    )
    rules = [
        "Check if the column's data type and name suggest a count or boolean.",
        "Look for FK-linked tables whose row counts could logically produce the column's values.",
        "Answer `yes` ONLY if the column is clearly an integer count or a boolean existence flag.",
        "Answer `no` if the column is a decimal/float, a weighted average, a ratio, or any continuous numeric value — these are NOT count/exist patterns.",
        "Return `yes` or `no`.",
    ]
    payload = {"is_count_or_exist": "yes or no"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying COUNT or EXISTS patterns in computed columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_find_count_exists_formulas(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is computed via COUNT or EXISTS subqueries against other tables. "
        f"Generate up to {config.max_candidate_formulas_count_exists} candidate SQL formulas.\n"
        "Use COUNT(*), SUM(CASE WHEN EXISTS ...), or IF EXISTS patterns. "
        "Use PK-FK relationships for join conditions. "
        "Include: textual_formula, used_tables, used_columns, confidence_score, computation_sql_query."
    )
    rules = [
        "Wrap aggregation inside subqueries — never directly in the outer SELECT without GROUP BY.",
        "Confidence scores must sum to 100.",
        "Return only valid MySQL syntax.",
    ]
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": "...",
                "used_tables": [],
                "used_columns": [],
                "confidence_score": 100,
                "computation_sql_query": "...",
            }
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL developer generating COUNT/EXISTS cross-table computation formulas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_identify_candidate_tables_for_count(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"Identify which tables in the database are best candidates to COUNT or check EXISTence "
        f"for computing <column>{config.target_column_name}</column> in "
        f"<table>{config.target_table_name}</table>.\n"
        f"Example: if <column>{config.target_column_name}</column> is `number_of_orders`, "
        "look for an `orders` or `order_items` table."
    )
    rules = [
        "Prioritize tables with FK relationships pointing to or from the target table.",
        "Consider table names and column meanings relative to the target column's semantics.",
        "Provide a brief reason for each candidate.",
    ]
    payload = {"candidate_tables": [{"table_name": "...", "reason": "..."}]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst finding tables for COUNT/EXISTS formula discovery.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_across_table_sql(
    target_table_description: str,
    formula: str,
    number_of_pks_in_target_table: int,
    names_of_pk_columns_of_target_table: list,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    pk_cols_str = str(names_of_pk_columns_of_target_table)
    if number_of_pks_in_target_table == 0:
        select_desc = "SELECT computed_value and actual_value."
    else:
        select_desc = (
            f"SELECT the {number_of_pks_in_target_table} PK column(s) {pk_cols_str}, "
            f"computed_value (predicted `{config.target_column_name}`), and actual_value (= `{config.target_column_name}`)."
        )

    context = (
        f"{initial_prompt_str}\n\n"
        f"Table description:\n{target_table_description}\n\n"
        f"Formula: [[[START]]] {formula} [[[END]]]"
    )
    task = (
        f"Generate a cross-table MySQL computation SQL query for <column>{config.target_column_name}</column> "
        f"in <table>{config.target_table_name}</table> using the formula above.\n"
        f"{select_desc}"
    )
    rules = [
        "Build JOIN chains using PK-FK relationships.",
        "Use subqueries to avoid nested aggregates — MySQL does not allow aggregate-inside-aggregate.",
        "Use GROUP BY when aggregating across joined rows.",
        "Preserve all rows in the outer table (use LEFT JOIN where appropriate).",
        "Return only the executable SQL query — no explanations.",
    ]
    return _build_skill_prompt(
        role="SQL developer generating cross-table JOIN computation queries.",
        context=context,
        task=task,
        rules=rules,
    )


# ============================================================================
# PATTERN CLASSIFICATION PROMPTS
# ============================================================================

def prompt_find_common_formula_pattern(
    target_table_description: str,
    formula_list: list,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = (
        f"{initial_prompt_str}\n\n"
        f"Table description:\n{target_table_description}\n\n"
        f"Candidate formulas: {formula_list}"
    )
    task = (
        f"Find the most common semantic formula pattern across the candidate list for "
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table>."
    )
    rules = [
        "Group semantically equivalent formulas together.",
        "Return the abstract pattern of the largest group.",
        "Express the pattern concisely — not a specific SQL expression.",
    ]
    payload = {"formula_pattern": "the common formula pattern"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Formula analyst extracting recurring patterns from multiple candidates.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_extract_semantic_formula(
    target_table_description: str,
    formula_list: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = (
        f"{initial_prompt_str}\n\n"
        f"Table description:\n{target_table_description}\n\n"
        f"Candidate formulas: {formula_list}"
    )
    task = (
        f"Extract the dominant semantic formula for <column>{config.target_column_name}</column> "
        f"in <table>{config.target_table_name}</table> from the candidate list."
    )
    rules = [
        "Group semantically equivalent formulas.",
        "Identify the group with the highest count.",
        "Return the canonical (most representative) form of that group.",
    ]
    payload = {"semantic_formula": "the most frequent semantic formula"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Formula analyst distilling the dominant semantic formula from a candidate list.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_classify_table_scope_type(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"Classify the computation scope of <column>{config.target_column_name}</column> "
        f"in <table>{config.target_table_name}</table>.\n"
        "Options:\n"
        "- `row-scope`: computed using only columns in the same row.\n"
        "- `single-table-scope`: requires other rows in the same table.\n"
        "- `cross-table-scope`: requires rows from other tables."
    )
    rules = [
        "Check row-scope first (no aggregation, no joins).",
        "Check single-table-scope if aggregation over same-table rows is needed.",
        "Check cross-table-scope if data from other tables is required.",
        "Return exactly one of the three scope strings.",
    ]
    payload = {"scope_type": "row-scope or single-table-scope or cross-table-scope"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst classifying the computation scope of a derived column.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# SINGLE-TABLE SCOPE PROMPTS
# ============================================================================

def prompt_is_single_table_computed_value(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"Determine if <column>{config.target_column_name}</column> in "
        f"<table>{config.target_table_name}</table> can be computed using only data within the same table "
        "(no cross-table joins).\n"
        "Examples of single-table patterns: cumulative sums, running totals, parent values in hierarchies, "
        "previous/next row values."
    )
    rules = [
        "Check for same-table patterns: cumulative, hierarchical, chaining.",
        "If any cross-table data is required, return `no`.",
        "Return `yes` or `no`.",
    ]
    payload = {"is_computed": "yes or no"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst determining single-table computation scope.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_generate_single_table_formula(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is computed from other rows in the same table. Generate candidate formulas.\n"
        "Consider: is the table hierarchical, chained, or cumulative/rolling?\n"
        "Use terms: `previous_row`, `next_row`, `parent_row`, `children_rows`, `all_rows`."
    )
    rules = [
        "Only use data from within the same table — no cross-table joins.",
        "Provide multiple candidates with confidence scores summing to 100 if uncertain.",
        "Label each formula with the row-access pattern it uses.",
    ]
    payload = {"candidate_formulas": [{"formula": "...", "confidence_score": 100}]}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL developer generating single-table aggregation formulas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_classify_as_table_scope(
    target_table_description: str,
) -> str:
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_table_description
    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is computed from rows in the same table. Classify the computation type.\n"
        "Options:\n"
        "- `chaining`: each row has a previous/next row in a sequence.\n"
        "- `hierarchical`: tree structure with parent/child self-references.\n"
        "- `other`: cumulative, rolling window, or general aggregation pattern."
    )
    rules = [
        "Check for ordered row sequences first (chaining).",
        "Check for self-referencing FK (hierarchical).",
        "Default to `other` for cumulative or rolling window patterns.",
        "Return exactly one of: `chaining`, `hierarchical`, or `other`.",
    ]
    payload = {"table_scope_type": "chaining or hierarchical or other"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst classifying single-table computation types.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# === END OF PART 2 ===


# ============================================================================
# PART 3 — SMART FORMULA FUNCTIONS
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
    chaining_columns: list,
) -> str:
    """Diagnose an incorrect chaining formula and request a corrected one."""
    grouping_info = (
        f"Grouping columns in <table>{target_tbl}</table>: {grouping_columns}. "
        if len(grouping_columns) > 1
        else f"Grouping column in <table>{target_tbl}</table>: {grouping_columns[0]}. "
    )
    chaining_info = (
        f"Chaining columns: {chaining_columns}. "
        if len(chaining_columns) > 1
        else f"Chaining column: {chaining_columns[0]}. "
    )
    context = (
        f"Table description: {target_tbl_description}\n\n"
        f"<table>{target_tbl}</table> is a **chaining table** — each row has a previous row (except the first in the chain) "
        "and a next row (except the last). Chains are split into groups.\n"
        "[Example 1] Table (A, B, C …): R1(0,'f',1), R2(0,'f',2), R3(0,'f',3), R4(5,'x',1), R5(5,'x',2), R6(5,'x',3). "
        "A and B are grouping columns; C is the chaining column.\n"
        "[Example 2] Table (A, B, C …): R1(1,1,5), R2(1,6,12), R3(1,13,15), R4(2,0,15), R5(2,16,22), R6(2,23,25). "
        "A is the grouping column; B and C are chaining columns.\n"
        f"{grouping_info}{chaining_info}"
        f"Sample rows of `{target_tbl}`: {data_sharing_str}"
    )
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is computed from {current} rows of the same table.\n"
        f"The formula below has {accuracy}% accuracy — it is incorrect.\n"
        f"Incorrect formula: {formula}\n"
        f"Diagnosis query results (actual_value vs computed_value): {diagnoses_result_str}\n"
        "Identify the root cause and provide a corrected formula. "
        f"Also list the columns needed to compute <column>{target_col}</column>."
    )
    rules = [
        "Compare actual_value vs computed_value to spot the error pattern.",
        "Cross-reference with sample rows to understand grouping/chaining in practice.",
        "Find the specific wrong assumption (wrong grouping condition, off-by-one, wrong column, etc.).",
        "The sample rows are randomly selected — they do not form chains.",
        "Propose a minimal corrected formula that fixes the mismatch.",
        "actual_value is always correct; computed_value is wrong.",
    ]
    payload = {
        "is_catched": " 'yes' if you find out the cause of the error and 'no' otherwise ",
        "cause_of_error": " explain the root cause of the error briefly ",
        "corrected_formula": " write the new correct formula here ",
        "columns": ["X", "Y"],
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL debugger diagnosing chaining-table formula mismatches.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


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
    pk_columns_names: list,
) -> str:
    """Generate corrected SQL for a chaining table after diagnosis."""
    pk_clause = (
        f"SELECT computed_value and actual_value (= `{target_col}`)."
        if number_of_pks == 0
        else (
            f"SELECT {number_of_pks} PK column(s) {pk_columns_names}, "
            f"computed_value, and actual_value (= `{target_col}`)."
        )
    )
    context = (
        f"Table description: {target_tbl_description}\n\n"
        f"<table>{target_tbl}</table> is a chaining table — each row has a previous/next row (except first/last). "
        "Chains are split into groups.\n"
        "[Example 1] Table (A, B, C …): R1(0,'f',1), R2(0,'f',2), R3(0,'f',3), R4(5,'x',1), R5(5,'x',2), R6(5,'x',3). "
        "A and B are grouping columns; C is the chaining column.\n"
        "[Example 2] Table (A, B, C …): R1(1,1,5), R2(1,6,12), R3(1,13,15), R4(2,0,15), R5(2,16,22), R6(2,23,25). "
        "A is the grouping column; B and C are chaining columns. "
        "current_row.B = (previous_row.C + 1); current_row.C = (next_row.B - 1).\n"
        f"Sample rows of `{target_tbl}`: {data_sharing_str}\n"
        f"Corrected formula: {corrected_formula}\n"
        f"Previously incorrect formula: {incorrect_formula}\n"
        f"Reason for incorrectness: {cause_of_error}"
    )
    task = (
        f"Generate a corrected SQL query that computes <column>{target_col}</column> in <table>{target_tbl}</table> "
        "using previous or next rows (chaining).\n"
        "The query is for verification only — do not modify or fill data.\n"
        f"{pk_clause}\n"
        f"Alias <table>{target_tbl}</table> as `target_table` in the outer FROM clause.\n"
        "Avoid repeating the same mistake as the incorrect formula."
    )
    rules = [
        f"Use a nested subquery (not self-join) inside the outer SELECT — return exactly one value aliased as computed_value.",
        "Rounding is not required.",
        "Only use columns that exist in the schema.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        f"Exclude uncomputable rows via WHERE (first rows of chains if using previous_row; last rows if using next_row).",
        f"Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias of `{target_tbl}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only.",
        f"Pay attention to the chaining criteria ({chaining_columns_str}) across rows.",
        "MySQL does not allow nested aggregate functions directly.",
        "Output only the executable SQL query — no explanation.",
    ]
    return _build_skill_prompt(
        role="SQL developer correcting a chaining-table computation query.",
        context=context,
        task=task,
        rules=rules,
    )


def prompt_is_count_or_exist_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
) -> str:
    """Determine whether target_col is derived from counting/existence in other tables."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> has missing values.\n"
        "Determine whether it is derived from **counting rows** or **checking existence** in other tables.\n"
        "Examples:\n"
        "- `number_of_passengers` in `trip` → COUNT rows in `tickets` for that trip → yes.\n"
        "- `is_canceled` in `trip` → EXISTS row in `canceled_trips` → yes.\n"
        f"Return 'yes' if <column>{target_col}</column> fits this pattern, 'no' otherwise."
    )
    rules = [
        "Check if the column's name/type suggests a count or boolean.",
        "Use PK-FK relationships to find tables that could be counted or checked.",
        "Respond strictly with the JSON below.",
    ]
    payload = {"is_count_or_exist": "yes or no"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying COUNT or EXISTS patterns in computed columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_count_or_exist_with_data_sharing(
    target_col: str,
    target_tbl: str,
    given_table_name: str,
    target_tbl_description: str,
    data_sharing_str: str,
    number_of_pks: int,
    pk_columns_names: list,
) -> str:
    """Refine a COUNT/EXISTS formula using data samples from another table."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    pk_clause = (
        f"SELECT computed_value and actual_value (= `{target_col}`)."
        if number_of_pks == 0
        else (
            f"SELECT {number_of_pks} PK column(s) {pk_columns_names}, "
            f"computed_value, and actual_value (= `{target_col}`)."
        )
    )
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is derived by counting rows in "
        f"<table>{given_table_name}</table>. A simple COUNT(*) is inaccurate — conditions are needed.\n"
        f"Sample data points: {data_sharing_str}\n"
        f"Generate a textual formula and a computation SQL query that verifies it.\n"
        f"{pk_clause}\n"
        f"Alias <table>{target_tbl}</table> as `target_table` in the outer FROM clause.\n"
        "Provide multiple candidates with confidence scores summing to 100 if uncertain."
    )
    rules = [
        "Use LEFT JOIN + COUNT aggregation in the SQL.",
        "Use LIKE for string comparisons — never FIND_IN_SET or REPLACE.",
        "Query is for verification only — do not modify data.",
        "Ensure valid MySQL syntax.",
        "Output only the JSON below.",
    ]
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " most potential formula ",
                "computation_sql_query": f" SQL to compute {target_col} ",
                "confidence_score": " 0-100 ",
            },
            {
                "textual_formula": " alternative formula, if any ",
                "computation_sql_query": f" SQL to compute {target_col} ",
                "confidence_score": " 0-100 ",
            },
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL developer generating COUNT/EXISTS cross-table formulas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_identify_candidate_table_for_count(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
) -> str:
    """Identify which table to use for a COUNT/EXISTS formula."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is derived from counting rows in another table.\n"
        "Identify the best candidate table(s) for this COUNT formula.\n"
        "Provide confidence scores summing to 100. Don't over-generate — if one table is obvious, return just that."
    )
    rules = [
        "Use FK relationships pointing to/from the target table.",
        "Consider relationship cardinality and table semantics.",
        "Respond strictly with the JSON below.",
    ]
    payload = {
        "candidates": [
            {"table_name": " most likely candidate table ", "confidence_score": " 0-100 "},
            {"table_name": " other candidate table, if any ", "confidence_score": " 0-100 "},
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying COUNT candidate tables.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_across_tables_formula_with_data(
    target_col: str,
    target_tbl: str,
    other_used_tables_names_str: str,
    used_tables: list,
    data_sharing_str: str,
    target_tbl_description: str,
    number_of_pks: int,
    pk_columns_names: list,
) -> str:
    """Generate cross-table formula and SQL using shared data samples."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    pk_clause = (
        f"SELECT computed_value and actual_value (= `{target_col}`)."
        if number_of_pks == 0
        else (
            f"SELECT {number_of_pks} PK column(s) {pk_columns_names}, "
            f"computed_value, and actual_value (= `{target_col}`)."
        )
    )
    tables_clause = (
        f"<column>{target_col}</column> can be derived from <table>{other_used_tables_names_str}</table>."
        if len(used_tables) == 1
        else f"<column>{target_col}</column> can be derived from some of the following tables: {other_used_tables_names_str}."
    )
    multi_table_note = (
        f"Some of the listed tables may be useless — use the data points to identify which ones matter.\n"
        if len(used_tables) > 1
        else ""
    )
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"Single-table formulas for <column>{target_col}</column> in <table>{target_tbl}</table> are insufficient. "
        f"The formula must use other tables.\n"
        f"{tables_clause}\n"
        f"Data samples: {data_sharing_str}\n"
        f"{multi_table_note}"
        f"Generate a textual formula and a computation SQL query.\n"
        f"{pk_clause}\n"
        f"Alias <table>{target_tbl}</table> as `target_table` in the outer FROM clause.\n"
        "Provide multiple candidates with confidence scores summing to 100."
    )
    rules = [
        "Do not aggregate on left-join values directly — put aggregation inside the subquery.",
        "Wrong: SELECT id, SUM(i.amount) FROM account a LEFT JOIN (SELECT account_id, amount FROM income) AS i ...",
        "Correct: SELECT id, total.computed_value FROM account a LEFT JOIN (SELECT account_id, SUM(amount) AS computed_value FROM income GROUP BY account_id) AS total ...",
        "Always alias the computed column as `computed_value` inside the subquery, then reference it as `subquery_alias.computed_value AS computed_value` in the outer SELECT.",
        "Rounding is not required.",
        f"Only use columns from the schema. Only use tables: {other_used_tables_names_str}.",
        "Cast UNSIGNED columns to SIGNED before arithmetic that may produce negatives.",
        f"Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias or direct table reference to `{target_tbl}`, and not inside any subquery, CTE, or nested SELECT. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The computed_value must be derived entirely from columns of other tables ({other_used_tables_names_str}).",
        f"Do NOT create a self-join. `{target_tbl}` must appear EXACTLY ONCE in the entire SQL (as `target_table` in the outer FROM clause). Do NOT reference `{target_tbl}` inside a derived table (subquery) used in a JOIN — even if the subquery is aliased differently, it is still a self-join if it reads from `{target_tbl}`. The JOIN must connect `target_table` to real tables from: {other_used_tables_names_str}. A query that only reads from `{target_tbl}` — even via window functions, self-aggregation, or derived subqueries — is forbidden.",
        "Do NOT propose data-fitting formulas. Do not hardcode specific data instances — person names, IDs, enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. The formula must follow structural schema logic, not memorized training data. Example of forbidden: CASE WHEN FirstName IN ('Ken', 'Michael', ...) THEN 'M'.",
        "Ensure valid MySQL syntax. Output only the JSON below.",
    ]
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " most potential formula ",
                "computation_sql_query": f" SQL to compute {target_col} ",
                "confidence_score": " 0-100 ",
            },
            {
                "textual_formula": " alternative formula, if any ",
                "computation_sql_query": f" SQL to compute {target_col} ",
                "confidence_score": " 0-100 ",
            },
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="SQL developer generating cross-table JOIN-based formulas for derived columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_across_tables_candidate_formulas(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
) -> str:
    """Discover cross-table candidate formulas (schema only, no data samples)."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"Single-table formulas for <column>{target_col}</column> in <table>{target_tbl}</table> are insufficient. "
        "Discover formulas that use other tables via joins.\n"
        f"Up to {config.max_candidate_formulas_across_tables} candidates. Multi-hop joins allowed (2-hop, 3-hop+).\n"
        "For each formula list the tables and columns directly used (not intermediate join-only tables).\n"
        "Example: if formula is `IF T1.A IS True THEN T.C = SUM(T2.X) ELSE T.C = SUM(T2.X - T2.Y)`, "
        "then used_tables = [T1, T2], used_columns = [T1.A, T2.X, T2.Y].\n"
        "Assign confidence scores summing to 100."
    )
    rules = [
        "Do not provide single-table formulas — only cross-table.",
        f"CRITICAL: Every candidate's used_tables MUST include at least one table other than `{target_tbl}`. Never return a formula where used_tables contains only `{target_tbl}` — self-joins and self-aggregations on the target table are strictly forbidden.",
        f"Also forbidden: any formula that computes `{target_col}` by reading `{target_col}` itself from `{target_tbl}` — e.g., MAX(`{target_tbl}`.`{target_col}`) GROUP BY pk — this is circular and must not be returned.",
        "Do NOT propose data-fitting formulas. Do not hardcode specific data instances — person names, IDs, enumerated row-level values — in IN (...) lists or CASE WHEN conditions to derive the computed value. Formulas must follow structural schema logic, not memorized training data.",
        "Explore PK-FK paths for multi-hop joins.",
        "List only formula-contributing tables/columns, not join intermediates.",
    ]
    payload = {
        "candidate_formulas": [
            {
                "textual_formula": " most potential cross-table formula ",
                "used_tables": " tables used in the formula (not join-only intermediates) ",
                "used_columns": " columns used in the formula (not joining columns) ",
                "confidence_score": " 0-100 ",
            },
            {
                "textual_formula": " alternative formula, if any ",
                "used_tables": " tables used ",
                "used_columns": " columns used ",
                "confidence_score": " 0-100 ",
            },
        ]
    }
    payload_example_1 = {
        "candidate_formulas": [
            {
                "textual_formula": " T.C = IF T1.A is True then T.C = SUM(T2.X) ELSE T.C = SUM(T2.X - T2.Y) ",
                "used_tables": ["T1", "T2"],
                "used_columns": ["T1.A", "T2.X", "T2.Y"],
                "confidence_score": "70",
            }
        ]
    }
    payload_example_2 = {"candidate_formulas": "NaN"}
    output = (
        "Return STRICTLY in JSON. No extra commentary.\n"
        "Format: " + json.dumps(payload, ensure_ascii=False) + "\n"
        "Example (formula found): " + json.dumps(payload_example_1, ensure_ascii=False) + "\n"
        "Example (no formula): " + json.dumps(payload_example_2, ensure_ascii=False) + "\n"
        "Provide the JSON."
    )
    return _build_skill_prompt(
        role="Database analyst discovering cross-table computed column formulas.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_common_formula_from_list(
    target_col: str,
    target_tbl: str,
    formula_list: list,
    target_tbl_description: str,
) -> str:
    """Return the most frequent semantic formula from a candidate list."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> has multiple candidate formulas. "
        "Some are semantically equivalent.\n"
        f"Formula list: {formula_list}\n"
        "Return the most frequent semantic formula. No explanation."
    )
    rules = [
        "Group semantically equivalent formulas.",
        "Return the canonical form of the largest group.",
        "Output only the formula text — no commentary.",
    ]
    return _build_skill_prompt(
        role="Formula analyst extracting the dominant semantic formula from a list.",
        context=context,
        task=task,
        rules=rules,
        output="Respond with only the formula text.",
    )


def prompt_classify_table_type_chaining_or_hierarchical(
    target_col: str,
    target_tbl: str,
    common_formula: str,
    target_tbl_description: str,
) -> str:
    """Classify target_tbl as 'chaining table' or 'hierarchical table'."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is computed from other rows in the same table.\n"
        f"Potential formula: {common_formula}\n"
        "Classify <table>{target_tbl}</table> as exactly one of:\n"
        "- **chaining table**: each row has a previous/next row in a sequence.\n"
        "- **hierarchical table**: tree structure with parent/child self-references."
    )
    rules = [
        "Check for sequence/order columns → suggests chaining.",
        "Check for self-referencing FK (parent column) → suggests hierarchical.",
        "Return exactly 'chaining table' or 'hierarchical table'.",
    ]
    payload = {"table_type": "chaining table or hierarchical table"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst classifying single-table computation types.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_row_scope_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list,
) -> str:
    """Discover row-scope formulas using sample rows."""
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is computed from other columns in the **same row**.\n"
        f"{len(result)} sample rows — columns: ({columns_names_str}), values: {result}\n"
        "Find all possible row-scope formulas."
    )
    rules = [
        f"<column>{target_col}</column> must appear on the left side only — never in the right-side expression.",
        "No aggregation and no cross-row access.",
        "Test each candidate against multiple rows before including it.",
    ]
    payload = {
        "formula_1": {"formula": f"{target_col} = X * 100 / square(Y) ...", "columns": ["X", "Y"]},
        "formula_2": {"formula": f"{target_col} = A - (2 * B) ...", "columns": ["A", "B"]},
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst identifying row-scope computed column formulas.",
        task=task,
        rules=rules,
        output=output,
    )


def prompt_row_scope_sql_generation(
    target_col: str,
    target_tbl: str,
    formula: str,
    columns_to_compute_str: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str,
    number_of_pks: int,
    pk_columns_names: list,
) -> str:
    """Generate a row-scope SQL query from a textual formula."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    pk_clause = (
        f"SELECT computed_value and actual_value (= `{target_col}`)."
        if number_of_pks == 0
        else (
            f"SELECT {number_of_pks} PK column(s) {pk_columns_names}, "
            f"computed_value, and actual_value (= `{target_col}`)."
        )
    )
    context = (
        initial_prompt_str + "\n\n" + target_tbl_description
        + f"\nSample rows — columns: ({columns_names_str}), values: {result}"
    )
    task = (
        f"Formula: {formula}\n"
        f"Generate a SQL query that computes <column>{target_col}</column> in <table>{target_tbl}</table> "
        f"from {columns_to_compute_str} using the formula above.\n"
        "Query is for verification only — do not modify data.\n"
        f"{pk_clause}\n"
        f"Alias <table>{target_tbl}</table> as `target_table`."
    )
    rules = [
        f"No joins, no subqueries, no aggregation — pure same-row arithmetic on `{target_tbl}`.",
        "Rounding is not required.",
        "Only use columns that exist in the schema.",
        "Cast UNSIGNED to SIGNED before arithmetic that may produce negatives.",
        f"Do NOT read `{target_col}` from `{target_tbl}` anywhere in the SQL — not via `target_table`, not via any other alias of `{target_tbl}`, not inside subqueries or CTEs. This includes aggregate functions such as MAX(`{target_col}`), MIN(`{target_col}`), SUM(`{target_col}`) applied to `{target_tbl}` data — wrapping the target column in an aggregate does NOT make it valid. The formula must derive the value from other columns only.",
        "Ensure valid MySQL syntax. Output only the executable SQL query.",
    ]
    return _build_skill_prompt(
        role="SQL developer generating row-scope SQL expressions for computed columns.",
        context=context,
        task=task,
        rules=rules,
    )


def prompt_single_table_formula_discovery(
    target_col: str,
    target_tbl: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str,
) -> str:
    """Discover a single-table formula (may or may not need cross-row access)."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    sample_rows_note = (
        f"\n{len(result)} sample rows — columns: ({columns_names_str}), values: {result}. "
        f"Rows are randomly selected (table is incomplete). "
        f"Use them to determine if <column>{target_col}</column> needs same-row columns only or other rows."
        if len(result) > 0
        else ""
    )
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"<column>{target_col}</column> in <table>{target_tbl}</table> is computed from within the same table.\n"
        f"Provide a formula (up to 200 characters) to compute it from other rows/columns in <table>{target_tbl}</table>.\n"
        f"Clarify whether the formula needs cross-row access.{sample_rows_note}\n"
        "If no formula can be found, respond with 'None'."
    )
    rules = [
        "The formula must be realistic and schema-compatible.",
        "Output only the formula text or 'None' — no explanation.",
    ]
    return _build_skill_prompt(
        role="Database analyst discovering single-table computed column formulas.",
        context=context,
        task=task,
        rules=rules,
        output="Respond with only the formula text or 'None'.",
    )


def prompt_table_scope_type_check(
    target_col: str,
    target_tbl: str,
    formula: str,
    columns_names_str: str,
    result: list,
    target_tbl_description: str,
) -> str:
    """Determine if the formula is table-scope (uses other rows) or row-scope (same row only)."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    sample_rows_note = (
        f"\nSample rows — columns: ({columns_names_str}), values: {result}."
        if len(result) > 0
        else ""
    )
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"Formula: {formula}\n"
        f"Determine if <column>{target_col}</column> in <table>{target_tbl}</table> is:\n"
        "- **table-scope**: computed from other rows (e.g., R2.x = f(R1.x))\n"
        "- **row-scope**: computed from same-row columns only (e.g., R2.x = f(R2.y))\n"
        f"{sample_rows_note}\n"
        "Return 'table-scope' if cross-row access is needed, 'None' otherwise."
    )
    rules = [
        "Check if the formula references values from other rows.",
        "Verify against sample rows if provided.",
        "Return exactly 'table-scope' or 'None'.",
    ]
    payload = {"scope_type": "table-scope or None"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst classifying row-scope vs table-scope computed columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_is_single_table_computed_value_smartly(
    target_col: str,
    target_tbl: str,
    target_tbl_description: str,
) -> str:
    """Determine whether target_col can be computed within the same table (no joins)."""
    initial_prompt_str = get_initial_prompt_str(config.strategy)
    context = initial_prompt_str + "\n\n" + target_tbl_description
    task = (
        f"Can <column>{target_col}</column> in <table>{target_tbl}</table> be computed from other columns/rows "
        f"in <table>{target_tbl}</table> alone — without joining other tables?\n"
        "Return 'yes' if a concrete same-table formula is plausible, 'no' if other tables are required."
    )
    rules = [
        "Consider three within-table patterns: (a) row-wise — same-row columns; "
        "(b) chaining — previous/next row in sequence; (c) hierarchical — parent/child rows.",
        "Consider reverse equations: e.g., if total_price = qty × unit_price exists, then qty = total_price / unit_price.",
        "Be realistic — neither overly pessimistic nor optimistic.",
        "Return 'yes' only if a concrete formula is plausible from the schema.",
        "Respond strictly with the JSON below.",
    ]
    payload = {"is_single_table_computed": "yes or no"}
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Database analyst determining single-table vs cross-table computation scope.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_hierarchical_parent_reference_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
) -> str:
    """Identify parent-reference columns in a hierarchical table."""
    from src.core.config import config

    initial_prompt_str = get_initial_prompt_str(config.strategy)

    if len(names_of_pk_columns_of_target_table) == 1:
        identifier_info = (
            f"The identifier of rows in <table>{config.target_table_name}</table> "
            f"is <column>{names_of_pk_columns_of_target_table[0]}</column>. "
        )
    elif len(names_of_pk_columns_of_target_table) > 1:
        identifier_info = (
            f"The identifier of rows in <table>{config.target_table_name}</table> "
            f"is the composite key: {names_of_pk_columns_of_target_table}. "
        )
    else:
        identifier_info = ""

    if len(names_of_pk_columns_of_target_table) == 0:
        task_instruction = (
            f"<table>{config.target_table_name}</table> has no known identifier — "
            "provide both the parent-reference-column and the parent-referencing-column."
        )
    elif len(names_of_pk_columns_of_target_table) == 1:
        task_instruction = (
            f"<table>{config.target_table_name}</table> has one identifier "
            f"<column>{names_of_pk_columns_of_target_table[0]}</column> — "
            "provide the parent-referencing-column."
        )
    else:
        task_instruction = (
            f"<table>{config.target_table_name}</table> has a composite key — "
            "provide the parent-referencing-column for each key part."
        )

    context = (
        initial_prompt_str + "\n\n" + target_table_description + "\n\n"
        + identifier_info
        + f"<table>{config.target_table_name}</table> is a **hierarchical table** — "
        "tree-like structure where each row has at most one parent (except the root) and zero or more children (except leaves). "
        "Each row stores its parent's identifier in a column.\n\n"
        "[Example 1] Table T (A, B, C …): A = identifier, C = parent-referencing-column (stores parent's A). "
        "Rows: R1(0,'any',null), R2(1,'any',0), R3(2,'any',0), R4(3,'any',2), R5(4,'any',null), R6(5,'any',4). "
        "R1 is parent of R2, R3; R3 is parent of R4; R5 is parent of R6. R1 and R5 have no parents.\n"
        "[Example 2] Table T with composite key (A, B): C refers to parent's A; D refers to parent's B."
    )
    task = (
        f"<column>{config.target_column_name}</column> in <table>{config.target_table_name}</table> "
        "is computed from other rows in the same hierarchical table.\n"
        + task_instruction
        + "\nUse the schema and sample rows provided."
    )
    rules = [
        "Look for self-referencing foreign keys in the schema.",
        "Identify which column stores the parent row's identifier.",
        "If no hierarchical structure exists, return empty lists.",
    ]
    payload = {
        "parent_reference_columns": [
            {
                "reference_1": ["identifier_1", "parent_reference_column_1"],
                "reference_2": ["identifier_2", "parent_reference_column_2"],
            }
        ]
    }
    payload_example_1 = {"parent_reference_columns": [{"reference_0": ["A", "C"]}]}
    payload_example_2 = {"parent_reference_columns": [{"reference_0": ["A", "C"], "reference_1": ["B", "D"]}]}
    output = (
        "Return STRICTLY in JSON. No extra commentary.\n"
        "Format: " + json.dumps(payload, ensure_ascii=False) + "\n"
        "Example 1 expected JSON: " + json.dumps(payload_example_1, ensure_ascii=False) + "\n"
        "Example 2 expected JSON: " + json.dumps(payload_example_2, ensure_ascii=False) + "\n"
        "Provide the JSON."
    )
    return _build_skill_prompt(
        role="Database analyst identifying hierarchical parent-reference columns.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


def prompt_hierarchical_candidate_formula_smartly(
    target_table_description: str,
    names_of_pk_columns_of_target_table: list,
    parent_reference_columns_list: list,
    data_for_sharing_with_LLM_str: str,
) -> str:
    """Find candidate formulas for a hierarchical table using data samples."""
    from src.core.config import config

    if len(names_of_pk_columns_of_target_table) == 1:
        identifier_info = (
            f"Identifier of rows in <table>{config.target_table_name}</table>: "
            f"<column>{names_of_pk_columns_of_target_table[0]}</column>. "
        )
    elif len(names_of_pk_columns_of_target_table) > 1:
        identifier_info = (
            f"Identifier of rows in <table>{config.target_table_name}</table>: "
            f"composite key {names_of_pk_columns_of_target_table}. "
        )
    else:
        identifier_info = ""

    if len(parent_reference_columns_list) > 0:
        if len(names_of_pk_columns_of_target_table) == 1:
            parent_ref_info = (
                f"Parent-reference-column: <column>{parent_reference_columns_list[0][0]}</column>; "
                f"parent-referencing-column: <column>{parent_reference_columns_list[0][1]}</column>. "
            )
        else:
            parent_ref_info = (
                f"<table>{config.target_table_name}</table> has a composite key. "
                "Pairs (parent-reference-column → parent-referencing-column): "
                + "".join(
                    f"<column>{pr[0]}</column> → <column>{pr[1]}</column>. "
                    for pr in parent_reference_columns_list
                )
            )
    else:
        parent_ref_info = ""

    context = (
        f"Table description: {target_table_description}\n\n"
        + identifier_info
        + f"<table>{config.target_table_name}</table> is a hierarchical table — "
        "tree-like structure: each row has at most one parent (except root) and zero or more children (except leaves).\n"
        "[Example 1] Table T (A, B, C …): A = identifier, C = parent-referencing-column. "
        "Rows: R1(0,'any',null), R2(1,'any',0), R3(2,'any',0), R4(3,'any',2). "
        "R1 is parent of R2, R3; R3 is parent of R4.\n"
        "[Example 2] Composite key (A, B): C → parent's A; D → parent's B.\n"
        + parent_ref_info
        + f"\nData samples of <table>{config.target_table_name}</table>: {data_for_sharing_with_LLM_str}"
    )
    task = (
        f"Find the formula to compute <column>{config.target_column_name}</column> "
        f"from other columns/rows in <table>{config.target_table_name}</table>.\n"
        "The formula must be compatible with the data samples.\n"
        "Use terms: `parent_row`, `children_rows`, `child_row`.\n"
        "Provide multiple candidates with confidence scores summing to 100 if uncertain. "
        "If one formula is clear, return just that one."
    )
    rules = [
        "Understand the parent-child link from the reference columns.",
        "Verify the formula pattern against the data samples.",
        "Express the pattern using parent_row, child_row, or children_rows.",
        "Be concise — only concrete, data-compatible formulas.",
    ]
    payload = {
        "candidate_formulas": [
            {"textual_formula": f" most potential formula to compute `{config.target_column_name}` "},
            {"textual_formula": f" alternative formula to compute `{config.target_column_name}`, if any "},
        ]
    }
    output = _get_json_prompt(payload)
    return _build_skill_prompt(
        role="Formula analyst working with hierarchical parent-child table computations.",
        context=context,
        task=task,
        rules=rules,
        output=output,
    )


# ============================================================================
# DATA HELPER FUNCTIONS (unchanged from template_2)
# ============================================================================


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


def prompt_zero_shot_formula(target_table: str, target_column: str) -> str:
    payload = {
        "is_computed": True,
        "sql": f"SELECT t.`{target_column}` AS actual_value, <expression> AS computed_value FROM `{target_table}` t",
        "explanation": "brief description of what the formula computes"
    }
    payload_not_computed = {
        "is_computed": False,
        "sql": None,
        "explanation": "brief reason why the column is not computed"
    }
    return _build_skill_prompt(
        context=f"Target column: <column>{target_column}</column> in table <table>{target_table}</table>",
        task=(
            f"Determine whether `{target_column}` in `{target_table}` is a computed column "
            f"(i.e. its value is fully derived from other columns via a deterministic formula). "
            f"If it is computed, write a single MySQL-compatible SQL query that, for each row, "
            f"selects the original `{target_column}` value AS actual_value alongside your computed expression AS computed_value. "
            f"If it is not computed, set is_computed to false and sql to null."
        ),
        output=(
            "Return the result STRICTLY in the JSON format below, with no extra commentary.\n"
            f"If computed: {json.dumps(payload)}\n"
            f"If not computed: {json.dumps(payload_not_computed)}\n"
            "Provide the JSON."
        ),
    )
