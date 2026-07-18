"""Step 5 module"""
import heapq
import logging
import re
import time
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Tuple

from src.core.join_builder import find_join_route_for_multiple_target_tables_with_composites, find_join_route_with_composites
from src.core.db_functions import execute_diagnoses_query_and_result_as_string, execute_validation_query_and_get_accuracy, get_filtered_columns_names_of_a_table, get_join_condition_as_dict, get_pk_columns_names_of_a_table, get_tables_dependencies_in_the_database
from src.core.utils import get_json_object, remove_substring
logging.basicConfig(level=logging.INFO)

from src.core import db_layer, file_utils, llm_layer
from src.core.llm_layer import ContextTooLargeError
from src.core import prompt_templates as pt

from src.steps.collect_statistical_metadata import tables_info

from src.core.config import config

from src.core import connect_to_db, disconnect_from_db, execute_query_and_get_results_with_headers

from src.core.report_util import report, write_todo_report, report_accuracy
from src.steps.formula_common import load_database_columns_metadata, load_database_distinct_values, load_database_sample_rows, load_database_schema, load_table_description, prepare_validation_sql_query, validate_and_prepare_computation_sql, is_computed_column, is_formula_semantically_plausible, write_metrics_to_csv, build_data_points_condition_sql, create_sample_table, process_llm_candidate

work_space = None
column_logical_type = None

number_of_pks_in_target_table = 0
names_of_pk_columns_of_target_table = []
    
already_found = False

_SELECTOR_LARGE_TABLE_THRESHOLD = 100_000


def _fits_context(prompt_text: str) -> bool:
    """Return True when the estimated token count fits within the model's context window."""
    return len(prompt_text) // 4 <= config.max_context_tokens


