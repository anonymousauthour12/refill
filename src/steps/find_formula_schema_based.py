"""Step 5 module — schema-based formula finder (strategies 1, 2, 3)"""
import logging
import time

from src.core.utils import get_json_object
logging.basicConfig(level=logging.INFO)

from src.core import db_layer, file_utils, llm_layer
from src.core.llm_layer import ContextTooLargeError
from src.core import prompt_templates as pt

from src.steps.collect_statistical_metadata import tables_info

from src.core.config import config

from src.core.report_util import report, report_accuracy, reported_accuracy_list
from src.steps.formula_common import load_table_description, prepare_validation_sql_query, validate_and_prepare_computation_sql, is_computed_column, is_formula_semantically_plausible, write_metrics_to_csv, process_llm_candidate


work_space = None
column_logical_type = None

# Set by run() to control mode-specific prompt behaviour in helper functions.
# 1 = schema only
# 2 = schema + statistics + distinct values
# 3 = schema + statistics + distinct values + sample rows
_strategy = 1

tried_formulas = []
number_of_pks_in_target_table = 0
names_of_pk_columns_of_target_table = []
reported_accuracy_sequence = 0




def find_formulas_and_computation_sql():

    prompt_text = pt.prompt_find_formulas_and_computation_sql(
        target_table_description,
        config.target_column_name,
        config.target_table_name,
        number_of_pks_in_target_table,
        names_of_pk_columns_of_target_table
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(response)

    if data is None or "candidate_formulas" not in data:
        report_accuracy(-2, "no_formula_found", "", "", 1)
        return

    if isinstance(data["candidate_formulas"], str):
        report_accuracy(-2, "no_formula_found", "", "", 1)
        return

    for candidate_formula in data["candidate_formulas"]:
        try:
            textual_formula = candidate_formula["textual_formula"]
            computation_sql_query = candidate_formula["computation_sql_query"]

            llm_layer.flush_chat_history("candidate_computation_sql_query")

            global reported_accuracy_sequence
            reported_accuracy_sequence += 1

            _, _, should_stop = process_llm_candidate(
                textual_formula, computation_sql_query, column_logical_type,
                "candidate_computation_sql_query",
                f"N/A [{_STRATEGY_LABELS[_strategy]}]",
                reported_accuracy_sequence,
            )

            if should_stop:
                break

        except ContextTooLargeError as e:
            print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
            llm_layer._log_warning(f"CONTEXT_TOO_LARGE | candidate skipped | {e}")
            continue
initial_prompt_str = ""
target_table_description = ""

# Strategy-specific settings
_STRATEGY_LABELS = {
    1: "SCHEMA ONLY",
    2: "SCHEMA WITH STATISTICS AND DISTINCT VALUES",
    3: "SCHEMA WITH STATISTICS, DISTINCT VALUES AND SAMPLE ROWS",
}

# Substring to trim from initial_prompt_str per strategy (None = no trim)
_STRATEGY_TRIM_SUBSTRINGS = {
    1: "Let me share with you metadata (i.e. statistics) of each column of each table",
    2: "In addition, let me send you a few sample rows of each table. I excluded some columns like longtext, blob, etc.",
    3: None,
}

def run(strategy: int = 1):

    global _strategy
    global column_logical_type
    global initial_prompt_str
    global target_table_description
    global names_of_pk_columns_of_target_table

    _strategy = strategy
    config.strategy = strategy

    execution_start_timestamp = time.perf_counter() * 1000

    logging.info("Running Step 5...")

    print(f"STRATEGY: {_STRATEGY_LABELS[strategy]}!!!")

    llm_layer.flush_chat_history()

    db_layer.db_export_schema()

    output_file = config.work_space + f"/output_{config.target_database_name}_{config.target_table_name}_{config.target_column_name}.txt"


    file_utils.delete_file_if_exists(output_file)
    file_utils.delete_file_if_exists(db_layer.sql_log_file)

    initial_prompt_str = pt.get_initial_prompt_str(strategy)

    target_table_description = load_table_description(strategy)

    '''
    trim_substring = _STRATEGY_TRIM_SUBSTRINGS[strategy]

    if trim_substring is not None:
        initial_prompt_str = initial_prompt_str.split(trim_substring)[0]
    '''

    print (f"{config.target_table_name}, {config.target_column_name}")

    tried_formulas.clear()

    if is_computed_column(target_table_description, _strategy):

        print("yes")

        report.is_computed = True

        columns = tables_info[config.target_table_name]

        column_info = [col for col in columns if col[1].strip() == config.target_column_name.strip()][0]

        _, _, _, _, _, column_logical_type, _ = column_info

        names_of_pk_columns = [item[1] for item in columns if item[2]]
        names_of_pk_columns_of_target_table = names_of_pk_columns

        find_formulas_and_computation_sql()

        if not reported_accuracy_list:
            report_accuracy(-2, "no_formula_found", "", "", 1)

    else:
        report.is_computed = False

        print("no")

        report_accuracy(-1, "not_computed", "", "", 1)

    execution_end_timestamp = time.perf_counter() * 1000
    total_execution_time = execution_end_timestamp - execution_start_timestamp

    write_metrics_to_csv(total_execution_time)
