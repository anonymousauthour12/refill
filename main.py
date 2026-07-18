#!/usr/bin/env python3
"""Main entry point for the project"""

import logging
import argparse
import signal
import time
import json
import traceback
import sys
from datetime import datetime, timezone
from src.core import llm_layer, prepare_database
#from src.core.config import init_config, db_config
import src.core.config as cfg
from src.core.db_functions import prepare_data_sharing
#from src.core.is_homogeneous import is_homogeneous_func
#from src.core.is_homogeneous_with_k2_check import is_homogeneous_with_k2_check_func
#from src.core.semantic_functions import semantic_test_func
#from src.core.semantic_functions_2 import semantic_test_func2
from src.steps import collect_statistical_metadata, find_formula_schema_based, find_formula_smartly_selected, rename_tables_and_columns, zero_shot


from src.core.report_util import report, write_the_report, report_accuracy, reported_accuracy_list
from src.core.llm_layer import ContextTooLargeError

# Mutable module-level state accessible by the SIGTERM signal handler
_start_ms = [0.0]
_bulk_file = [""]

def _sigterm_handler(signum, frame):
    """Catch the 1-hour xargs timeout (SIGTERM) and write a structured profiling record."""
    # Explicitly tell MySQL to stop the current query before we exit,
    # so it doesn't keep running as a zombie after this process dies.
    try:
        from src.core.db_layer import kill_running_query
        kill_running_query()
    except Exception:
        pass
    try:
        from src.steps.formula_common import drop_sample_table
        drop_sample_table()
    except Exception:
        pass
    elapsed = time.perf_counter() * 1000 - _start_ms[0]
    try:
        from src.core.timeout_profiler import log_timeout
        col = (f"{cfg.config.target_database_name}."
               f"{cfg.config.target_table_name}."
               f"{cfg.config.target_column_name}")
        log_timeout("PIPELINE_TIMEOUT_1H", elapsed, 3_600_000, col)
        if not reported_accuracy_list:
            report_accuracy(-2, "pipeline_timeout", "", "", 1)
        from src.steps.formula_common import write_metrics_to_csv
        write_metrics_to_csv(0)
        _write_column_diagnosis()
        write_the_report(_bulk_file[0])
    except Exception:
        pass
    try:
        from src.core.db_layer import disconnect_from_db
        disconnect_from_db()
    except Exception:
        pass
    sys.exit(1)

signal.signal(signal.SIGTERM, _sigterm_handler)


