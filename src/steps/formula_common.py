"""Shared utilities for formula-finding step modules."""
import csv
import os
import re
from datetime import datetime

from src.core import db_layer, file_utils, llm_layer
from src.core import prompt_templates as pt
from src.core.config import config
from src.core.utils import get_json_object
from src.core.db_functions import get_distinct_values_str, get_distinct_values_list, get_filtered_columns_names_of_a_table, get_tables_dependencies_in_the_database, execute_diagnoses_query_and_result_as_string, execute_validation_query_and_get_accuracy
from src.core import connect_to_db, disconnect_from_db, execute_query_and_get_results_with_headers
from src.steps.collect_statistical_metadata import tables_info


def detect_topic(items: list) -> str:
    prompt_text = pt.prompt_detect_topic(items)
    llm_layer.flush_chat_history("detect_topic")
    response = llm_layer.get_response(prompt_text, "detect_topic")
    data = get_json_object(response)
    if data is None or "topic" not in data:
        response = llm_layer.get_response(pt.prompt_detect_topic_retry(), "detect_topic")
        data = get_json_object(response)
    return data["topic"] if data and "topic" in data else response


def _extract_computed_value_expr(sql: str) -> str:
    """Return the expression that precedes AS computed_value, walking back from the
    last top-level comma (i.e. not nested inside parentheses)."""
    cv_match = re.search(r'\bAS\s+computed_value\b', sql, re.IGNORECASE)
    if not cv_match:
        return ""
    before = sql[:cv_match.start()]
    depth = 0
    last_top_comma = -1
    for i, ch in enumerate(before):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            last_top_comma = i
    return before[last_top_comma + 1:].strip()


def _add_null_cv_column(computation_sql_query: str) -> str | None:
    """
    Return a modified computation_sql_query that adds a computed_value_null column:
    the computed_value expression with every reference to the target column replaced by NULL.
    Returns None if the target column does not appear in the computed_value expression.
    """
    col_pattern = re.escape(config.target_column_name)
    cv_expr = _extract_computed_value_expr(computation_sql_query)
    if not cv_expr:
        return None
    null_expr, n = re.subn(
        rf'\b(?:[\w`"]+\.)?`?{col_pattern}`?\b',
        'NULL',
        cv_expr,
        flags=re.IGNORECASE,
    )
    if n == 0:
        return None
    # Insert ", {null_expr} AS computed_value_null" right after "AS computed_value"
    cv_match = re.search(r'\bAS\s+computed_value\b', computation_sql_query, re.IGNORECASE)
    return (
        computation_sql_query[: cv_match.end()]
        + f", {null_expr} AS computed_value_null"
        + computation_sql_query[cv_match.end() :]
    )


