"""Zero-shot baseline for computed column recovery (strategies 1 and 3).

Single LLM call, no rules, no retry loop, no diagnosis.
Used as a competitor baseline in the paper evaluation.
"""
import time

from src.core import llm_layer
from src.core import prompt_templates as pt
from src.core.config import config
from src.core.utils import get_json_object
from src.core.db_functions import execute_validation_query_and_get_accuracy
from src.core.report_util import report_accuracy, report
from src.steps.collect_statistical_metadata import tables_info
from src.steps.formula_common import (
    prepare_validation_sql_query,
    load_table_description,
    write_metrics_to_csv,
)

_STRATEGY_LABELS = {
    1: "ZERO_SHOT_S1",
    2: "ZERO_SHOT_S2",
    3: "ZERO_SHOT_S3",
}


def run(strategy: int = 1):
    """Run zero-shot formula prediction for the configured target column.

    strategy=1 → schema-only context (S1)
    strategy=2 → schema + stats + distinct values context (S2)
    strategy=3 → schema + stats + sample rows context (S3)
    """
    assert strategy in (1, 2, 3), f"zero_shot.run() only supports strategy 1, 2, or 3, got {strategy}"

    config.strategy = strategy
    execution_start = time.perf_counter() * 1000

    label = _STRATEGY_LABELS[strategy]
    print(f"ZERO-SHOT BASELINE: {label}")
    print(f"{config.target_table_name}, {config.target_column_name}")

    llm_layer.flush_chat_history()

    # --- context ----------------------------------------------------------------
    context_str = pt.get_initial_prompt_str(strategy)

    # --- column metadata --------------------------------------------------------
    columns = tables_info.get(config.target_table_name, [])
    column_info_list = [c for c in columns if c[1].strip() == config.target_column_name.strip()]
    if not column_info_list:
        report.is_computed = False
        report_accuracy(-2, "column_not_in_tables_info", "", "", 1)
        write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
        return

    _, _, _, _, _, column_logical_type, _ = column_info_list[0]

    # --- single LLM call --------------------------------------------------------
    prompt_text = context_str + "\n" + pt.prompt_zero_shot_formula(
        config.target_table_name, config.target_column_name
    )
    response = llm_layer.get_response(prompt_text, "zero_shot", False, False)

    data = get_json_object(response)
    if data is None:
        report.is_computed = True
        report_accuracy(-2, "no_sql_returned", "", "", 1)
        write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
        return

    # LLM says the column is not computed
    if not data.get("is_computed", True):
        report.is_computed = False
        report_accuracy(-1, "not_computed", "", "", 1)
        write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
        return

    if not data.get("sql"):
        report.is_computed = True
        report_accuracy(-2, "no_sql_returned", "", "", 1)
        write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
        return

    computation_sql = str(data["sql"]).strip()
    explanation = str(data.get("explanation", "zero_shot"))

    # --- validation (no retry, no diagnosis) ------------------------------------
    report.is_computed = True
    try:
        validation_sql, _ = prepare_validation_sql_query(
            computation_sql, column_logical_type
        )
        accuracy, _ = execute_validation_query_and_get_accuracy(validation_sql)
        if accuracy < 0:
            accuracy = 0.0
    except Exception as e:
        llm_layer._log_warning(f"ZERO_SHOT_VALIDATION_ERROR | {e}")
        report_accuracy(-2, "validation_error", computation_sql, label, 1)
        write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
        return

    report_accuracy(accuracy, explanation, computation_sql, label, 1)
    write_metrics_to_csv(time.perf_counter() * 1000 - execution_start)