def _write_column_diagnosis():
    """Write a 3-6 line summary to {work_space}/column_diagnosis.log for instant FN/FP triage."""
    try:
        import os
        from src.core import db_layer
        from src.steps.formula_common import _last_is_computed_log

        ws = cfg.config.work_space
        if not ws:
            return

        col = (f"{cfg.config.target_database_name}."
               f"{cfg.config.target_table_name}."
               f"{cfg.config.target_column_name}")

        real    = [r for r in reported_accuracy_list if r[0] >= 0]
        sent    = [r for r in reported_accuracy_list if r[0] < 0]
        lines   = [f"COLUMN   : {col} | model={cfg.config.model} | strategy={cfg.config.strategy}"]

        if not real and sent:
            sv = sent[0][0]
            if sv == -1:
                lines.append(f"RESULT   : FN_NOT_COMPUTED (sentinel=-1) | {_last_is_computed_log}")
            else:
                errors    = db_layer.db_metrics.number_of_errors_of_non_guarenteed_queries
                llm_calls = llm_layer.llm_metrics.number_of_calls_to_LLM
                lines.append(f"RESULT   : FN_NO_FORMULA (sentinel=-2)")
                lines.append(f"ERRORS   : sql_errors={errors} | llm_calls={llm_calls}")
        elif real:
            best = max(real, key=lambda r: r[0])
            acc, formula, _, meta, _, _, _, _, _, _, _, _, _, _, _, implausible, full_val = best
            branch     = (meta or "").split(",")[0].strip("[] ") or "unknown"
            full_label = "True" if full_val else "False (partial)"
            lines.append(f"RESULT   : FOUND ({acc:.1f}%) | branch={branch} | full_val={full_label}")
            lines.append(f"FLAGS    : implausible={implausible}")
            lines.append(f"FORMULA  : {str(formula)[:120]}")
        else:
            lines.append("RESULT   : UNKNOWN (reported_accuracy_list empty)")

        with open(os.path.join(ws, "column_diagnosis.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


logging.disable(logging.CRITICAL)


logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')


def main():

    print("***************************************************************************************************************")
    start_timestamp = time.perf_counter() * 1000
    _start_ms[0] = start_timestamp

    parser = argparse.ArgumentParser(description="Run the 6-step process")
    parser.add_argument("--steps", nargs="*", type=int, help="Specify steps to run (1-6). Default: all")
    parser.add_argument("--db_name", type=str, help="Specify the name of the database")
    parser.add_argument("--table_name", type=str, help="Specify the table of the target column")
    parser.add_argument("--column_name", type=str, help="Specify the target column")
    parser.add_argument("--work_space", type=str, help="Specify the experiment directory")
    parser.add_argument("--bulk_experiments_file_path", type=str, help="Specify the experiment directory")
    parser.add_argument("--strategy", type=int, help="Specify the strategy to use in step 5")
    parser.add_argument("--model", type=str, help="Override the model from config.yaml")
    parser.add_argument("--prompt_template", type=int, help="Override the prompt template from config.yaml")
    parser.add_argument("--early_stopping", type=lambda x: x.lower() == "true", help="Override early stopping from config.yaml (True/False)")

    args = parser.parse_args()

    steps_to_run = args.steps if args.steps else [1, 2, 3, 4, 5, 6]
    logging.info(f"Steps to run: {steps_to_run}")
    target_database_name = args.db_name
    target_table_name = args.table_name
    target_column_name = args.column_name
    config_file_path = args.work_space + "/config.yaml"
    bulk_experiments_file_path = args.bulk_experiments_file_path
    _bulk_file[0] = bulk_experiments_file_path or ""
    strategy = args.strategy


    print(f"Given the following column: {target_database_name}.{target_table_name}.{target_column_name}")

    print(f"strategy: {strategy}")


    cfg.set_configuration(config_file_path, args.db_name, args.table_name, args.column_name, args.work_space, args.model)
    if args.strategy:
        cfg.config.strategy = args.strategy
    if args.prompt_template:
        cfg.config.prompt_template = args.prompt_template
    if args.early_stopping is not None:
        cfg.config.early_stopping = args.early_stopping

    print(f"=== Experiment Configuration ===")
    print(f"  Model:           {cfg.config.model}")
    print(f"  Strategy:        {cfg.config.strategy}")
    print(f"  Prompt Template: {cfg.config.prompt_template}")
    print(f"  Early Stopping:  {cfg.config.early_stopping}")
    print(f"================================")

    report.target_database = args.db_name
    report.target_table = args.table_name
    report.target_column = args.column_name

    llm_layer.llm_init()

    try:
        from src.core.db_layer import connect_to_db
        connect_to_db(cfg.config.target_database_name)
        for step in steps_to_run:
            logging.info(f"Executing Step {step}")
            if step == 1:
                print("step 1")
                collect_statistical_metadata.run()
            elif step == 2:
                rename_tables_and_columns.run()
            elif step == 3:
                pass
            elif step == 4:
                pass
            elif step == 5:
                print("step 5")
                if strategy in (1, 2, 3):
                    try:
                        find_formula_schema_based.run(strategy)
                    except ContextTooLargeError as e:
                        print(f"[CONTEXT_TOO_LARGE] strategy={strategy} → {e}")
                        llm_layer._log_warning(f"CONTEXT_TOO_LARGE | strategy={strategy} | {e}")
                        from src.core.timeout_profiler import log_timeout
                        log_timeout("CONTEXT_TOO_LARGE", 0, 0, str(e)[:200])
                        if not reported_accuracy_list:
                            report_accuracy(-2, "context_too_large", "", "", 1)
                elif strategy == 4:
                    _original_dp = cfg.config.maximum_potential_data_points_in_target_table
                    _dp_sizes = [s for s in [_original_dp, 5, 3, 2] if s <= _original_dp]
                    _dp_sizes = sorted(set(_dp_sizes), reverse=True)
                    for _size in _dp_sizes:
                        cfg.config.maximum_potential_data_points_in_target_table = _size
                        try:
                            find_formula_smartly_selected.run()
                            break
                        except ContextTooLargeError as e:
                            print(f"[CONTEXT_TOO_LARGE] {_size} data points → {e}")
                            llm_layer._log_warning(f"CONTEXT_TOO_LARGE | data_points={_size} | {e}")
                            from src.core.timeout_profiler import log_timeout
                            log_timeout("CONTEXT_TOO_LARGE", 0, 0, str(e)[:200])
                            reported_accuracy_list.clear()
                            find_formula_smartly_selected.already_found = False
                            find_formula_smartly_selected.reported_accuracy_sequence = 0
                            llm_layer.chat_histories.clear()
                            llm_layer.chat_histories["global"] = []
                    else:
                        llm_layer._log_warning("CONTEXT_TOO_LARGE | all data point sizes failed — skipping column")
                        report_accuracy(-2, "context_too_large", "", "", 1)
                    cfg.config.maximum_potential_data_points_in_target_table = _original_dp
                elif strategy == 6:
                    zero_shot.run(1)
                elif strategy == 7:
                    zero_shot.run(3)
                elif strategy == 8:
                    zero_shot.run(2)
            elif step == 6:
                pass
    except Exception:
        tb = traceback.format_exc()
        error_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "column": f"{target_database_name}.{target_table_name}.{target_column_name}",
            "model": cfg.config.model,
            "prompt_template": cfg.config.prompt_template,
            "error_type": type(sys.exc_info()[1]).__name__,
            "traceback": tb,
        }
        error_file = args.work_space + "/errors.jsonl"
        with open(error_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(error_record) + "\n")
        print(f"\n[ERROR] Crash on {error_record['column']} — logged to {error_file}\n{tb}")
        sys.exit(1)
    finally:
        try:
            from src.steps.formula_common import drop_sample_table
            drop_sample_table()
        except Exception:
            pass
        try:
            from src.core.db_layer import disconnect_from_db
            disconnect_from_db()
        except Exception:
            pass

    end_timestamp = time.perf_counter() * 1000



    execution_time = end_timestamp - start_timestamp

    report.execution_time = execution_time
    _write_column_diagnosis()
    write_the_report(bulk_experiments_file_path)


if __name__ == "__main__":
    main()