def prepare_validation_sql_query(computation_sql_query: str, column_logical_type: str, is_null_computed_value_allowed: bool = True, partial_rows: int = 0):

    if computation_sql_query.endswith(";"):
        computation_sql_query = computation_sql_query[:-1]

    # If the LLM SQL does not expose an 'actual_value' alias, fall back to the real
    # target column name so the validation wrapper can always find the ground-truth value.
    has_actual_value_alias = bool(
        re.search(r'\bAS\s+actual_value\b', computation_sql_query, re.IGNORECASE)
    )
    actual_col_ref = "actual_value" if has_actual_value_alias else f"`{config.target_column_name}`"

    tbl_actual_column = actual_col_ref
    tbl_predicted_column = "computed_value"

    if column_logical_type == "float":
        tbl_actual_column = f"ROUND({actual_col_ref}, CASE WHEN LOCATE('.', CAST({actual_col_ref} AS CHAR)) = 0 THEN 0 ELSE LENGTH(SUBSTRING_INDEX(CAST({actual_col_ref} AS CHAR), '.', -1)) END)"
        tbl_predicted_column = f"ROUND({tbl_predicted_column}, CASE WHEN LOCATE('.', CAST({actual_col_ref} AS CHAR)) = 0 THEN 0 ELSE LENGTH(SUBSTRING_INDEX(CAST({actual_col_ref} AS CHAR), '.', -1)) END)"

    # Self-referential check requires a proper actual_value alias in the SQL.
    # For partial validation we skip it: (a) the self-ref check regex operates on the
    # raw computation SQL and would break if we wrapped it in a LIMIT subquery, and
    # (b) accuracy is approximate on a sample anyway.
    null_cv_sql = None
    if partial_rows == 0:
        null_cv_sql = _add_null_cv_column(computation_sql_query) if has_actual_value_alias else None

    # inner_from is the FROM-clause source for both the validation and diagnoses queries.
    # For partial mode we wrap the original SQL in SELECT * ... LIMIT N so MySQL only
    # processes a small sample of the target-table rows.  The original computation_sql_query
    # (without LIMIT) is always what gets stored in the CSV as the discovered formula.
    if partial_rows > 0:
        inner_from = f"(SELECT * FROM ({computation_sql_query}) _partial_inner LIMIT {partial_rows})"
    else:
        inner_from = f"({computation_sql_query})"

    if null_cv_sql:
        # Runtime self-referentiality check: the inner query exposes computed_value_null
        # (formula with target col replaced by NULL). A row is "self-referential" if the
        # original formula matched actual_value but the null version did not — meaning the
        # formula's success depended on reading the target column itself.
        null_cv_where = "" if is_null_computed_value_allowed else " AND computed_value IS NOT NULL"
        validation_sql_query = f"""
SELECT
    CASE WHEN self_ref > 0 THEN 0     ELSE matches    END AS matches,
    CASE WHEN self_ref > 0 THEN total ELSE mismatches END AS mismatches
FROM (
    SELECT
        SUM(CASE WHEN {tbl_actual_column} = {tbl_predicted_column} THEN 1 ELSE 0 END) AS matches,
        SUM(CASE WHEN {tbl_actual_column} = {tbl_predicted_column} THEN 0 ELSE 1 END) AS mismatches,
        SUM(CASE WHEN {tbl_actual_column} = {tbl_predicted_column}
                  AND NOT ({tbl_actual_column} <=> computed_value_null) THEN 1 ELSE 0 END) AS self_ref,
        COUNT(*) AS total
    FROM ({null_cv_sql}) tbl_raw
    WHERE actual_value IS NOT NULL{null_cv_where}
) agg;"""
    else:
        inner = f"select {actual_col_ref} as actual_value, {tbl_predicted_column} as computed_value from {inner_from} tbl_predicted_and_actual"
        null_filter = " and computed_value is not null" if not is_null_computed_value_allowed else ""
        validation_sql_query = (
            f"select sum(case when actual_value = computed_value then 1 else 0 end) as matches,"
            f" sum(case when actual_value = computed_value then 0 else 1 end) as mismatches"
            f" from ({inner}) final_table where actual_value is not null{null_filter};"
        )

    diagnoses_sql_query = (
        f"select {actual_col_ref} as actual_value, {tbl_predicted_column} as computed_value"
        f" from {inner_from} tbl_predicted_and_actual"
        f" where {actual_col_ref} != {tbl_predicted_column} or {tbl_predicted_column} is null"
        f" limit {config.diagnoses_rows_count}"
    )

    return validation_sql_query, diagnoses_sql_query


def get_table_description(table_name: str, column_name: str = "") -> str:

    initial_prompt_str = pt.get_initial_prompt_str(config.strategy)
    prompt_text = initial_prompt_str + " " + pt.prompt_get_table_description_columns(table_name)
    response = llm_layer.get_response(prompt_text, "any", False, False)
    data = get_json_object(response)
    if data and "column_descriptions" in data:
        col_descs = data["column_descriptions"]
        if isinstance(col_descs, list):
            target_table_description = " ".join(
                f"{item.get('column_name', '')}: {item.get('description', '')}"
                for item in col_descs
                if isinstance(item, dict)
            )
        else:
            target_table_description = str(col_descs)
    else:
        target_table_description = response
    target_table_description += " "

    if column_name != "":
        prompt_text = pt.prompt_get_table_description_correlations(
            table_name,
            column_name,
            target_table_description,
        )
        response = llm_layer.get_response(prompt_text, "any", False, False)
        data = get_json_object(response)
        if data and "correlations" in data:
            target_table_description += " " + str(data["correlations"])
        else:
            target_table_description += " " + response

    return target_table_description


_last_is_computed_log: str = ""   # read by main.py for column_diagnosis.log


def is_computed_column(target_table_description: str, strategy: int = 3) -> bool:

    global _last_is_computed_log
    db_layer.db_metrics.number_of_calls_to_db = 0

    prompt_text = pt.prompt_is_computed_column(
        target_table_description,
        config.target_column_name,
        config.target_table_name,
        strategy
    )

    total_candidates = 0
    for attempt in range(config.is_computed_max_attempts):
        llm_layer.flush_chat_history("iscomputed")
        response = llm_layer.get_response(prompt_text, "iscomputed")
        data = get_json_object(response)
        print(f"data (attempt {attempt + 1}): {data}")
        if data is None or "candidate_formulas" not in data:
            continue
        if isinstance(data["candidate_formulas"], str) and data["candidate_formulas"].strip().lower() == "none":
            continue
        for candidate_formula in data["candidate_formulas"]:
            print(f"candidate_formula: {candidate_formula}")
            if candidate_formula.get("textual_formula", "None") != "None":
                total_candidates += 1
                _last_is_computed_log = f"is_computed=True | attempts={attempt + 1} | candidates={total_candidates}"
                db_layer._log_warning(f"IS_COMPUTED | result=True | attempts={attempt + 1} | candidates_found={total_candidates}")
                return True

    _last_is_computed_log = f"is_computed=False | attempts=3 | candidates=0"
    db_layer._log_warning(f"IS_COMPUTED | result=False | attempts=3 | candidates_found=0")
    return False


