
import csv
import os
import time
from datetime import datetime
from pathlib import Path
from dataclasses import asdict

import yaml

import configparser

from dataclasses import dataclass

from src.core import file_utils
from src.core import llm_layer
from src.core import db_layer

from src.core.config import config


@dataclass
class Report:

    target_database: str = ""
    target_table: str = ""
    target_column: str = ""

    execution_time: int = 0
    
    is_computed: bool = False

    accuracy: float = 0.0

    number_of_shared_data_points: int = 0
    data_sharing_number_of_tries: int = 0
    data_sharing_selected_try_number: int = 0
    size_number_of_shared_data_points_in_tockens: int = 0

    size_of_schema_prompt_text_in_bytes: int = 0
    size_of_schema_prompt_text_in_tockens: int = 0

    size_of_all_database_columns_metadata_prompt_text_in_bytes: int = 0
    size_of_all_database_columns_metadata_prompt_text_in_tockens: int = 0

    size_of_all_database_columns_distinct_values_prompt_text_in_bytes: int = 0
    size_of_all_database_columns_distinct_values_prompt_text_in_tockens: int = 0

    size_of_all_database_random_rows_prompt_text_in_bytes: int = 0
    size_of_all_database_random_rows_prompt_text_in_tockens: int = 0

    size_of_all_related_data_points_sharing_prompt_text_in_bytes: int = 0
    size_of_all_related_data_points_sharing_prompt_text_in_tockens: int = 0

    size_of_metadata_and_data_sharing_prompt_text_in_bytes: int = 0
    size_of_metadata_and_data_sharing_prompt_text_in_tockens: int = 0


    schema_sending_time: int = 0
    preparing_all_database_columns_metadata_time: int = 0
    preparing_all_database_columns_distinct_values_time: int = 0
    preparing_all_database_random_rows_time: int = 0
    preparing_data_sharing_time: int = 0

    validation_sql_query: str = ""
    sql_query: str = ""
    simplified_sql_query: str = ""

    bulk_experiments_file_path: str = ""


report = Report()


reported_accuracy_list = []

program_start_time = time.perf_counter()

def report_accuracy(accuracy: float, textual_formula: str, computation_sql_query: str, meta_data: str, reported_accuracy_sequence: int, is_semantically_implausible: bool = False, full_validation: bool = True, plausibility_timestamp: datetime = None):
    elapsed_ms = (time.perf_counter() - program_start_time) * 1000 - llm_layer._rate_limiter.total_wait_ms
    in_tokens  = llm_layer.llm_metrics.actual_in_tokens  or llm_layer.llm_metrics.number_of_chars_to_LLM   // 4
    out_tokens = llm_layer.llm_metrics.actual_out_tokens or llm_layer.llm_metrics.number_of_chars_from_LLM // 4
    llm_calls  = llm_layer.llm_metrics.number_of_calls_to_LLM
    total_llm_time = llm_layer.llm_metrics.total_LLM_time
    db_queries = db_layer.db_metrics.number_of_calls_to_db
    non_guaranteed_queries = db_layer.db_metrics.number_of_non_guarenteed_queries
    guaranteed_queries     = db_layer.db_metrics.number_of_guarenteed_queries
    total_db_time          = db_layer.db_metrics.total_db_time
    db_errors              = db_layer.db_metrics.number_of_errors_of_non_guarenteed_queries
    reported_accuracy_list.append((accuracy, textual_formula, computation_sql_query, meta_data, reported_accuracy_sequence, elapsed_ms, in_tokens, out_tokens, llm_calls, total_llm_time, db_queries, non_guaranteed_queries, guaranteed_queries, total_db_time, db_errors, is_semantically_implausible, full_validation, plausibility_timestamp))