def find_formula_of_a_single_table_scope_chaining_table_computed_value():

    global already_found
    
    found = False

    prompt_text = pt.prompt_identify_chaining_table_structure(target_table_description)

    chaining_table_info = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(chaining_table_info)

    if data is None or "chaining_table_info" not in data:
        return

    if len(data["chaining_table_info"]) == 0:
        return 
    
    # Access the first (and only) object inside chaining_table_info
    info = data["chaining_table_info"][0]

    # Extract the values into separate variables
    grouping_columns = info["grouping_columns"]                    # list of strings
    chaining_columns = info["chaining_columns"]                    # list of strings   

    chaining_columns_str = ""
    for chaining_column in chaining_columns:
        chaining_columns_str += f"{chaining_column}, "
    chaining_columns_str = chaining_columns_str[:-2]

    grouping_columns_str = ""
    if len(grouping_columns) == 1:

        for grouping_column in grouping_columns: 
            grouping_columns_str += f"`{grouping_column}`, "
        grouping_columns_str = grouping_columns_str[:-2]

        # Get data points of groups that do not have missing rows (broken chains), halving if the prompt would overflow context.

        n_pts = config.maximum_potential_data_points_in_target_table
        while True:
            sql_query = f"select * from (select {grouping_columns_str} from (SELECT {grouping_columns_str}, count(*) cnt from `{config.target_table_name}` "
            sql_query += f" where {grouping_columns_str} not in (select distinct {grouping_columns_str} where `{config.target_column_name}` is null) "
            sql_query += f"group by {grouping_columns_str}) a where cnt > 3 order by cnt) a limit {n_pts};"

            #print(f"data points selection sql_query: {sql_query}")


            result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)


            header = headers[0]
            values = [str(row[0]) for row in result]  # ["10087", "10055", "10019"]

            chaining_table_group_condition_str = f"{header} in ({', '.join(values)})"

            sql_query = f" select * from `{config.target_table_name}` where {chaining_table_group_condition_str} order by {grouping_columns_str}, {chaining_columns_str};"


            data_for_sharing_with_LLM, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)


            data_for_sharing_with_LLM_str = f"Columns names: {headers}, Sample rows: {data_for_sharing_with_LLM}"

            prompt_text = pt.prompt_chaining_table_candidate_formula(target_table_description, data_for_sharing_with_LLM_str, grouping_columns, chaining_columns)

            if _fits_context(prompt_text) or n_pts <= 2:
                break
            n_pts = max(2, n_pts // 2)
            llm_layer._log_warning(f"S4_CONTEXT_REDUCE | chaining | halved data points to {n_pts}")

        response = llm_layer.get_response(prompt_text, "any", False, False)

        data = get_json_object(response)

        if data is None or "candidate_formulas" not in data:
            return

        for candidate_formula in data["candidate_formulas"]:
            try:

                used_formula = candidate_formula["textual_formula"]
                used_columns_for_the_formula = candidate_formula["columns"]

                formula_based_on_data_sharing = used_formula

                #print(f"formula_based_on_data_sharing: {formula_based_on_data_sharing}")

                prompt_text = pt.prompt_generate_sql_for_chaining_table(target_table_description, data_for_sharing_with_LLM_str, formula_based_on_data_sharing, grouping_columns, chaining_columns, chaining_columns_str, number_of_pks_in_target_table, names_of_pk_columns_of_target_table)

                llm_layer.flush_chat_history("single_table_chaining_table")
                response = llm_layer.get_response(prompt_text, "single_table_chaining_table")

                match = re.search(r"```sql(.*?)```", response, re.DOTALL)
                computation_sql_query = match.group(1).strip() if match else None

                is_plausible, plausibility_ts = is_formula_semantically_plausible(formula_based_on_data_sharing, computation_sql_query or "")
                is_implausible = not is_plausible

                is_valid, computation_sql_query, validation_sql_query, diagnoses_sql_query, is_partial = validate_and_prepare_computation_sql(computation_sql_query, column_logical_type, "single_table_chaining_table")
                if not is_valid:
                    continue

                accuracy, validation_sql_query = execute_validation_query_and_get_accuracy(validation_sql_query)

                #print(f"************************************************************************************************")
                #print(f"Accuracy = {accuracy}. (chaining table)")
                #print(f"Formula {formula_based_on_data_sharing}. (chaining table)")
                #print(f"Computation SQL query {computation_sql_query}. (chaining table)")
                global reported_accuracy_sequence
                reported_accuracy_sequence += 1
                report_accuracy(accuracy, formula_based_on_data_sharing, computation_sql_query, f"[chaining_table], grouping_columns({grouping_columns}), chaining_columns({chaining_columns})", reported_accuracy_sequence, is_implausible, full_validation=not is_partial, plausibility_timestamp=plausibility_ts)
                #print(f"************************************************************************************************")

                if accuracy >= config.cleaning_threshold:
                    already_found = config.early_stopping
                    return

                prompt_text = pt.prompt_classify_chain_direction()
                response = llm_layer.get_response(prompt_text, "single_table_chaining_table", False, True)
                data = get_json_object(response)

                current = "next"
                if data and "direction" in data and data["direction"] == "previous":
                    current = "previous"
                
                if accuracy >= config.cleaning_threshold:
                    found = True
                else:
                    diagnoses_sql_query_result_str = execute_diagnoses_query_and_result_as_string(diagnoses_sql_query)

                    prompt_text = pt.prompt_diagnose_chaining_formula_smartly(
                        config.target_column_name,
                        config.target_table_name,
                        target_table_description,
                        current,
                        data_for_sharing_with_LLM_str,
                        formula_based_on_data_sharing,
                        accuracy,
                        diagnoses_sql_query_result_str,
                        grouping_columns,
                        chaining_columns
                    )

                    formula_diagnoses = llm_layer.get_response(prompt_text, "any", False, False)

                    data = get_json_object(formula_diagnoses)

                    #print(f"data: {data}")

                    if data is None or "is_catched" not in data:
                        continue

                    if "yes" not in data["is_catched"].lower():
                        return False

                    prompt_text = pt.prompt_corrected_sql_for_chaining_table(
                        config.target_column_name,
                        config.target_table_name,
                        target_table_description,
                        data_for_sharing_with_LLM_str,
                        formula_based_on_data_sharing,
                        data["corrected_formula"],
                        data["cause_of_error"],
                        grouping_columns,
                        chaining_columns,
                        chaining_columns_str,
                        number_of_pks_in_target_table,
                        names_of_pk_columns_of_target_table
                    )

                    llm_layer.flush_chat_history("single_table_chaining_table_diagnoses")
                    response = llm_layer.get_response(prompt_text, "single_table_chaining_table_diagnoses")

                    match = re.search(r"```sql(.*?)```", response, re.DOTALL)
                    computation_sql_query = match.group(1).strip() if match else None

                    is_valid, computation_sql_query, validation_sql_query, diagnoses_sql_query, _is_partial_diag = validate_and_prepare_computation_sql(computation_sql_query, column_logical_type, "single_table_chaining_table_diagnoses")
                    if not is_valid:
                        continue

                    #print(f"validation_sql_query after diagnoses: {validation_sql_query}")

                    accuracy_after_diagnoses, validation_sql_query = execute_validation_query_and_get_accuracy(validation_sql_query)

                    #print(f"************************************************************************************************")
                    #print(f"Accuracy after diagnoses = {accuracy_after_diagnoses}. (chaining table)")
                    #print(f"************************************************************************************************")

                    if accuracy_after_diagnoses > accuracy:
                        found = True
                        used_formula = data["corrected_formula"]
                        used_columns_for_the_formula = data["columns"]
                        accuracy = accuracy_after_diagnoses
                   
                if config.target_column_name in used_columns_for_the_formula:
                    used_columns_for_the_formula.remove(config.target_column_name)

                for grouping_column in grouping_columns:
                    if grouping_column in used_columns_for_the_formula:
                        used_columns_for_the_formula.remove(grouping_column)

                return
        
            except ContextTooLargeError as e:
                print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
                llm_layer._log_warning(f"CONTEXT_TOO_LARGE | chaining candidate skipped | {e}")
                continue
            except Exception as e:
                print(f"[ERROR] chaining candidate skipped: {e}")
                llm_layer._log_warning(f"CANDIDATE_ERROR | chaining candidate skipped | {e}")
                continue
    else: # TODO
        return False

    return found

def find_formula_of_a_single_table_scope_hierarchical_table_computed_value():

    global already_found
    
    found = False

    prompt_text = pt.prompt_hierarchical_parent_reference_smartly(target_table_description, names_of_pk_columns_of_target_table)

    hierarchical_table_info = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(hierarchical_table_info)

    if data is None or "parent_reference_columns" not in data:
        return

    self_join_condition = " on "
    names_of_pk_columns_of_target_table_as_parent_table_str = ""
    number_of_identifier_keys = 0
    parent_reference_columns_list = []
    hierarchical_columns_str = ""
    for ref in data["parent_reference_columns"]:
        for _, values in ref.items():
            number_of_identifier_keys += 1
            parent_reference_columns_list.append((values[0], values[1]))
            hierarchical_columns_str += f"{values[0]}, {values[1]}, "
            self_join_condition += f" parent_table.`{values[0]}` = child_table.`{values[1]}` and "
            names_of_pk_columns_of_target_table_as_parent_table_str += "parent_table.`" + values[0] + "`, "
    hierarchical_columns_str = hierarchical_columns_str[:-2]
    self_join_condition = self_join_condition[:-5]
    names_of_pk_columns_of_target_table_as_parent_table_str = names_of_pk_columns_of_target_table_as_parent_table_str[:-2]

    n_pts = config.maximum_potential_data_points_in_target_table
    while True:
        sql_query = f"select {names_of_pk_columns_of_target_table_as_parent_table_str} from ("
        sql_query += f"select {names_of_pk_columns_of_target_table_as_parent_table_str}, count(*) children_number "
        sql_query += f"from `{config.target_table_name}` parent_table inner join `{config.target_table_name}` child_table {self_join_condition} "
        sql_query += f"group by {names_of_pk_columns_of_target_table_as_parent_table_str} having count(*) > 2 and count(*) < 5 "
        sql_query += f") parent_table limit {n_pts} "

        result, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

        if len(result) < 2:
            sql_query = f"select {names_of_pk_columns_of_target_table_as_parent_table_str} from ("
            sql_query += f"select {names_of_pk_columns_of_target_table_as_parent_table_str}, count(*) children_number "
            sql_query += f"from `{config.target_table_name}` parent_table inner join `{config.target_table_name}` child_table {self_join_condition} "
            sql_query += f"group by {names_of_pk_columns_of_target_table_as_parent_table_str} having count(*) > 1 and count(*) < 20 "
            sql_query +=") parent_table limit 6 "

            result, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

            if len(result) < 2:
                sql_query = f"select {names_of_pk_columns_of_target_table_as_parent_table_str} from ("
                sql_query += f"select {names_of_pk_columns_of_target_table_as_parent_table_str}, count(*) children_number "
                sql_query += f"from `{config.target_table_name}` parent_table inner join `{config.target_table_name}` child_table {self_join_condition} "
                sql_query += f"group by {names_of_pk_columns_of_target_table_as_parent_table_str} having count(*) > 1 and count(*) < 50 "
                sql_query +=") parent_table limit 3 "

                result, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

            if len(result) < 2:
                sql_query = f"select {names_of_pk_columns_of_target_table_as_parent_table_str} from ("
                sql_query += f"select {names_of_pk_columns_of_target_table_as_parent_table_str}, count(*) children_number "
                sql_query += f"from `{config.target_table_name}` parent_table inner join `{config.target_table_name}` child_table {self_join_condition} "
                sql_query += f"group by {names_of_pk_columns_of_target_table_as_parent_table_str} having count(*) > 1 "
                sql_query +=") parent_table limit 2 "

                result, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

                if len(result) < 2:
                    return False

        condition_str = " where "
        if number_of_identifier_keys == 1:

            condition_body_str = f" in ("
            for r in result:
                condition_body_str += f"{r[0]}, "
            condition_body_str = condition_body_str[:-2]
            condition_body_str += ")"

            for ref in data["parent_reference_columns"]:
                for _, values in ref.items():
                    condition_str += f"{values[0]} {condition_body_str} or {values[1]} {condition_body_str}"

        elif number_of_identifier_keys > 1: #TODO
            return False

        columns_names_str = get_filtered_columns_names_of_a_table(config.target_table_name)
        sql_query = f"select {columns_names_str} from `{config.target_table_name}` {condition_str} "

        data_for_sharing_with_LLM, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)

        data_for_sharing_with_LLM_str = f"Columns names: {headers}, Sample rows: {data_for_sharing_with_LLM}"

        if len(parent_reference_columns_list) == 0:
            write_todo_report("In hierarchical table, no parent-reference-columns and no parent-referencing-columns are found")

        prompt_text = pt.prompt_hierarchical_candidate_formula_smartly(target_table_description, names_of_pk_columns_of_target_table, parent_reference_columns_list, data_for_sharing_with_LLM_str)

        if _fits_context(prompt_text) or n_pts <= 2:
            break
        n_pts = max(2, n_pts // 2)
        llm_layer._log_warning(f"S4_CONTEXT_REDUCE | hierarchical | halved data points to {n_pts}")

    response = llm_layer.get_response(prompt_text, "any", False, False)

    #print("##################################################################")
    #print(response)
    #print("##################################################################")

    data = get_json_object(response)

    if data is None or "candidate_formulas" not in data:
        return

    for candidate_formula in data["candidate_formulas"]:
        try:
            formula_based_on_data_sharing = candidate_formula["textual_formula"]

            prompt_text = pt.prompt_generate_sql_for_hierarchical_table(target_table_description, names_of_pk_columns_of_target_table, parent_reference_columns_list, data_for_sharing_with_LLM_str, formula_based_on_data_sharing, number_of_pks_in_target_table)

            llm_layer.flush_chat_history("single_table_hierarchical_table")
            response = llm_layer.get_response(prompt_text, "single_table_hierarchical_table")

            match = re.search(r"```sql(.*?)```", response, re.DOTALL)
            computation_sql_query = match.group(1).strip() if match else None

            global reported_accuracy_sequence
            reported_accuracy_sequence += 1

            parent_reference_columns_str = ", ".join(
                f"{child} -> {parent}" for parent, child in parent_reference_columns_list
            )
            best_accuracy, _, should_stop = process_llm_candidate(
                formula_based_on_data_sharing, computation_sql_query, column_logical_type,
                "single_table_hierarchical_table",
                f"[hierarchical_table], (child.referencing_column -> parent.reference_column) ({parent_reference_columns_str})",
                reported_accuracy_sequence,
            )

            if should_stop:
                already_found = config.early_stopping
                return True

            found = best_accuracy >= config.cleaning_threshold
            return found

        except ContextTooLargeError as e:
            print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
            llm_layer._log_warning(f"CONTEXT_TOO_LARGE | hierarchical candidate skipped | {e}")
            continue
        except Exception as e:
            print(f"[ERROR] hierarchical candidate skipped: {e}")
            llm_layer._log_warning(f"CANDIDATE_ERROR | hierarchical candidate skipped | {e}")
            continue
def is_count_or_exist():

    prompt_text = pt.prompt_is_count_or_exist_smartly(
        config.target_column_name,
        config.target_table_name,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)
    data = get_json_object(response)
    if data and "is_count_or_exist" in data:
        return data["is_count_or_exist"].strip().lower() == "yes"
    return "yes" in response.lower()


def get_minimal_distinct_values(table_name: str, column_name: str, number_of_rows: int):

    pk_columns_names = get_pk_columns_names_of_a_table(table_name)
    pk_columns_str = ""
    for pk_col in pk_columns_names:
        pk_columns_str += f"`{table_name}`.{pk_col}, "
    pk_columns_str = pk_columns_str[:-2]
    
    sql_query = f"""
    SELECT {pk_columns_str}, {column_name}
    FROM {table_name}
    JOIN (
        SELECT DISTINCT {column_name}
        FROM {table_name}
        ORDER BY {column_name}
        LIMIT {number_of_rows}
    ) AS d
    ON {table_name}.{column_name} = d.{column_name}
    """

    """
    SELECT x.col_1, x.col_2
    FROM X x
    WHERE x.col_1 = (
        SELECT x2.col_1
        FROM X x2
        WHERE x2.col_2 = x.col_2
        ORDER BY RAND()
        LIMIT 1
    )
    GROUP BY x.col_2;
    """

    # pk_columns is a list of PK column names (supports composite PK)
    # Example: ["id"]  or  ["order_id", "line_no"]

    pk_columns_str = ", ".join(pk_columns_names)

    # Build a composite key expression for tie-breaking, e.g. CONCAT(order_id,'|',line_no)
    if len(pk_columns_names) == 1:
        composite_pk = pk_columns_names[0]
    else:
        composite_pk = "CONCAT(" + ", '|', ".join(pk_columns_names) + ")"

    sql_query = f"""
    SELECT {pk_columns_str}
    FROM {table_name}
    JOIN (
        SELECT {column_name}, MIN({composite_pk}) AS min_pk
        FROM {table_name}
        GROUP BY {column_name}
        ORDER BY {column_name}
        LIMIT {number_of_rows}
    ) AS d
    ON {table_name}.{column_name} = d.{column_name}
    AND {composite_pk} = d.min_pk;
    """

    result, header, _, _ = execute_query_and_get_results_with_headers(sql_query)

    return result, header

def find_formula_of_count_or_exist_computed_column_on_a_given_table_without_data_sharing(given_table_name: str, target_table_and_join_conditions_str: str):

    global already_found

    names_of_pk_columns_of_target_table_str = ""
    for name_of_pk_column_of_target_table in names_of_pk_columns_of_target_table:
        names_of_pk_columns_of_target_table_str += f"{config.target_table_name}.{name_of_pk_column_of_target_table}, "
    names_of_pk_columns_of_target_table_str = names_of_pk_columns_of_target_table_str[:-2]
    
    computation_sql_query = f"select {names_of_pk_columns_of_target_table_str}, {config.target_table_name}.{config.target_column_name} actual_value, Count(*) computed_value from {target_table_and_join_conditions_str} "
    computation_sql_query += f"group by {names_of_pk_columns_of_target_table_str}, {config.target_table_name}.{config.target_column_name}"

    validation_sql_query, _ = prepare_validation_sql_query(computation_sql_query, column_logical_type)

    try:
        accuracy, validation_sql_query = execute_validation_query_and_get_accuracy(validation_sql_query)
    except Exception as e:
        print(f"SQL execution error (skipping candidate): {e}")
        return False

    #print(f"************************************************************************************************")
    #print(f"Accuracy {config.target_column_name}` = {accuracy}. (count or exist without data sharing)")
    #print(f"Computation SQL query {computation_sql_query}. (count or exist without data sharing)")
    #print(f"************************************************************************************************")
    
    global reported_accuracy_sequence
    reported_accuracy_sequence += 1
    report_accuracy(accuracy, "NaN", computation_sql_query, f"[count_or_exist without data sharing], given_table_name = {given_table_name}", reported_accuracy_sequence)

    if accuracy >= config.cleaning_threshold:
        already_found = config.early_stopping
        return True
    
    return False


def find_formula_of_count_or_exist_computed_column_on_a_given_table(given_table_name: str):
    
    global already_found

    print(f"Try with {given_table_name} table. ")

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])
    
    result = find_join_route_with_composites(
        dependencies=dependencies,
        source_table=config.target_table_name,
        target_table=given_table_name,
    )

    if not result:
        #TODO Ask LLM to ptovide the join path
        print("No join path found - Ask LLM to find the join path.")
        return False
    else:

        target_table_and_join_conditions_str = result["join_chain_sql"]

        tables_in_path = result["tables_in_path"]

        if given_table_name == config.target_table_name:
            target_table_and_join_conditions_str = given_table_name

        found = find_formula_of_count_or_exist_computed_column_on_a_given_table_without_data_sharing(given_table_name, target_table_and_join_conditions_str)

        if already_found:
            return True

        if found:
            #print("****************************************************************************")
            #print("Found without data sharing")
            #print("****************************************************************************")
            return True
        
        #print("****************************************************************************")
        #print("Not found without data sharing - we must share data")
        #print("****************************************************************************")
        
        n_pts = config.maximum_potential_data_points_in_target_table
        while True:
            results, headers = get_minimal_distinct_values(config.target_table_name, config.target_column_name, n_pts)

            data_points_condition_sql = build_data_points_condition_sql(config.target_table_name, headers, results)

            filtered_columns_in_target_table = get_filtered_columns_names_of_a_table(config.target_table_name, config.target_table_name)
            sql_query_for_data_points_in_target_table = f"select distinct {filtered_columns_in_target_table} from {target_table_and_join_conditions_str} where {data_points_condition_sql} "

            data_points_in_target_table, header_of_data_points_in_target_table, _, _ = execute_query_and_get_results_with_headers(sql_query_for_data_points_in_target_table)

            #print(f"header_of_data_points_in_target_table: {header_of_data_points_in_target_table}")
            #print(f"data_points_in_target_table: {data_points_in_target_table}")

            data_for_sharing_with_LLM_str = f"Here are some sample data of table {config.target_table_name}: Columns names: {header_of_data_points_in_target_table}, Sample rows: {data_points_in_target_table}. "

            filtered_columns_in_the_other_table = get_filtered_columns_names_of_a_table(given_table_name, given_table_name)
            sql_query_for_data_points_in_the_other_table = f"select distinct {filtered_columns_in_the_other_table} from {target_table_and_join_conditions_str} where {data_points_condition_sql} "

            #print(f"sql_query: {sql_query_for_data_points_in_the_other_table}")

            data_points_in_the_other_table, header_of_data_points_in_the_other_table, _, _ = execute_query_and_get_results_with_headers(sql_query_for_data_points_in_the_other_table)

            if len(data_points_in_the_other_table) > 300: # data is very huge e.g. ErgastF1.constructorStandings.constructorStandingsId
                #print("##################################################################################################################")
                #print("Data is huge!")
                #print(f"len(data_points_in_the_other_table): {len(data_points_in_the_other_table)}")
                #print("##################################################################################################################")

                pk_columns_names = get_pk_columns_names_of_a_table(config.target_table_name)
                pk_columns_str = ""
                for pk_col in pk_columns_names:
                    pk_columns_str += f"`{config.target_table_name}`.{pk_col}, "
                pk_columns_str = pk_columns_str[:-2]

                rows_number = 3
                found_data_points = 0

                results = []
                headers = []

                found_cc = []
                total_number_of_rows = 0

                while rows_number < 100 and total_number_of_rows < 300 and found_data_points < n_pts:

                    sql_query = f"select {pk_columns_str}, `{config.target_table_name}`.`{config.target_column_name}` from {target_table_and_join_conditions_str} group by {pk_columns_str} having count(*) = {rows_number} limit 1 "

                    if len(found_cc) > 0:

                        found_cc_str = ""
                        for f_cc in found_cc:
                            found_cc_str += f"{f_cc}, "
                        found_cc_str = found_cc_str[:-2]

                        sql_query = f"select {pk_columns_str}, `{config.target_table_name}`.`{config.target_column_name}` from {target_table_and_join_conditions_str} "
                        sql_query += f" where `{config.target_table_name}`.`{config.target_column_name}` not in ({found_cc_str}) "
                        sql_query += f"group by {pk_columns_str} having count(*) = {rows_number} limit 1 "

                    #print(f"sql_query with count = {rows_number}: {sql_query}")

                    results_local, headers_local, _, _ = execute_query_and_get_results_with_headers(sql_query)

                    headers_local.pop()

                    if len(results_local) > 0:

                        results_local_list = list(results_local[0])

                        last = results_local_list.pop()

                        results_local[0] = tuple(results_local_list)

                        found_cc.append(last)

                        found_data_points += 1

                        if len(results_local) + len(results) < 300:
                            results.extend(results_local)
                            total_number_of_rows += rows_number
                        else:
                            break

                        if len(headers) == 0:
                            headers.extend(headers_local)

                    rows_number += 1

                #print(f"headers: {headers}")
                #print(f"results: {results}")

                data_points_condition_sql = build_data_points_condition_sql(config.target_table_name, headers, results)

                filtered_columns_in_target_table = get_filtered_columns_names_of_a_table(config.target_table_name, config.target_table_name)
                sql_query_for_data_points_in_target_table = f"select distinct {filtered_columns_in_target_table} from {target_table_and_join_conditions_str} where {data_points_condition_sql} "

                #print(f"sql_query: {sql_query_for_data_points_in_target_table}")

                data_points_in_target_table, header_of_data_points_in_target_table, _, _ = execute_query_and_get_results_with_headers(sql_query_for_data_points_in_target_table)

                #print(f"header_of_data_points_in_target_table: {header_of_data_points_in_target_table}")
                #print(f"data_points_in_target_table: {data_points_in_target_table}")

                data_for_sharing_with_LLM_str = f"Here are some sample data of table {config.target_table_name}: Columns names: {header_of_data_points_in_target_table}, Sample rows: {data_points_in_target_table}. "

                for table_in_path in tables_in_path:

                    if table_in_path == config.target_table_name:
                        continue

                    filtered_columns_in_the_other_table = get_filtered_columns_names_of_a_table(table_in_path, table_in_path)
                    sql_query_for_data_points_in_the_other_table = f"select distinct {filtered_columns_in_the_other_table} from {target_table_and_join_conditions_str} where {data_points_condition_sql} "

                    #print(f"sql_query: {sql_query_for_data_points_in_the_other_table}")

                    data_points_in_the_other_table, header_of_data_points_in_the_other_table, _, _ = execute_query_and_get_results_with_headers(sql_query_for_data_points_in_the_other_table)

                    data_for_sharing_with_LLM_str += f"Here are some sample data of table {table_in_path}: Columns names: {header_of_data_points_in_the_other_table}, Sample rows: {data_points_in_the_other_table}. "

            #print(data_for_sharing_with_LLM_str)

            prompt_text = pt.prompt_count_or_exist_with_data_sharing(
                config.target_column_name,
                config.target_table_name,
                given_table_name,
                target_table_description,
                data_for_sharing_with_LLM_str,
                number_of_pks_in_target_table,
                names_of_pk_columns_of_target_table
            )

            if _fits_context(prompt_text) or n_pts <= 2:
                break
            n_pts = max(2, n_pts // 2)
            llm_layer._log_warning(f"S4_CONTEXT_REDUCE | count_or_exist | halved data points to {n_pts}")

        llm_layer.flush_chat_history("finding_count_or_exists_formula_across_tables")

        response = llm_layer.get_response(prompt_text, "finding_count_or_exists_formula_across_tables")

        data = get_json_object(response)

        if data is None or "candidate_formulas" not in data:
            return False

        for candidate_formula in data["candidate_formulas"]:
            try:
                llm_layer.flush_chat_history("finding_count_or_exists_formula_across_tables")
                computation_sql_query = candidate_formula["computation_sql_query"]
                textual_formula = candidate_formula.get("textual_formula", "NaN")

                global reported_accuracy_sequence
                reported_accuracy_sequence += 1

                _, _, should_stop = process_llm_candidate(
                    textual_formula, computation_sql_query, column_logical_type,
                    "finding_count_or_exists_formula_across_tables",
                    f"[count_or_exist with data sharing], given_table_name = {given_table_name}",
                    reported_accuracy_sequence,
                    use_sample=True,
                )

                if should_stop:
                    already_found = config.early_stopping
                    return True
        


    


            except ContextTooLargeError as e:
                print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
                llm_layer._log_warning(f"CONTEXT_TOO_LARGE | count_or_exist candidate skipped | {e}")
                continue
            except Exception as e:
                print(f"[ERROR] count_or_exist candidate skipped: {e}")
                llm_layer._log_warning(f"CANDIDATE_ERROR | count_or_exist candidate skipped | {e}")
                continue
def find_formula_of_across_tables_count_or_exist_computed_column():

    prompt_text = pt.prompt_identify_candidate_table_for_count(
        config.target_column_name,
        config.target_table_name,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)

    #print(f"response: {response}")

    

    data = get_json_object(response)

    if data is None or "candidates" not in data:
        return

    for candidate in data["candidates"]:
        try:
            table_name = candidate["table_name"]


            found = find_formula_of_count_or_exist_computed_column_on_a_given_table(table_name)
        
            if already_found:
                    return True
            if found:
                return True

    
        except ContextTooLargeError as e:
            print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
            llm_layer._log_warning(f"CONTEXT_TOO_LARGE | count_or_exist table skipped | {e}")
            continue
        except Exception as e:
            print(f"[ERROR] count_or_exist table skipped: {e}")
            llm_layer._log_warning(f"CANDIDATE_ERROR | count_or_exist table skipped | {e}")
            continue
    return False


def remove_redundant_items(used_tables_and_columns_list):
    to_remove = set()

    # Compare each pair of items (X, Y)
    for i, (tables_x, cols_x) in enumerate(used_tables_and_columns_list):
        for j, (tables_y, cols_y) in enumerate(used_tables_and_columns_list):

            if i in to_remove:
                continue

            # Do not compare an item with itself
            if i == j:
                continue

            # Check conditions:
            # 1. tables_x is subset of tables_y
            # 2. tables_x is subset of cols_y
            if set(tables_x).issubset(tables_y) and set(cols_x).issubset(cols_y):
                to_remove.add(i)

    # Create a new filtered list
    return [
        item for idx, item in enumerate(used_tables_and_columns_list)
        if idx not in to_remove
    ]

def merge_by_same_tables_unordered(
    used_tables_and_columns_list: List[Tuple[List[str], List[str]]]
) -> List[Tuple[List[str], List[str]]]:
    """
    Merge entries where tables_x and tables_y contain the same tables,
    regardless of order. Column lists are merged while preserving the
    original appearance order and removing duplicates.
    """

    def dedupe_preserve_order(items):
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    buckets = OrderedDict()  # key = tuple(sorted tables)

    for tables, cols in used_tables_and_columns_list:
        key = tuple(sorted(tables))    # ORDER DOES NOT MATTER
        if key not in buckets:
            buckets[key] = {
                "tables": tables,      # preserve original version of tables for output
                "cols": []
            }
        buckets[key]["cols"].extend(cols)

    # Build final merged result
    merged = []
    for entry in buckets.values():
        merged_cols = dedupe_preserve_order(entry["cols"])
        merged.append((entry["tables"], merged_cols))

    return merged


def remove_duplicates(lst):
    seen = set()
    result = []

    for tables, columns in lst:
        # Convert inner lists to tuples (hashable)
        key = (tuple(tables), tuple(columns))

        if key not in seen:
            seen.add(key)
            result.append((tables, columns))  # keep original lists

    return result

def select_diverse_min_count(
    results: List[Tuple[Any, ...]],
    number_of_selected_rows: int
) -> List[Tuple[Any, ...]]:
    """
    Select a subset of tuples of length `number_of_selected_rows` from `results` such that:
      1) Tuples are as diverse as possible by target_value (tuple[0]).
         - First, pick the best (lowest count_value) one per distinct target_value.
      2) Among candidates, prioritize minimal count_value (tuple[-1]).
      3) If more rows are needed than distinct target_values, continue selecting the next
         minimal count_value across targets (fair k-way merge).
    
    Notes:
      - Uses tuple[0] as target_value and tuple[-1] as count_value.
      - If `number_of_selected_rows` exceeds the total available items, returns as many as possible.
      - Ties are broken by original input order to keep selection stable.
    
    Args:
        results: List of tuples; first item is target_value, last item is count_value.
        number_of_selected_rows: Desired number of tuples in the output subset.

    Returns:
        A list of tuples satisfying the constraints above (length <= number_of_selected_rows).
    """
    if number_of_selected_rows <= 0 or not results:
        return []

    # Index results to keep stable tie-breaking by original order
    indexed = [(i, t) for i, t in enumerate(results)]

    # Group by target_value (t[0])
    groups: Dict[Any, List[Tuple[float, int, Tuple[Any, ...]]]] = {}
    for idx, tup in indexed:
        target = tup[0]
        count_val = tup[-1]
        if target not in groups:
            groups[target] = []
        # Store as (count_value, original_index, tuple) for sorting within each group
        groups[target].append((count_val, idx, tup))

    # Sort each group's items by (count_value asc, original_index asc)
    for target in groups:
        groups[target].sort(key=lambda x: (x[0], x[1]))

    # Initial pass: pick the best (lowest count_value) one per distinct target_value
    # Collect one candidate from each group and sort them globally by (count, idx)
    first_choices = []
    for target, items in groups.items():
        if items:
            first_choices.append(items[0])

    first_choices.sort(key=lambda x: (x[0], x[1]))  # (count, idx, tuple)
    k = min(number_of_selected_rows, len(first_choices))

    selected: List[Tuple[Any, ...]] = []
    selected_count = 0

    # Take the best from as many distinct targets as needed or available
    taken_from_group = set()
    for count_val, idx, tup in first_choices[:k]:
        selected.append(tup)
        taken_from_group.add(tup[0])  # target_value
        selected_count += 1

    # Remove the taken top item from each used group so we can access the next ones
    for target in list(groups.keys()):
        if target in taken_from_group and groups[target]:
            groups[target].pop(0)  # consume the selected best item

    # If we still need more rows, do a k-way merge across remaining items in all groups
    remaining_needed = number_of_selected_rows - selected_count
    if remaining_needed > 0:
        # Build a min-heap of the next candidates from each group (if any)
        heap = []
        for target, items in groups.items():
            if items:
                # push first remaining candidate
                count_val, idx, tup = items[0]
                # entry: (count, idx, target, position_in_group)
                heapq.heappush(heap, (count_val, idx, target, 0, tup))

        while heap and remaining_needed > 0:
            count_val, idx, target, pos, tup = heapq.heappop(heap)
            selected.append(tup)
            remaining_needed -= 1

            # Push the next item from the same group (if exists)
            next_pos = pos + 1
            if next_pos < len(groups[target]):
                n_count, n_idx, n_tup = groups[target][next_pos]
                heapq.heappush(heap, (n_count, n_idx, target, next_pos, n_tup))

    return selected

reported_accuracy_sequence = 0


def _get_max_table_rows(table_names: list) -> int:
    """Return the max known row count across table_names via tables_info."""
    max_rows = 0
    for t in table_names:
        cols = tables_info.get(t)
        if cols and cols[0][6]:
            cnt = cols[0][6].get('total_number_of_values', 0)
            if cnt > max_rows:
                max_rows = cnt
    return max_rows


def find_formula_across_tables_based_on_potential_tables(used_tables: list):

    global already_found
    
    if len(used_tables) == 0:
        return 
    
    #print("\n")
    #print("\n")
    #print("\n")
    #print("\n")
    #print(f"**********************************************************************************")

    #print(f"used_tables: {used_tables}")

    #print(f"find_formula_across_tables_based_on_potential_tables({used_tables})")

    # 1 prepare sql query

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])
    
    result = find_join_route_for_multiple_target_tables_with_composites(
        dependencies=dependencies,
        source_table=config.target_table_name,
        target_tables=used_tables
    )

    if not result:
        #TODO Ask LLM to ptovide the join path
        #print("No join path found - Ask LLM to find the join path.")
        return False
    else:
        
        tables_in_path = result["tables_in_path"]
        #print(f"tables_in_path:{tables_in_path}")
        #print("Tables in path:", " → ".join(result["tables_in_path"]))
        #print("\nJOIN chain:\n", result["join_chain_sql"])

        if len(tables_in_path) > config.max_tables_in_join_path:
            #print(f"*******************************************************************************")
            #print(f"len(tables_in_path) = {len(tables_in_path)}")
            #print(f"*******************************************************************************")
            return

        join_chain_sql = result["join_chain_sql"]

        names_of_pk_columns_of_target_table_str = ""
        if len(names_of_pk_columns_of_target_table) > 0:
            for name_of_pk_column_of_target_table in names_of_pk_columns_of_target_table:
                names_of_pk_columns_of_target_table_str += f"{config.target_table_name}.{name_of_pk_column_of_target_table}, "
            names_of_pk_columns_of_target_table_str = names_of_pk_columns_of_target_table_str[:-2]
        else: 
            columns_names_str = get_filtered_columns_names_of_a_table(config.target_table_name, config.target_table_name)
            names_of_pk_columns_of_target_table_str = remove_substring(columns_names_str, f"`{config.target_table_name}`.`{config.target_column_name}`")

        n_pts = config.maximum_potential_data_points_in_target_table
        _large = _get_max_table_rows(used_tables) > _SELECTOR_LARGE_TABLE_THRESHOLD

        if not _large:
            used_tables_count_str = ""
            total_count_alias_str = ""
            all_count_alias = []
            for used_table in used_tables:

                columns = tables_info[used_table]
                names_of_distinct_columns = [item[1] for item in columns if item[2]]
                if len(names_of_distinct_columns) == 0:
                    names_of_distinct_columns = [item[1] for item in columns]

                names_of_pk_columns_of_used_table_str = ""
                for name_of_pk_column_of_used_table in names_of_distinct_columns:
                    names_of_pk_columns_of_used_table_str += f"`{used_table}`.`{name_of_pk_column_of_used_table}`, "
                names_of_pk_columns_of_used_table_str = names_of_pk_columns_of_used_table_str[:-2]
                count_alias = f"count_of_rows_in_{used_table}"
                used_tables_count_str += f"count(distinct CONCAT_WS('|', {names_of_pk_columns_of_used_table_str})) {count_alias}, "
                total_count_alias_str += f"{count_alias} + "
                all_count_alias.append(count_alias)

            used_tables_count_str = used_tables_count_str[:-2]
            total_count_alias_str = total_count_alias_str[:-2]

            sql_query = f"select `{config.target_table_name}`.`{config.target_column_name}`, {names_of_pk_columns_of_target_table_str}, {used_tables_count_str} from {join_chain_sql} "
            sql_query += f"where `{config.target_table_name}`.`{config.target_column_name}` is not null "
            sql_query += f"group by {names_of_pk_columns_of_target_table_str}, `{config.target_table_name}`.`{config.target_column_name}` "

            # Try first with all counts > 1
            # Then try with all counts > 0

            where_condition_str = "where "
            for count_alias in all_count_alias:
                where_condition_str += f"{count_alias} > 1 and "
            where_condition_str = where_condition_str[:-4]
            sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a {where_condition_str} order by {total_count_alias_str}"

            result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

        while True:
            if _large:
                db_layer._log_warning(
                    f"SELECTOR_LARGE_TABLE | skipping JOIN selector | using random sample"
                )
                _fb_sql = (
                    f"SELECT {names_of_pk_columns_of_target_table_str} "
                    f"FROM `{config.target_table_name}` "
                    f"WHERE `{config.target_table_name}`.`{config.target_column_name}` IS NOT NULL "
                    f"ORDER BY RAND() LIMIT {n_pts}"
                )
                _fb_result, _fb_headers, _, _ = execute_query_and_get_results_with_headers(_fb_sql)
                headers = _fb_headers if _fb_result else []
                headers_of_selected_data_points = headers
                selected_data_points = list(_fb_result) if _fb_result else []
            else:
                selected_resutls = select_diverse_min_count(result, n_pts)

                if len(selected_resutls) < n_pts:
                    where_condition_str = "where "
                    for count_alias in all_count_alias:
                        where_condition_str += f"{count_alias} > 0 and "
                    where_condition_str = where_condition_str[:-4]

                    sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a {where_condition_str} order by {total_count_alias_str}"

                    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

                    another_selected_resutls = select_diverse_min_count(result, n_pts - len(selected_resutls))

                    selected_resutls.extend(another_selected_resutls)

                    if len(selected_resutls) < n_pts:

                        sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a where {total_count_alias_str} > 0 order by {total_count_alias_str}"

                        result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

                        another_selected_resutls = select_diverse_min_count(result, n_pts - len(selected_resutls))

                        selected_resutls.extend(another_selected_resutls)

                headers = headers[1:-1]
                selected_resutls = [t[1:-1] for t in selected_resutls]

                headers_of_selected_data_points = headers[:len(used_tables)*-1]
                selected_data_points = [t[:len(used_tables)*-1] for t in selected_resutls]

            #print("data points of the target table are selected!")

            data_points_where_condition = ""

            if len(selected_data_points) > 0:
                data_points_where_condition = "where "

            if len(headers) == 1:
                data_points_where_condition += f" `{config.target_table_name}`.`{headers[0]}` in ("
                for selected_data_point in selected_data_points:
                    data_points_where_condition += f"'{selected_data_point[0]}', "
                data_points_where_condition = data_points_where_condition[:-2]
                data_points_where_condition = f")"
            else:
                for selected_data_point in selected_data_points:
                    data_points_where_condition += "("
                    i = 0
                    for header_of_selected_data_points in headers_of_selected_data_points:
                        data_points_where_condition += f"`{config.target_table_name}`.`{header_of_selected_data_points}` = '{selected_data_point[i]}' and "
                        i += 1
                    data_points_where_condition = data_points_where_condition[:-5]
                    data_points_where_condition += ") or "
                data_points_where_condition = data_points_where_condition[:-4]

            data_sharing_list = []

            #print("start preparing data points for other tables")

            #for used_table in used_tables:
            for used_table in tables_in_path:
                #print(f"start preparing data points for {used_table} tables")
                columns_names_str = get_filtered_columns_names_of_a_table(used_table, used_table)
                sql_query = f"select distinct {columns_names_str} from {join_chain_sql} {data_points_where_condition}"
                used_table_data_points, used_table_data_points_headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
                data_sharing_list.append((used_table, used_table_data_points_headers, used_table_data_points))
                #print(f"end preparing data points for {used_table} tables")

            #print("end preparing data points for other tables")

            data_for_sharing_with_LLM_str = ""

            other_used_tables_names_str = ""

            for data_sharing_table in data_sharing_list:
                data_for_sharing_with_LLM_str += f"Take the following data samples of `{data_sharing_table[0]}` table: "
                data_for_sharing_with_LLM_str += f"Columns names: {data_sharing_table[1]}, Sample rows: {data_sharing_table[2]}. "

                other_used_tables_names_str += f"{data_sharing_table[0]}, "


            other_used_tables_names_str = other_used_tables_names_str[:-2]

            prompt_text = pt.prompt_across_tables_formula_with_data(
                config.target_column_name,
                config.target_table_name,
                other_used_tables_names_str,
                used_tables,
                data_for_sharing_with_LLM_str,
                target_table_description,
                number_of_pks_in_target_table,
                names_of_pk_columns_of_target_table
            )

            if _fits_context(prompt_text) or n_pts <= 2:
                break
            n_pts = max(2, n_pts // 2)
            llm_layer._log_warning(f"S4_CONTEXT_REDUCE | across_tables | halved data points to {n_pts}")


        llm_layer.flush_chat_history("finding_formula_across_tables")


        try:
            response = llm_layer.get_response(prompt_text, "finding_formula_across_tables")
        except Exception as e:
            llm_layer._log_warning(f"BRANCH_ERROR | across_tables get_response failed | {e}")
            return

        data = get_json_object(response)

        #print(f"[find_formula_across_tables] response:\n{response}")
        #print(f"[find_formula_across_tables] data={data}")

        if data is None or "candidate_formulas" not in data:
            return

        for candidate_formula in data["candidate_formulas"]:
            try:
                llm_layer.flush_chat_history("finding_formula_across_tables")

                computation_sql_query = candidate_formula["computation_sql_query"]
                textual_formula_across = candidate_formula.get("textual_formula", "NaN")

                global reported_accuracy_sequence
                reported_accuracy_sequence += 1

                _, _, should_stop = process_llm_candidate(
                    textual_formula_across, computation_sql_query, column_logical_type,
                    "finding_formula_across_tables",
                    f"[across_tables], used_tables: {used_tables}",
                    reported_accuracy_sequence,
                    use_sample=True,
                    is_null_computed_value_allowed=False,
                )

                if should_stop:
                    already_found = config.early_stopping
                    return
            
                #print(f"************************************************************************************************")

            except ContextTooLargeError as e:
                print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
                llm_layer._log_warning(f"CONTEXT_TOO_LARGE | across_tables candidate skipped | {e}")
                continue
            except Exception as e:
                print(f"[ERROR] across_tables candidate skipped: {e}")
                llm_layer._log_warning(f"CANDIDATE_ERROR | across_tables candidate skipped | {e}")
                continue
    # 2 share data with LLM
    # 3 get accuracy


def find_formula_of_across_tables_using_candidate_formulas():

    prompt_text = pt.prompt_across_tables_candidate_formulas(
        config.target_column_name,
        config.target_table_name,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(response)

    #print("****************************************************************************")
    #print(f"response: {response}")
    #print("****************************************************************************")

    cf = data.get("candidate_formulas") if data else None

    #print(f"candidate_formulas type={type(cf).__name__}, value={cf}")

    if cf is None:
        #print("candidate_formulas is None — JSON parse failed or key missing")
        return

    if isinstance(cf, list) and len(cf) > 0 and isinstance(cf[0], dict):
        used_tables_and_columns_list = []
        for candidate_formula in cf:
            textual_formula = candidate_formula["textual_formula"]
            used_tables = candidate_formula["used_tables"]
            used_columns = candidate_formula["used_columns"]
            if config.target_table_name in used_tables:
                used_tables.remove(config.target_table_name)

            # Skip candidates that only reference the target table — a self-join
            # would not constitute a genuine across-tables formula.
            if not used_tables:
                continue

            target_column_as_used_column_str = f"{config.target_table_name}.{config.target_column_name}"
            if target_column_as_used_column_str in used_columns:
                used_columns.remove(target_column_as_used_column_str)

            used_tables_and_columns_list.append((used_tables, used_columns))

            #print(f"textual_formula: {textual_formula}")
            #print(f"used_tables: {used_tables}")
            #print(f"used_columns: {used_columns}")
        
        
        used_tables_and_columns_list = remove_duplicates(used_tables_and_columns_list)
        #print(f"used_tables_and_columns_list After deduplication: {used_tables_and_columns_list}")
        

        non_redundent_used_tables_and_columns_list = remove_redundant_items(used_tables_and_columns_list)
        #print(f"non_redundent_used_tables_and_columns_list: {non_redundent_used_tables_and_columns_list}")

        non_redundent_merged_used_tables_and_columns_list = merge_by_same_tables_unordered(non_redundent_used_tables_and_columns_list)
        #print(f"non_redundent_merged_used_tables_and_columns_list: {non_redundent_merged_used_tables_and_columns_list}")

        non_redundent_merged_used_tables_and_columns_list.sort(key=lambda item: len(item[0]))

        for item in non_redundent_merged_used_tables_and_columns_list:
            used_tables = item[0]
            #print(f"used_tables ({len(used_tables)}): {used_tables}")
        
        
        for item in non_redundent_merged_used_tables_and_columns_list:
            used_tables = item[0]
            find_formula_across_tables_based_on_potential_tables(used_tables)

            if already_found:
                return

            
    elif isinstance(cf, str) and "NaN" in cf:
        print("No formula found across tables")
    else:
        print(f"Unknown candidate_formulas structure: type={type(cf).__name__}, value={cf}")
        return


def find_formula_across_tables_based_on_potential_tables_hypered(used_tables: list):
    """Hypered variant of find_formula_across_tables_based_on_potential_tables.
    In addition to cross-table joined data, also shares standalone rows from
    the target table itself (one row per distinct target-column value).
    Used by find_formula_single_shot() for guided_search_mode=2."""

    global already_found

    if len(used_tables) == 0:
        return

    dependencies, headers = get_tables_dependencies_in_the_database()
    dependencies = [list(dep) for dep in dependencies]
    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    result = find_join_route_for_multiple_target_tables_with_composites(
        dependencies=dependencies,
        source_table=config.target_table_name,
        target_tables=used_tables
    )

    if not result:
        return False
    else:
        tables_in_path = result["tables_in_path"]

        if len(tables_in_path) > config.max_tables_in_join_path:
            return

        join_chain_sql = result["join_chain_sql"]

        names_of_pk_columns_of_target_table_str = ""
        if len(names_of_pk_columns_of_target_table) > 0:
            for name_of_pk_column_of_target_table in names_of_pk_columns_of_target_table:
                names_of_pk_columns_of_target_table_str += f"{config.target_table_name}.{name_of_pk_column_of_target_table}, "
            names_of_pk_columns_of_target_table_str = names_of_pk_columns_of_target_table_str[:-2]
        else:
            columns_names_str = get_filtered_columns_names_of_a_table(config.target_table_name, config.target_table_name)
            names_of_pk_columns_of_target_table_str = remove_substring(columns_names_str, f"`{config.target_table_name}`.`{config.target_column_name}`")

        n_pts = config.maximum_potential_data_points_in_target_table
        _large = _get_max_table_rows(used_tables) > _SELECTOR_LARGE_TABLE_THRESHOLD

        if not _large:
            used_tables_count_str = ""
            total_count_alias_str = ""
            all_count_alias = []
            for used_table in used_tables:
                columns = tables_info[used_table]
                names_of_distinct_columns = [item[1] for item in columns if item[2]]
                if len(names_of_distinct_columns) == 0:
                    names_of_distinct_columns = [item[1] for item in columns]

                names_of_pk_columns_of_used_table_str = ""
                for name_of_pk_column_of_used_table in names_of_distinct_columns:
                    names_of_pk_columns_of_used_table_str += f"`{used_table}`.`{name_of_pk_column_of_used_table}`, "
                names_of_pk_columns_of_used_table_str = names_of_pk_columns_of_used_table_str[:-2]
                count_alias = f"count_of_rows_in_{used_table}"
                used_tables_count_str += f"count(distinct CONCAT_WS('|', {names_of_pk_columns_of_used_table_str})) {count_alias}, "
                total_count_alias_str += f"{count_alias} + "
                all_count_alias.append(count_alias)

            used_tables_count_str = used_tables_count_str[:-2]
            total_count_alias_str = total_count_alias_str[:-2]

            sql_query = f"select `{config.target_table_name}`.`{config.target_column_name}`, {names_of_pk_columns_of_target_table_str}, {used_tables_count_str} from {join_chain_sql} "
            sql_query += f"where `{config.target_table_name}`.`{config.target_column_name}` is not null "
            sql_query += f"group by {names_of_pk_columns_of_target_table_str}, `{config.target_table_name}`.`{config.target_column_name}` "

            where_condition_str = "where "
            for count_alias in all_count_alias:
                where_condition_str += f"{count_alias} > 1 and "
            where_condition_str = where_condition_str[:-4]
            sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a {where_condition_str} order by {total_count_alias_str}"

            result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

        while True:
            if _large:
                db_layer._log_warning(
                    f"SELECTOR_LARGE_TABLE | skipping JOIN selector | using random sample"
                )
                _fb_sql = (
                    f"SELECT {names_of_pk_columns_of_target_table_str} "
                    f"FROM `{config.target_table_name}` "
                    f"WHERE `{config.target_table_name}`.`{config.target_column_name}` IS NOT NULL "
                    f"ORDER BY RAND() LIMIT {n_pts}"
                )
                _fb_result, _fb_headers, _, _ = execute_query_and_get_results_with_headers(_fb_sql)
                headers = _fb_headers if _fb_result else []
                headers_of_selected_data_points = headers
                selected_data_points = list(_fb_result) if _fb_result else []
            else:
                selected_resutls = select_diverse_min_count(result, n_pts)

                if len(selected_resutls) < n_pts:
                    where_condition_str = "where "
                    for count_alias in all_count_alias:
                        where_condition_str += f"{count_alias} > 0 and "
                    where_condition_str = where_condition_str[:-4]

                    sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a {where_condition_str} order by {total_count_alias_str}"

                    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

                    another_selected_resutls = select_diverse_min_count(result, n_pts - len(selected_resutls))

                    selected_resutls.extend(another_selected_resutls)

                    if len(selected_resutls) < n_pts:

                        sql_query_with_condition = f"select *, ({total_count_alias_str}) AS total_count_of_rows from ({sql_query})a where {total_count_alias_str} > 0 order by {total_count_alias_str}"

                        result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query_with_condition)

                        another_selected_resutls = select_diverse_min_count(result, n_pts - len(selected_resutls))

                        selected_resutls.extend(another_selected_resutls)

                headers = headers[1:-1]
                selected_resutls = [t[1:-1] for t in selected_resutls]

                headers_of_selected_data_points = headers[:len(used_tables)*-1]
                selected_data_points = [t[:len(used_tables)*-1] for t in selected_resutls]

            data_points_where_condition = ""

            if len(selected_data_points) > 0:
                data_points_where_condition = "where "

            if len(headers) == 1:
                data_points_where_condition += f" `{config.target_table_name}`.`{headers[0]}` in ("
                for selected_data_point in selected_data_points:
                    data_points_where_condition += f"'{selected_data_point[0]}', "
                data_points_where_condition = data_points_where_condition[:-2]
                data_points_where_condition = f")"
            else:
                for selected_data_point in selected_data_points:
                    data_points_where_condition += "("
                    i = 0
                    for header_of_selected_data_points in headers_of_selected_data_points:
                        data_points_where_condition += f"`{config.target_table_name}`.`{header_of_selected_data_points}` = '{selected_data_point[i]}' and "
                        i += 1
                    data_points_where_condition = data_points_where_condition[:-5]
                    data_points_where_condition += ") or "
                data_points_where_condition = data_points_where_condition[:-4]

            data_sharing_list = []

            for used_table in tables_in_path:
                columns_names_str = get_filtered_columns_names_of_a_table(used_table, used_table)
                sql_query = f"select distinct {columns_names_str} from {join_chain_sql} {data_points_where_condition}"
                used_table_data_points, used_table_data_points_headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
                data_sharing_list.append((used_table, used_table_data_points_headers, used_table_data_points))

            data_for_sharing_with_LLM_str = ""
            other_used_tables_names_str = ""

            for data_sharing_table in data_sharing_list:
                data_for_sharing_with_LLM_str += f"Take the following data samples of `{data_sharing_table[0]}` table: "
                data_for_sharing_with_LLM_str += f"Columns names: {data_sharing_table[1]}, Sample rows: {data_sharing_table[2]}. "
                other_used_tables_names_str += f"{data_sharing_table[0]}, "

            other_used_tables_names_str = other_used_tables_names_str[:-2]

            # Hypered addition: share standalone target-table rows (one per distinct
            # target-column value) in addition to the cross-table join data above.
            target_columns_names_str, target_rows = get_random_rows_for_single_table_computed_column(
                n_pts, config.target_column_name
            )
            if target_rows:
                data_for_sharing_with_LLM_str += (
                    f"Additionally, take the following standalone data samples of "
                    f"`{config.target_table_name}` table "
                    f"(independent rows, not via join): "
                    f"Columns names: {target_columns_names_str}, Sample rows: {target_rows}. "
                )

            prompt_text = pt.prompt_across_tables_formula_with_data(
                config.target_column_name,
                config.target_table_name,
                other_used_tables_names_str,
                used_tables,
                data_for_sharing_with_LLM_str,
                target_table_description,
                number_of_pks_in_target_table,
                names_of_pk_columns_of_target_table
            )

            if _fits_context(prompt_text) or n_pts <= 2:
                break
            n_pts = max(2, n_pts // 2)
            llm_layer._log_warning(f"S4_CONTEXT_REDUCE | single_shot | halved data points to {n_pts}")

        llm_layer.flush_chat_history("finding_formula_across_tables")

        try:
            response = llm_layer.get_response(prompt_text, "finding_formula_across_tables")
        except Exception as e:
            llm_layer._log_warning(f"BRANCH_ERROR | single_shot get_response failed | {e}")
            return

        data = get_json_object(response)

        if data is None or "candidate_formulas" not in data:
            return

        for candidate_formula in data["candidate_formulas"]:
            try:
                llm_layer.flush_chat_history("finding_formula_across_tables")

                computation_sql_query = candidate_formula["computation_sql_query"]
                textual_formula_across = candidate_formula.get("textual_formula", "NaN")

                global reported_accuracy_sequence
                reported_accuracy_sequence += 1

                _, _, should_stop = process_llm_candidate(
                    textual_formula_across, computation_sql_query, column_logical_type,
                    "finding_formula_across_tables",
                    f"[single_shot], used_tables: {used_tables}",
                    reported_accuracy_sequence,
                    use_sample=True,
                    is_null_computed_value_allowed=False,
                )

                if should_stop:
                    already_found = config.early_stopping
                    return

            except ContextTooLargeError as e:
                print(f"[CONTEXT_TOO_LARGE] skipping candidate: {e}")
                llm_layer._log_warning(f"CONTEXT_TOO_LARGE | single_shot candidate skipped | {e}")
                continue
            except Exception as e:
                print(f"[ERROR] single_shot candidate skipped: {e}")
                llm_layer._log_warning(f"CANDIDATE_ERROR | single_shot candidate skipped | {e}")
                continue


def find_formula_single_shot():
    """Single-shot variant of find_formula_of_across_tables_using_candidate_formulas.
    Used when guided_search_mode=2. Calls the hypered data-preparation variant
    that also shares standalone target-table rows alongside cross-table join data."""

    prompt_text = pt.prompt_across_tables_candidate_formulas(
        config.target_column_name,
        config.target_table_name,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(response)

    cf = data.get("candidate_formulas") if data else None

    if cf is None:
        return

    if isinstance(cf, list) and len(cf) > 0 and isinstance(cf[0], dict):
        used_tables_and_columns_list = []
        for candidate_formula in cf:
            textual_formula = candidate_formula["textual_formula"]
            used_tables = candidate_formula["used_tables"]
            used_columns = candidate_formula["used_columns"]
            if config.target_table_name in used_tables:
                used_tables.remove(config.target_table_name)

            if not used_tables:
                continue

            target_column_as_used_column_str = f"{config.target_table_name}.{config.target_column_name}"
            if target_column_as_used_column_str in used_columns:
                used_columns.remove(target_column_as_used_column_str)

            used_tables_and_columns_list.append((used_tables, used_columns))

        used_tables_and_columns_list = remove_duplicates(used_tables_and_columns_list)
        non_redundent_used_tables_and_columns_list = remove_redundant_items(used_tables_and_columns_list)
        non_redundent_merged_used_tables_and_columns_list = merge_by_same_tables_unordered(non_redundent_used_tables_and_columns_list)
        non_redundent_merged_used_tables_and_columns_list.sort(key=lambda item: len(item[0]))

        for item in non_redundent_merged_used_tables_and_columns_list:
            used_tables = item[0]
            find_formula_across_tables_based_on_potential_tables_hypered(used_tables)

            if already_found:
                return

    elif isinstance(cf, str) and "NaN" in cf:
        print("No formula found across tables")
    else:
        print(f"Unknown candidate_formulas structure: type={type(cf).__name__}, value={cf}")
        return


def find_formula_of_across_tables_computed_value_variant_3(found_in_single_table: bool):

    if config.guided_search_mode == 0:
        # Tree mode: is_count_or_exist() is a classification gate — only one
        # of the two across-table branches runs depending on its answer.
        count_or_exist = is_count_or_exist()
        if count_or_exist:
            found = find_formula_of_across_tables_count_or_exist_computed_column()
            if already_found:
                return True
            if found:
                return True
        else:
            find_formula_of_across_tables_using_candidate_formulas()
            if already_found:
                return True
    else:
        # Flat mode: both across-table branches always run.
        # already_found / early_stopping controls whether to stop between them.
        find_formula_of_across_tables_count_or_exist_computed_column()
        if already_found:
            return True

        find_formula_of_across_tables_using_candidate_formulas()
        if already_found:
            return True


def find_formula_of_across_tables_computed_value(found_in_single_table: bool):

    v3 = find_formula_of_across_tables_computed_value_variant_3(found_in_single_table)

    #return v1 or v2
    return v3

def get_computation_type():

    if config.guided_search_mode == 0:
        # Tree-based: LLM answers classification questions and the pipeline
        # commits to exactly one branch before any formula search starts.

        is_single_table = is_single_table_computed_value()

        if is_single_table:
            is_table_scope = is_single_table_table_scope_computed_value()
            if is_table_scope:
                table_scope_type = get_table_scope_type()
                if table_scope_type and "chaining" in str(table_scope_type).lower():
                    find_formula_of_a_single_table_scope_chaining_table_computed_value()
                else:
                    # "hierarchical" or anything else falls here
                    find_formula_of_a_single_table_scope_hierarchical_table_computed_value()
            else:
                find_formula_of_a_single_table_row_scope_computed_value()
        else:
            create_sample_table()
            find_formula_of_across_tables_computed_value(False)

    elif config.guided_search_mode == 2:
        # Single-shot mode: one hypered across-tables call that shares both
        # cross-table joined data and standalone target-table rows with the LLM.
        create_sample_table()
        find_formula_single_shot()

    else:
        # Flat mode (mode 1): all branches run sequentially.
        # already_found is set to config.early_stopping when a formula is found,
        # so if early_stopping=True the pipeline stops after the first success;
        # if early_stopping=False all branches always run.

        find_formula_of_a_single_table_scope_chaining_table_computed_value()
        if already_found:
            return

        find_formula_of_a_single_table_scope_hierarchical_table_computed_value()
        if already_found:
            return

        find_formula_of_a_single_table_row_scope_computed_value()
        if already_found:
            return

        create_sample_table()
        find_formula_of_across_tables_computed_value(True)

def get_table_scope_type():

    prompt_text = pt.prompt_common_formula_from_list(
        config.target_column_name,
        config.target_table_name,
        single_table_computed_value_formula_list,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)
    data = get_json_object(response)
    common_formula = data["common_formula"] if data and "common_formula" in data else response

    get_random_rows_for_single_table_computed_column(config.maximum_potential_data_points_in_target_table, config.target_column_name)

    prompt_text = pt.prompt_classify_table_type_chaining_or_hierarchical(
        config.target_column_name,
        config.target_table_name,
        common_formula,
        target_table_description
    )

    response = llm_layer.get_response(prompt_text, "any", False, False)
    data = get_json_object(response)
    single_table_type = data["table_type"] if data and "table_type" in data else response

    return single_table_type

def find_formula_of_a_single_table_row_scope_computed_value():

    global already_found
    
    
    found_in_single_table_row_scope = False

    n_pts = config.maximum_potential_data_points_in_target_table
    columns_names_str, result = get_random_rows_for_single_table_computed_column(n_pts, config.target_column_name)
    prompt_text = pt.prompt_row_scope_formula_discovery(
        config.target_column_name,
        config.target_table_name,
        columns_names_str,
        result
    )
    while not _fits_context(prompt_text) and n_pts > 2:
        n_pts = max(2, n_pts // 2)
        llm_layer._log_warning(f"S4_CONTEXT_REDUCE | row_scope | halved data points to {n_pts}")
        columns_names_str, result = get_random_rows_for_single_table_computed_column(n_pts, config.target_column_name)
        prompt_text = pt.prompt_row_scope_formula_discovery(
            config.target_column_name,
            config.target_table_name,
            columns_names_str,
            result
        )

    row_scope_table_info = llm_layer.get_response(prompt_text, "any", False, False)

    data = get_json_object(row_scope_table_info)

    if data is None:
        return found_in_single_table_row_scope

    for _, block in data.items():
      try:
        # formula string
        formula_to_compute_the_computed_column = block["formula"]

        columns_list = block["columns"]

        columns_to_compute_the_computed_column_str = ""

        for c in columns_list:
            columns_to_compute_the_computed_column_str += f"{c}, "
        columns_to_compute_the_computed_column_str = columns_to_compute_the_computed_column_str[:-2]

        prompt_text = pt.prompt_row_scope_sql_generation(
            config.target_column_name,
            config.target_table_name,
            formula_to_compute_the_computed_column,
            columns_to_compute_the_computed_column_str,
            columns_names_str,
            result,
            target_table_description,
            number_of_pks_in_target_table,
            names_of_pk_columns_of_target_table
        )

        llm_layer.flush_chat_history("single_table_row_scope")

        response = llm_layer.get_response(prompt_text, "single_table_row_scope")

        match = re.search(r"```sql(.*?)```", response, re.DOTALL)
        computation_sql_query = match.group(1).strip() if match else None

        global reported_accuracy_sequence
        reported_accuracy_sequence += 1

        best_accuracy, _, should_stop = process_llm_candidate(
            formula_to_compute_the_computed_column, computation_sql_query, column_logical_type,
            "single_table_row_scope",
            "[row_scope]",
            reported_accuracy_sequence,
        )

        if best_accuracy >= config.cleaning_threshold:
            found_in_single_table_row_scope = True

        if should_stop:
            already_found = config.early_stopping
            return True

        continue
      except ContextTooLargeError as e:
        print(f"[CONTEXT_TOO_LARGE] skipping row_scope block: {e}")
        llm_layer._log_warning(f"CONTEXT_TOO_LARGE | row_scope block skipped | {e}")
        continue
      except Exception as e:
        print(f"[ERROR] row_scope block skipped: {e}")
        llm_layer._log_warning(f"CANDIDATE_ERROR | row_scope block skipped | {e}")
        continue
    return found_in_single_table_row_scope

def get_random_rows_for_single_table_computed_column(max_number_of_sent_random_rows: int, distinct_column_name: str = None):
    # Retrieve column list as a comma-separated string with proper backticks
    columns_names_str = get_filtered_columns_names_of_a_table(config.target_table_name)

    # Validate or escape the distinct column name if provided
    # (assuming `distinct_column_name` is a raw column identifier without backticks)
    if distinct_column_name is not None:
        # Basic defensive check; you may want to restrict to known columns
        # to avoid SQL injection via identifiers.
        if distinct_column_name.strip() == "":
            raise ValueError("distinct_column_name must be a non-empty string when provided.")
        distinct_col_quoted = f"`{distinct_column_name}`"

        # Build query ensuring one random row per distinct value of the chosen column
        sql_query = f"""
        SELECT {columns_names_str}
        FROM (
            SELECT s.*,
                   ROW_NUMBER() OVER (PARTITION BY {distinct_col_quoted} ORDER BY RAND()) AS rn
            FROM `{config.target_table_name}` s
            where `{distinct_column_name}` is not null
        ) AS t
        WHERE rn = 1
        ORDER BY RAND()
        LIMIT {max_number_of_sent_random_rows}
        """
    else:
        # Pure random rows across the whole table
        sql_query = f"""
        SELECT {columns_names_str}
        FROM `{config.target_table_name}` s
        ORDER BY RAND()
        LIMIT {max_number_of_sent_random_rows}
        """

    result, _, _, _ = execute_query_and_get_results_with_headers(sql_query)
    
    return columns_names_str, result


single_table_computed_value_formula_list = []
def is_single_table_table_scope_computed_value():

    global single_table_computed_value_formula_list
    
    single_table_computed_value_type_list = []

    single_table_computed_value_formula_list = []

    max_number_of_tries = 10

    single_table_computed_value_type_final = "table_scope or row-scope"
    
    n_pts = config.maximum_potential_data_points_in_target_table
    columns_names_str, result = get_random_rows_for_single_table_computed_column(n_pts, config.target_column_name)
    _size_check_prompt = pt.prompt_single_table_formula_discovery(config.target_column_name, config.target_table_name, columns_names_str, result, target_table_description)
    while not _fits_context(_size_check_prompt) and n_pts > 2:
        n_pts = max(2, n_pts // 2)
        llm_layer._log_warning(f"S4_CONTEXT_REDUCE | single_table_scope | halved data points to {n_pts}")
        columns_names_str, result = get_random_rows_for_single_table_computed_column(n_pts, config.target_column_name)
        _size_check_prompt = pt.prompt_single_table_formula_discovery(config.target_column_name, config.target_table_name, columns_names_str, result, target_table_description)

    i = 0
    counts = Counter()
    while i < max_number_of_tries:

        prompt_text = pt.prompt_single_table_formula_discovery(config.target_column_name, config.target_table_name, columns_names_str, result, target_table_description)

        response = llm_layer.get_response(prompt_text, "any", False, False)
        data = get_json_object(response)
        single_table_computed_value_formula = data["formula"] if data and "formula" in data else response

        if single_table_computed_value_formula is None or "None" in str(single_table_computed_value_formula):
            i += 1

            single_table_computed_value_type_list.append("None")

            counts = Counter(single_table_computed_value_type_list)

            none_counts = counts.get('None', 0)

            if none_counts > max_number_of_tries/2:
                return False


            continue

        prompt_text = pt.prompt_table_scope_type_check(config.target_column_name, config.target_table_name, single_table_computed_value_formula, columns_names_str, result, target_table_description)

        response = llm_layer.get_response(prompt_text, "any", False, False)
        data = get_json_object(response)
        single_table_computed_value_type_str = data["scope_type"] if data and "scope_type" in data else response

        single_table_computed_value_formula_list.append(single_table_computed_value_formula)
        single_table_computed_value_type_list.append(single_table_computed_value_type_str)

        counts = Counter(single_table_computed_value_type_list)

        table_wise_counts = counts.get('table-scope', 0)
        none_counts = counts.get('None', 0)

        if table_wise_counts > max_number_of_tries/2:
            return True

        if none_counts > max_number_of_tries/2:
            return False

        i += 1
    
    print(f"single_table_computed_value_type_list: {single_table_computed_value_type_list}")
    print(f"single_table_computed_value_type_final: {single_table_computed_value_type_final}")

    table_wise_counts = counts.get('table-scope', 0)
    none_counts = counts.get('None', 0)

    if table_wise_counts > none_counts:
        return True
    return False

def is_single_table_computed_value():
    
    is_single_table_computed_value_list = []

    max_number_of_tries = 3

    i = 0

    is_single_table_computed_value_final = False

    while i < max_number_of_tries:
        prompt_text = pt.prompt_is_single_table_computed_value_smartly(config.target_column_name, config.target_table_name, target_table_description)

        response = llm_layer.get_response(prompt_text, "any", False, False)
        data = get_json_object(response)
        if data and "is_computed" in data:
            is_single_table_computed_value_str = data["is_computed"]
        else:
            is_single_table_computed_value_str = response

        is_single_table_computed_value = False
        if "yes" in is_single_table_computed_value_str.lower():
            is_single_table_computed_value = True

        is_single_table_computed_value_list.append(is_single_table_computed_value)

        count_true = sum(is_single_table_computed_value_list)

        if count_true > max_number_of_tries/2:
            is_single_table_computed_value_final = True
            break
        
        count_false = len(is_single_table_computed_value_list) - count_true

        if count_false > max_number_of_tries/2:
            is_single_table_computed_value_final = False
            break

        i += 1
    
    
    print(f"is_single_table_computed_value_list: {is_single_table_computed_value_list}")
    print(f"is_single_table_computed_value_final: {is_single_table_computed_value_final}")

    return is_single_table_computed_value_final

   

def try_a_formula(try_number: int): # "new_formula", "validation_sql_query", accuracy, is_with_diagnoses

    get_computation_type()

    return

target_column_distinct_values_str = ""
target_table_sample_rows_headers = ""
target_table_sample_rows = ""


initial_prompt_str = ""
target_table_description = ""
def run():

    global column_logical_type
    global initial_prompt_str
    global target_table_description
    global names_of_pk_columns_of_target_table

    execution_start_timestamp = time.perf_counter() * 1000

    """Run step 5 (placeholder)"""
    logging.info("Running Step 5...")


    llm_layer.flush_chat_history()

    db_layer.db_export_schema()

    output_file = config.work_space + f"/output_{config.target_database_name}_{config.target_table_name}_{config.target_column_name}.txt"

    config.strategy = 4
    initial_prompt_str = pt.get_initial_prompt_str(4)

    target_table_description = load_table_description(3)

    file_utils.delete_file_if_exists(output_file)
    file_utils.delete_file_if_exists(db_layer.sql_log_file)

    print (f"{config.target_table_name}, {config.target_column_name}")

    if is_computed_column(target_table_description, config.strategy):

        print("yes")

        report.is_computed = True
        
        columns = tables_info[config.target_table_name]

        column_info = [col for col in columns if col[1].strip() == config.target_column_name.strip()][0]

        _, _, _, _, _, column_logical_type, _ = column_info

        names_of_pk_columns = [item[1] for item in columns if item[2]]
        names_of_pk_columns_of_target_table = names_of_pk_columns

        for try_number in range(config.different_formula_max_tries):

            try_a_formula(try_number+1)

            break

    else:
        report.is_computed = False

        print("no")

        
        report_accuracy(-1, "not_computed", "", "", 1)

    from src.core.report_util import reported_accuracy_list
    if not reported_accuracy_list:
        report_accuracy(-2, "no_formula_found", "", "", 1)

    execution_end_timestamp = time.perf_counter() * 1000
    total_execution_time = execution_end_timestamp - execution_start_timestamp

    write_metrics_to_csv(total_execution_time)