def _log_sql_incident(chat_history_key: str, prompt: str, llm_response: str, error: str):
    if not config.work_space:
        return
    import json, time as _time
    record = {
        "timestamp": _time.strftime('%Y-%m-%d %H:%M:%S'),
        "column": f"{config.target_database_name}.{config.target_table_name}.{config.target_column_name}",
        "chat_history_key": chat_history_key,
        "prompt": prompt,
        "llm_response": llm_response,
        "error": error,
    }
    try:
        with open(os.path.join(config.work_space, "sql_incidents.jsonl"), "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass


_EXPLAIN_ROW_THRESHOLD = 10_000  # single full-scan table rows that trigger optimization
_PARTIAL_VALIDATION_ROWS = 1000   # row limit used when EXPLAIN or a runtime timeout marks a query as expensive


# ── Sample-table helpers ──────────────────────────────────────────────────────

def _substitute_sample_table(sql: str) -> str:
    """Replace the target table name with the pre-created sample table name in SQL.

    Handles both backtick-quoted (`table`) and unquoted occurrences.
    Only substitutes when config.sample_table_name is set (non-empty).
    """
    if not config.sample_table_name:
        return sql
    tbl = config.target_table_name
    sample = config.sample_table_name
    # Replace backtick-quoted form first (more specific match)
    sql = sql.replace(f'`{tbl}`', f'`{sample}`')
    # Replace bare unquoted form (word boundary so we don't hit column names)
    sql = re.sub(rf'\b{re.escape(tbl)}\b', f'`{sample}`', sql, flags=re.IGNORECASE)
    return sql


def _copy_indexes_to_sample(db: str, tbl: str, sample_name: str):
    """Recreate secondary indexes from the source table on the sample table.

    PRIMARY KEY is skipped because the 1000 random rows may have duplicate or
    missing key values.  All other indexes are created as non-unique (INDEX, not
    UNIQUE INDEX) for the same reason.  Composite indexes preserve column order
    and prefix lengths.
    """
    from collections import defaultdict

    result, headers, _, ok = execute_query_and_get_results_with_headers(
        f"SHOW INDEX FROM `{db}`.`{tbl}`"
    )
    if not ok or not result or not headers:
        return

    try:
        non_unique_idx = headers.index("Non_unique")
        key_name_idx   = headers.index("Key_name")
        seq_idx        = headers.index("Seq_in_index")
        col_name_idx   = headers.index("Column_name")
        sub_part_idx   = headers.index("Sub_part")
    except ValueError:
        db_layer._log_warning("SAMPLE_TABLE_INDEX | unexpected SHOW INDEX format — skipping indexes")
        return

    # Group rows by index name, preserving per-column order via Seq_in_index.
    index_map = defaultdict(list)
    for row in result:
        key_name = str(row[key_name_idx])
        if key_name.upper() == "PRIMARY":
            continue
        index_map[key_name].append(row)

    for key_name, rows in index_map.items():
        rows.sort(key=lambda r: int(r[seq_idx]))
        col_parts = []
        for row in rows:
            col = f"`{row[col_name_idx]}`"
            sub_part = row[sub_part_idx]
            if sub_part is not None:
                col += f"({sub_part})"
            col_parts.append(col)
        cols_str = ", ".join(col_parts)
        # Always non-unique: the random sample may violate original uniqueness constraints.
        create_idx_sql = (
            f"CREATE INDEX `{key_name}` ON `{db}`.`{sample_name}` ({cols_str})"
        )
        err = db_layer.execute_ddl(create_idx_sql)
        if err:
            db_layer._log_warning(f"SAMPLE_TABLE_INDEX_FAILED | key={key_name} | {err[:120]}")
        else:
            db_layer._log_warning(f"SAMPLE_TABLE_INDEX_CREATED | key={key_name} | cols=({cols_str})")


def create_sample_table() -> bool:
    """Create a random 1000-row sample of the target table for cross-table validation.

    The table is named _sample_{pid}_{target_table} to avoid conflicts between
    parallel workers.  Only created when the target table exceeds
    _PARTIAL_VALIDATION_ROWS rows.  Secondary indexes from the source table are
    copied so JOIN queries can use them.  Sets config.sample_table_name on success.
    Returns True if the table was created, False if not needed or on error.
    """
    import os
    tbl = config.target_table_name
    col = config.target_column_name
    db  = config.target_database_name

    if not config.use_sample_table:
        return False  # feature disabled in config.yaml

    # Check whether the target table is large enough to warrant sampling.
    _target_cols = tables_info.get(tbl, [])
    row_count = (
        _target_cols[0][6].get('total_number_of_values', 0)
        if _target_cols and _target_cols[0][6]
        else 0
    )
    if row_count <= _PARTIAL_VALIDATION_ROWS:
        return False  # small table — no need for a sample

    pid = os.getpid()
    sample_name = f"_sample_{pid}_{tbl}"

    # Drop any leftover from a previous crashed run with the same PID.
    db_layer.execute_ddl(f"DROP TABLE IF EXISTS `{db}`.`{sample_name}`")

    create_sql = (
        f"CREATE TABLE `{db}`.`{sample_name}` AS "
        f"SELECT * FROM `{db}`.`{tbl}` "
        f"WHERE `{col}` IS NOT NULL "
        f"ORDER BY RAND() "
        f"LIMIT {_PARTIAL_VALIDATION_ROWS}"
    )
    err = db_layer.execute_ddl(create_sql)
    if err:
        db_layer._log_warning(f"SAMPLE_TABLE_CREATE_FAILED | {err[:120]}")
        return False

    # Copy secondary indexes from the source table so JOIN queries can use them.
    _copy_indexes_to_sample(db, tbl, sample_name)

    config.sample_table_name = sample_name
    db_layer._log_warning(
        f"SAMPLE_TABLE_CREATED | {db}.{sample_name} | source_rows={row_count}"
    )
    return True


def drop_sample_table():
    """Drop the pre-created sample table and clear config.sample_table_name."""
    if not config.sample_table_name:
        return
    db = config.target_database_name
    sample_name = config.sample_table_name
    err = db_layer.execute_ddl(f"DROP TABLE IF EXISTS `{db}`.`{sample_name}`")
    if err:
        db_layer._log_warning(f"SAMPLE_TABLE_DROP_FAILED | {err[:120]}")
    else:
        db_layer._log_warning(f"SAMPLE_TABLE_DROPPED | {db}.{sample_name}")
    config.sample_table_name = ""

def _explain_query(sql: str) -> tuple:
    """Run EXPLAIN on sql. Returns (is_expensive: bool, explain_str: str)."""
    try:
        result, headers, _, _ = execute_query_and_get_results_with_headers(f"EXPLAIN {sql}")
    except Exception:
        return False, ""
    if not result or not headers:
        return False, ""

    header_str = " | ".join(str(h) for h in headers)
    rows_str = "\n".join(" | ".join(str(v) for v in row) for row in result)
    explain_str = header_str + "\n" + rows_str

    try:
        type_idx = headers.index("type")
        rows_idx = headers.index("rows")
        for row in result:
            scan_type = str(row[type_idx]) if row[type_idx] else ""
            est_rows = int(row[rows_idx]) if row[rows_idx] else 0
            if scan_type == "ALL" and est_rows > _EXPLAIN_ROW_THRESHOLD:
                return True, explain_str
    except (ValueError, IndexError):
        pass
    return False, explain_str


def _try_optimize_query(computation_sql_query: str, explain_str: str, chat_history_key: str):
    """Ask LLM once to optimize an expensive query. Returns optimized SQL or None."""
    prompt_text = pt.prompt_optimize_sql_query(computation_sql_query, explain_str)
    response = llm_layer.get_response(prompt_text, chat_history_key)
    data = get_json_object(response)
    if not data:
        return None
    optimized = data.get("computation_sql_query")
    if not optimized or str(optimized).strip().lower() in ("null", "none", ""):
        db_layer._log_warning("EXPLAIN_OPTIMIZE | LLM returned null — skipping candidate")
        return None
    db_layer._log_warning(f"EXPLAIN_OPTIMIZE | rewritten query accepted")
    return optimized


def validate_and_prepare_computation_sql(
    computation_sql_query: str,
    column_logical_type: str,
    chat_history_key: str,
    is_null_computed_value_allowed: bool = True,
    use_sample: bool = False,
) -> tuple:
    """
    Wrap computation_sql_query in the validation shell and confirm it runs error-free.
    On SQL error, ask the LLM to fix the computation SQL and retry up to
    execute_query_max_tries times.

    When use_sample=True and config.sample_table_name is set, the validation (only)
    runs against the pre-created 1000-row sample table instead of the full target
    table.  The returned computation_sql_query always references the real table so
    the stored formula is correct.

    Returns (is_valid, computation_sql_query, validation_sql_query, diagnoses_sql_query, is_partial).
    """
    if not computation_sql_query:
        return False, computation_sql_query, "", "", False

    # Some LLMs (e.g. Llama) emit 'target_table' as a literal table name instead of
    # an alias. Detect this by checking whether the SQL contains 'AS target_table';
    # if not, every occurrence of 'target_table' is a placeholder and should be
    # replaced with the real table name.
    if not re.search(r'\bAS\s+target_table\b', computation_sql_query, re.IGNORECASE):
        computation_sql_query = re.sub(
            r'\btarget_table\b',
            f'`{config.target_table_name}`',
            computation_sql_query,
            flags=re.IGNORECASE,
        )

    # When running cross-table validation on a large target table, substitute the real
    # table name with the pre-created 1000-row sample table for the validation only.
    # The formula stored in the report still references the real table.
    sql_for_validation = _substitute_sample_table(computation_sql_query) if use_sample else computation_sql_query

    is_partial = False

    if use_sample and config.sample_table_name:
        # Sample table is already ≤1000 rows — skip PREEMPTIVE/EXPLAIN checks.
        # Mark as partial because we're validating on a row-limited sample.
        is_partial = True
        db_layer._log_warning(f"USING_SAMPLE_TABLE | {config.sample_table_name}")
    else:
        # Fast preemptive check: if the target table is known to be large (row count already
        # populated by Step 1 metadata), skip EXPLAIN and go straight to partial validation.
        _target_cols = tables_info.get(config.target_table_name, [])
        _target_row_count = (
            _target_cols[0][6].get('total_number_of_values', 0)
            if _target_cols and _target_cols[0][6]
            else 0
        )
        if _target_row_count > _EXPLAIN_ROW_THRESHOLD:
            db_layer._log_warning(
                f"PREEMPTIVE_PARTIAL | rows={_target_row_count} | skipping EXPLAIN"
            )
            from src.core.timeout_profiler import log_timeout
            log_timeout("PREEMPTIVE_PARTIAL", 0, _EXPLAIN_ROW_THRESHOLD, computation_sql_query)
            is_partial = True
        else:
            # One-time EXPLAIN check for smaller tables before the error-fix loop.
            _validation_sql_for_explain, _ = prepare_validation_sql_query(
                sql_for_validation, column_logical_type, is_null_computed_value_allowed
            )
            is_expensive, _ = _explain_query(_validation_sql_for_explain)
            if is_expensive:
                db_layer._log_warning(f"EXPLAIN_EXPENSIVE | switching to partial validation ({_PARTIAL_VALIDATION_ROWS} rows)")
                from src.core.timeout_profiler import log_timeout
                log_timeout("EXPLAIN_EXPENSIVE", 0, _EXPLAIN_ROW_THRESHOLD, computation_sql_query)
                is_partial = True

    for attempt in range(max(1, config.execute_query_max_tries)):
        # When using the sample table the inner SQL already hits ≤1000 rows,
        # so no additional LIMIT wrapping is needed (partial_rows stays 0).
        _partial_rows = (
            0 if (use_sample and config.sample_table_name)
            else (_PARTIAL_VALIDATION_ROWS if is_partial else 0)
        )
        validation_sql_query, diagnoses_sql_query = prepare_validation_sql_query(
            sql_for_validation, column_logical_type, is_null_computed_value_allowed,
            partial_rows=_partial_rows,
        )
        err = db_layer.validate_query(validation_sql_query)
        if not err:
            return True, computation_sql_query, validation_sql_query, diagnoses_sql_query, is_partial
        db_layer._log_warning(f"VALIDATION_SQL_ERROR | {err[:120]}")

        # DB timeout (MySQL error 3024): don't ask LLM — it can't rewrite away a
        # structural performance problem.  On the first timeout switch to partial
        # validation (1000 rows) and retry; on the second bail out immediately.
        if "3024" in err or "maximum statement execution time" in err.lower() \
                or "2013" in err or "lost connection" in err.lower():
            from src.core.timeout_profiler import log_timeout
            if is_partial:
                db_layer._log_warning("TIMEOUT_ON_PARTIAL | DB timeout on 1000-row validation, bailing out")
                log_timeout("DB_TIMEOUT_ON_PARTIAL", 0, 600_000, err[:200])
                return False, computation_sql_query, "", "", True
            db_layer._log_warning(
                f"TIMEOUT_SWITCH_TO_PARTIAL | DB timeout detected, retrying with {_PARTIAL_VALIDATION_ROWS}-row validation"
            )
            log_timeout("DB_TIMEOUT_SWITCH_TO_PARTIAL", 0, 600_000, err[:200])
            is_partial = True
            continue  # retry immediately with partial (no LLM call)

        # Syntax / logic error: ask LLM to fix.
        # On the first failure, log the generation prompt/response that produced the bad SQL.
        if attempt == 0:
            history = llm_layer.chat_histories.get(chat_history_key, [])
            gen_prompt = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
            gen_response = next((m["content"] for m in reversed(history) if m["role"] == "assistant"), "")
            _log_sql_incident(chat_history_key, gen_prompt, gen_response, err)
        prompt_text = pt.prompt_fix_sql_query_error(computation_sql_query, err)
        response = llm_layer.get_response(prompt_text, chat_history_key)
        _log_sql_incident(chat_history_key, prompt_text, response, err)
        data = get_json_object(response)
        if data and "computation_sql_query" in data:
            computation_sql_query = data["computation_sql_query"]
            # Re-apply sample substitution after LLM rewrites the SQL.
            sql_for_validation = _substitute_sample_table(computation_sql_query) if use_sample else computation_sql_query
        else:
            break
    return False, computation_sql_query, "", "", is_partial


def is_formula_semantically_plausible(textual_formula: str, computation_sql_query: str) -> tuple:
    """Returns (is_plausible: bool, timestamp: datetime) captured just before returning."""
    if not textual_formula or textual_formula in ("NaN", "None", "none"):
        return True, datetime.now()
    prompt_text = pt.prompt_semantic_plausibility_check(
        textual_formula,
        computation_sql_query,
        config.target_column_name,
        config.target_table_name,
    )
    response = llm_layer.get_response(prompt_text, "any", False, False)
    data = get_json_object(response)
    if data is None or "is_plausible" not in data:
        return True, datetime.now()  # fail open: don't block on LLM/parse failure
    result = bool(data["is_plausible"])
    if not result:
        print(f"[plausibility] rejected: {data.get('reason', '')}")
    return result, datetime.now()


def diagnose_a_validation_sql_query(
    computation_sql_query: str,
    diagnoses_sql_query: str,
    column_logical_type: str,
    chat_history_key: str = "",
) -> tuple:
    """Step 6 — fetch mismatch rows, ask LLM to fix SQL, re-validate.

    Returns (corrected_sql, accuracy_after, is_partial).
    Returns ("", -1, True) on any failure so callers treat it as no improvement.
    """
    diagnoses_result_str = execute_diagnoses_query_and_result_as_string(diagnoses_sql_query)

    prompt_text = pt.prompt_diagnose_formula_mismatch(
        computation_sql_query,
        diagnoses_sql_query,
        diagnoses_result_str,
        config.target_column_name,
        config.target_table_name,
    )

    if chat_history_key:
        result = llm_layer.get_response(prompt_text, chat_history_key)
    else:
        result = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(result)
    if data is None or "computation_sql_query_after_diagnoses" not in data:
        return "", -1, True

    sql_after = data["computation_sql_query_after_diagnoses"]
    is_succeed, sql_after, val_sql_after, _, is_partial_diag = validate_and_prepare_computation_sql(
        sql_after, column_logical_type, chat_history_key
    )
    if not is_succeed:
        return "", -1, True

    accuracy_after, _ = execute_validation_query_and_get_accuracy(val_sql_after)
    if accuracy_after < 0:
        return "", -1, True

    return sql_after, accuracy_after, is_partial_diag


def process_llm_candidate(
    textual_formula: str,
    computation_sql_query: str,
    column_logical_type: str,
    chat_history_key: str,
    branch_label: str,
    seq_num: int,
    skip_plausibility: bool = False,
    use_sample: bool = False,
    is_null_computed_value_allowed: bool = True,
) -> tuple:
    """Apply Steps 4, 5, and 6 uniformly to any LLM-generated SQL candidate.

    Step 4 — Semantic plausibility check (skipped when skip_plausibility=True).
    Step 5 — SQL validation + accuracy measurement + report.
    Step 6 — Diagnosis: fetch mismatch rows, LLM fixes SQL, re-validate + report.

    Returns (best_accuracy, best_sql, should_stop).
    should_stop=True when accuracy >= cleaning_threshold AND early_stopping=True.
    Returns (-1, "", False) when SQL validation fails entirely.
    """
    from src.core.report_util import report_accuracy

    # Step 4
    is_implausible = False
    plausibility_ts = None
    if not skip_plausibility:
        is_plausible, plausibility_ts = is_formula_semantically_plausible(textual_formula, computation_sql_query or "")
        is_implausible = not is_plausible

    # Step 5
    is_valid, computation_sql_query, validation_sql_query, diagnoses_sql_query, is_partial = \
        validate_and_prepare_computation_sql(
            computation_sql_query, column_logical_type, chat_history_key,
            is_null_computed_value_allowed=is_null_computed_value_allowed,
            use_sample=use_sample,
        )
    if not is_valid:
        return -1, "", False

    accuracy, _ = execute_validation_query_and_get_accuracy(validation_sql_query)
    report_accuracy(accuracy, textual_formula, computation_sql_query, branch_label,
                    seq_num, is_implausible, full_validation=not is_partial,
                    plausibility_timestamp=plausibility_ts)

    if accuracy >= config.cleaning_threshold and config.early_stopping:
        return accuracy, computation_sql_query, True

    # Step 6
    diag_key = f"diagnose_{chat_history_key}"
    llm_layer.flush_chat_history(diag_key)
    sql_after, accuracy_after, is_partial_diag = diagnose_a_validation_sql_query(
        computation_sql_query, diagnoses_sql_query, column_logical_type, diag_key
    )
    if accuracy_after >= 0:
        report_accuracy(accuracy_after, textual_formula, sql_after,
                        f"{branch_label} [After Diagnoses]", seq_num, is_implausible,
                        full_validation=not is_partial_diag,
                        plausibility_timestamp=plausibility_ts)
        if accuracy_after >= config.cleaning_threshold and config.early_stopping:
            return accuracy_after, sql_after, True

    best_accuracy = max(accuracy, accuracy_after if accuracy_after >= 0 else -1)
    best_sql = sql_after if (accuracy_after >= 0 and accuracy_after >= accuracy) else computation_sql_query
    return best_accuracy, best_sql, False


_reachable_tables_cache: dict = {}

def _get_reachable_tables() -> set:
    """Return tables within 3 FK hops of the target table (undirected graph BFS)."""
    key = (config.target_database_name, config.target_table_name)
    if key in _reachable_tables_cache:
        return _reachable_tables_cache[key]

    dependencies, _ = get_tables_dependencies_in_the_database()

    graph: dict = {}
    for parent, child, _ in dependencies:
        graph.setdefault(parent, set()).add(child)
        graph.setdefault(child, set()).add(parent)

    visited = {config.target_table_name}
    frontier = {config.target_table_name}
    for _ in range(config.schema_pruning_fk_hops):
        next_frontier = set()
        for t in frontier:
            for neighbor in graph.get(t, set()):
                if neighbor not in visited:
                    next_frontier.add(neighbor)
                    visited.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break

    _reachable_tables_cache[key] = visited
    return visited


def _filter_schema_sql(schema_sql: str, reachable: set) -> str:
    """Keep only CREATE TABLE blocks whose table name is in reachable."""
    blocks = re.split(r'(?=CREATE TABLE\s)', schema_sql, flags=re.IGNORECASE)
    result = []
    for block in blocks:
        m = re.match(r'CREATE TABLE\s+`?(\w+)`?', block, re.IGNORECASE)
        if m:
            if m.group(1) in reachable:
                result.append(block)
        elif block.strip():
            result.append(block)
    return "".join(result)


def load_database_schema():

    database_schema_file = f"database_info/{config.target_database_name}/schema.sql"

    if file_utils.is_file_exists(database_schema_file):
        db_schema_content = file_utils.read_file(database_schema_file)
    else:
        os.makedirs(os.path.dirname(database_schema_file), exist_ok=True)
        db_schema_content = file_utils.read_file(db_layer.schema_file_path)
        file_utils.write_file(database_schema_file, db_schema_content)

    reachable = _get_reachable_tables()
    return _filter_schema_sql(db_schema_content, reachable)

def _filter_text_sections(text: str, reachable: set) -> str:
    """Filter a prompt string whose table sections start with "In table 'tbl_name'"."""
    blocks = re.split(r"(?=In table ')", text)
    result = []
    for block in blocks:
        m = re.match(r"In table '(\w+)'", block)
        if m:
            if m.group(1) in reachable:
                result.append(block)
        elif block.strip():
            result.append(block)
    return "".join(result)


def load_database_columns_metadata() -> str:
    database_columns_metadata_file = f"database_info/{config.target_database_name}/columns_metadata.txt"

    if file_utils.is_file_exists(database_columns_metadata_file):
        full_str = file_utils.read_file(database_columns_metadata_file)
    else:
        full_str = ""
        for tbl_name, columns in tables_info.items():
            column_metadata_parts = []
            for col in columns:
                _, col_name, _, _, data_type, logical_type, stats = col
                total_number_of_values = stats["total_number_of_values"] or 0
                number_of_null_values = stats["number_of_null_values"] or 0
                number_of_distinct_values = stats["number_of_distinct_values"] or 0
                is_category = stats["is_category"] or False
                if logical_type == "string":
                    distinct_values_list = get_distinct_values_list(config.target_database_name, tbl_name, col_name)
                    topic = detect_topic(distinct_values_list)
                    column_metadata_parts.append(pt.prompt_column_metadata_string(col_name, data_type, total_number_of_values, number_of_null_values, number_of_distinct_values, is_category, topic))
                else:
                    min_value = stats["min_value"] or 0
                    max_value = stats["max_value"] or 0
                    average_value = stats["average_value"] or 0
                    column_metadata_parts.append(pt.prompt_column_metadata_numeric(col_name, data_type, total_number_of_values, number_of_null_values, number_of_distinct_values, is_category, min_value, max_value, average_value))
            full_str += pt.prompt_table_metadata_row(tbl_name, "".join(column_metadata_parts))
        file_utils.write_file(database_columns_metadata_file, full_str)

    return _filter_text_sections(full_str, _get_reachable_tables())


def load_database_distinct_values() -> str:
    database_distinct_values_file = f"database_info/{config.target_database_name}/distinct_values.txt"

    if file_utils.is_file_exists(database_distinct_values_file):
        full_str = file_utils.read_file(database_distinct_values_file)
    else:
        full_str = ""
        for tbl_name, columns in tables_info.items():
            table_part = ""
            for col in columns:
                col_name = col[1]
                values_str = get_distinct_values_str(config.target_database_name, tbl_name, col_name)
                if values_str != "":
                    table_part += pt.prompt_distinct_values_column_item(col_name, values_str)
            if table_part != "":
                full_str += pt.prompt_distinct_values_table_row(tbl_name, table_part)
        file_utils.write_file(database_distinct_values_file, full_str)

    return _filter_text_sections(full_str, _get_reachable_tables())


def load_database_sample_rows() -> str:
    database_sample_rows_file = f"database_info/{config.target_database_name}/sample_rows.txt"

    if file_utils.is_file_exists(database_sample_rows_file):
        full_str = file_utils.read_file(database_sample_rows_file)
    else:
        full_str = ""
        for tbl_name, _ in tables_info.items():
            columns_names_str = get_filtered_columns_names_of_a_table(tbl_name)
            sql_query = f"SELECT distinct {columns_names_str} FROM {tbl_name} LIMIT {config.data_sharing_strategy_3_number_of_rows}"
            result, header, _, _ = execute_query_and_get_results_with_headers(sql_query)
            header_str = ", ".join(header)
            full_str += pt.prompt_table_sample_rows(tbl_name, header_str, result)
        file_utils.write_file(database_sample_rows_file, full_str)

    return _filter_text_sections(full_str, _get_reachable_tables())

def load_table_description(strategy: int) -> str:

    target_table_description_file = f"database_info/{config.target_database_name}/table_descriptions/{config.target_table_name}_S{strategy}.txt"

    if file_utils.is_file_exists(target_table_description_file):
        #print("target_table_description_file is found")
        target_table_description = file_utils.read_file(target_table_description_file)
    else:
        #print("target_table_description_file is not found")
        os.makedirs(os.path.dirname(target_table_description_file), exist_ok=True)
        target_table_description = get_table_description(config.target_table_name)
        file_utils.write_file(target_table_description_file, target_table_description)

    return target_table_description

'''
def load_cached_prompts() -> tuple:
    initial_prompt_file = f"stored_prompts/initial_prompt_{config.target_database_name}_{config.target_table_name}_{config.target_column_name}.txt"
    target_table_description_file = f"stored_prompts/target_table_description_{config.target_database_name}_{config.target_table_name}_{config.target_column_name}.txt"

    if file_utils.is_file_exists(initial_prompt_file):
        #print("initial_prompt_file file is found")
        initial_prompt_str = file_utils.read_file(initial_prompt_file)
    else:
        #print("initial_prompt_file is not found")
        initial_prompt_str = get_initial_prompt_str(config.target_database_name, config.target_table_name, config.target_column_name)
        file_utils.write_file(initial_prompt_file, initial_prompt_str)

    if file_utils.is_file_exists(target_table_description_file):
        #print("target_table_description_file is found")
        target_table_description = file_utils.read_file(target_table_description_file)
    else:
        #print("target_table_description_file is not found")
        target_table_description = get_table_description(config.target_table_name, initial_prompt_str, config.target_column_name)
        file_utils.write_file(target_table_description_file, target_table_description)

    return initial_prompt_str, target_table_description
'''

def write_metrics_to_csv(total_execution_time: float):
    csv_filename = config.work_space + "/time_metrics_log.csv"

    metrics_row = {
        "target_database": config.target_database_name,
        "target_table": config.target_table_name,
        "target_column": config.target_column_name,
        "strategy": config.strategy,
        "model": config.model,
        "prompt_template": config.prompt_template,
        "early_stopping": config.early_stopping,
        "total_execution_time": total_execution_time,
        "number_of_calls_to_LLM": llm_layer.llm_metrics.number_of_calls_to_LLM,
        "total_LLM_time": round(llm_layer.llm_metrics.total_LLM_time),
        "number_of_chars_to_LLM": llm_layer.llm_metrics.number_of_chars_to_LLM,
        "number_of_chars_from_LLM": llm_layer.llm_metrics.number_of_chars_from_LLM,
        "number_of_calls_to_DB": db_layer.db_metrics.number_of_calls_to_db,
        "number_of_non_guaranteed_queries": db_layer.db_metrics.number_of_non_guarenteed_queries,
        "number_of_guaranteed_queries": db_layer.db_metrics.number_of_guarenteed_queries,
        "total_db_time": db_layer.db_metrics.total_db_time,
        "number_of_errors_of_non_guarenteed_queries": db_layer.db_metrics.number_of_errors_of_non_guarenteed_queries
    }

    file_exists = os.path.isfile(csv_filename)

    with open(csv_filename, mode="a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=metrics_row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(metrics_row)


def build_data_points_condition_sql(table_name: str, headers: list, results: list) -> str:
    data_points_condition_sql = " "

    if len(headers) == 1:
        data_points_condition_sql += f" {table_name}.{headers[0]} in ("
        for result in results:
            data_points_condition_sql += f"'{result[0]}', "
        data_points_condition_sql = data_points_condition_sql[:-2]
        data_points_condition_sql += ")"
    else:
        for result in results:
            i = 0
            data_points_condition_sql += "("
            for header in headers:
                data_points_condition_sql += f" {table_name}.{header} = '{result[i]}' and "
                i += 1
            data_points_condition_sql = data_points_condition_sql[:-4]
            data_points_condition_sql += ") or "
        data_points_condition_sql = data_points_condition_sql[:-3]

    return data_points_condition_sql