def write_the_report(bulk_experiments_file_path: str = ""):
    
    print(f"Write the report for {config.target_database_name}.{config.target_table_name}.{config.target_column_name}")

    sorted_reported_accuracy_list = sorted(
        reported_accuracy_list,
        key=lambda x: x[0],  # accuracy is the first element
        reverse=True         # descending order
    )

    reported_accuracy_file = config.work_space + f"/reported_accuracy_{config.target_database_name}_{config.target_table_name}_{config.target_column_name}.csv"

    headers = ["accuracy", "textual_formula", "computation_sql_query", "meta_data", "reported_accuracy_sequence", "elapsed_time_ms", "in_tokens", "out_tokens", "llm_calls", "total_llm_time", "db_queries", "non_guaranteed_queries", "guaranteed_queries", "total_db_time", "db_errors", "is_semantically_implausible", "full_validation", "plausibility_timestamp"]

    with open(reported_accuracy_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    with open(reported_accuracy_file, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for accuracy, textual_formula, computation_sql_query, meta_data, reported_accuracy_sequence, elapsed_ms, in_tokens, out_tokens, llm_calls, total_llm_time, db_queries, non_guaranteed_queries, guaranteed_queries, total_db_time, db_errors, is_semantically_implausible, full_validation, plausibility_timestamp in sorted_reported_accuracy_list:
            ts_str = plausibility_timestamp.strftime("%Y-%m-%d %H:%M:%S.%f") if plausibility_timestamp else ""
            writer.writerow([accuracy, textual_formula, computation_sql_query, meta_data, reported_accuracy_sequence, round(elapsed_ms, 2), in_tokens, out_tokens, llm_calls, total_llm_time, db_queries, non_guaranteed_queries, guaranteed_queries, total_db_time, db_errors, is_semantically_implausible, full_validation, ts_str])

    return
    
    report_csv_file = config.work_space + f"/report.csv"

    if not file_utils.is_file_exists(report_csv_file):
        file_utils.create_file_if_not_exists(report_csv_file) 

        # ✅ Write headers when creating the file
        headers = [
            "target_database", "target_table", "target_column", "execution_time", 
            "is_computed", "accuracy", "number_of_shared_data_points",
            "data_sharing_number_of_tries", "data_sharing_selected_try_number",
            "size_number_of_shared_data_points_in_tockens",
            "size_of_schema_prompt_text_in_bytes", "size_of_schema_prompt_text_in_tockens",
            "size_of_all_database_columns_metadata_prompt_text_in_bytes",
            "size_of_all_database_columns_metadata_prompt_text_in_tockens",
            "size_of_all_database_columns_distinct_values_prompt_text_in_bytes",
            "size_of_all_database_columns_distinct_values_prompt_text_in_tockens",
            "size_of_all_database_random_rows_prompt_text_in_bytes",
            "size_of_all_database_random_rows_prompt_text_in_tockens",
            "size_of_all_related_data_points_sharing_prompt_text_in_bytes",
            "size_of_all_related_data_points_sharing_prompt_text_in_tockens",
            "size_of_metadata_and_data_sharing_prompt_text_in_bytes",
            "size_of_metadata_and_data_sharing_prompt_text_in_tockens",
            "schema_sending_time", "preparing_all_database_columns_metadata_time",
            "preparing_all_database_columns_distinct_values_time",
            "preparing_all_database_random_rows_time", "preparing_data_sharing_time",
            "validation_sql_query", "sql_query", "simplified_sql_query"
        ]

        with open(report_csv_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    # ✅ Append report values
    row = list(asdict(report).values())
    with open(report_csv_file, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)

    
    if bulk_experiments_file_path != "":

        if os.path.getsize(bulk_experiments_file_path) == 0:

            headers = ["data_sharing_schema_and_diagnoses", "data_sharing_statistics_and_distinct_values", "data_sharing_random_rows_of_each_table", "data_sharing_selected_data_points", "target_database", "target_table", "target_column", "is_computed", "accuracy", "sql_query"]

            with open(bulk_experiments_file_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

        target_database = row[0]
        target_table = row[1]
        target_column = row[2]
        is_computed = row[4]
        accuracy = row[5]
        sql_query = row[28]

        row = [config.data_sharing_schema_and_diagnoses, config.data_sharing_statistics_and_distinct_values, config.data_sharing_random_rows_of_each_table, config.data_sharing_selected_data_points, target_database, target_table, target_column, is_computed, accuracy, sql_query]
        with open(bulk_experiments_file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)







def write_todo_report(msg: str, is_with_exist: bool = True):
    print("************************************************************************************************")
    print(f"{config.target_database_name}.{config.target_table_name}.{config.target_column_name}")
    print(msg)
    print("************************************************************************************************")
    if is_with_exist:
        exit()