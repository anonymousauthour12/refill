
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from math import ceil
import re

from src.core import connect_to_db, disconnect_from_db, execute_query_and_get_results_with_headers, execute_query, file_utils, llm_layer

from src.core import db_layer
from src.core.config import config

import subprocess

from src.core.report_util import report

#from src.core.data_point_selector import select_diverse_points
#from src.core.data_point_selector2 import select_diverse_points
from src.core.data_point_selector3 import select_diverse_points

from src.core.db_layer import cursor, flush_cursor, validate_a_non_guarenteed_query_and_rewrite_if_needed

# Configuration

databases_dir = "databases"

def prepare_database():
    
    sql_query = f"DROP DATABASE IF EXISTS {config.target_database_name}"

    connect_to_db("mysql")
    
    execute_query(sql_query)
    
    disconnect_from_db()
    
    sql_query = f"CREATE DATABASE IF NOT EXISTS {config.target_database_name}"

    connect_to_db("mysql")
    
    execute_query(sql_query)
    
    disconnect_from_db()

    mysql_user = config.database_user
    mysql_password = config.database_pw
    dump_file = f"{databases_dir}/{config.target_database_name}.sql"

    # Build the command
    command = f"mysql -u {mysql_user} -p{mysql_password} {config.target_database_name} < {dump_file}"

    try:
        # Execute the command
        result = subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print("Error occurred while importing the database:", e)

    tables_names = get_tables_names_of_a_database()  
    connect_to_db(config.target_database_name)
    for table_name in tables_names:
        execute_query(f"ANALYZE TABLE `{table_name}`;")    
    disconnect_from_db()    


def get_table_average_row_size(table_name: str):
    # Optional minimal sanitization; prefer parameterized queries if available in your helper
    safe_table = table_name.replace("`", "").replace("'", "").strip()

    avg_row_size_query = f"""
    SELECT
        IFNULL(SUM(col_bytes), 0)
        AS estimated_row_bytes
    FROM (
    SELECT
        CASE
        /* ======= Numeric ======= */
        WHEN DATA_TYPE IN ('tinyint','boolean','bool')                 THEN 1
        WHEN DATA_TYPE = 'smallint'                                    THEN 2
        WHEN DATA_TYPE = 'mediumint'                                   THEN 3
        WHEN DATA_TYPE IN ('int','integer')                            THEN 4
        WHEN DATA_TYPE = 'bigint'                                      THEN 8
        WHEN DATA_TYPE = 'float'                                       THEN 4
        WHEN DATA_TYPE IN ('double','real','double precision')         THEN 8
        WHEN DATA_TYPE IN ('decimal','numeric')                        THEN
            (FLOOR( (COALESCE(NUMERIC_PRECISION,0) - COALESCE(NUMERIC_SCALE,0)) / 9 ) * 4)
            + CASE MOD( (COALESCE(NUMERIC_PRECISION,0) - COALESCE(NUMERIC_SCALE,0)), 9 )
                WHEN 0 THEN 0 WHEN 1 THEN 1 WHEN 2 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 2
                WHEN 5 THEN 3 WHEN 6 THEN 3 WHEN 7 THEN 4 WHEN 8 THEN 4
            END
            + (FLOOR( COALESCE(NUMERIC_SCALE,0) / 9 ) * 4)
            + CASE MOD( COALESCE(NUMERIC_SCALE,0), 9 )
                WHEN 0 THEN 0 WHEN 1 THEN 1 WHEN 2 THEN 1 WHEN 3 THEN 2 WHEN 4 THEN 2
                WHEN 5 THEN 3 WHEN 6 THEN 3 WHEN 7 THEN 4 WHEN 8 THEN 4
            END
        WHEN DATA_TYPE = 'bit'                                         THEN CEIL(COALESCE(NUMERIC_PRECISION,1)/8)

        /* ======= Date/Time (with fractional seconds) ======= */
        WHEN DATA_TYPE = 'year'                                        THEN 1
        WHEN DATA_TYPE = 'date'                                        THEN 3
        WHEN DATA_TYPE = 'time'                                        THEN 3 + (
            CASE
            WHEN COALESCE(DATETIME_PRECISION,0) IN (0)    THEN 0
            WHEN COALESCE(DATETIME_PRECISION,0) IN (1,2)  THEN 1
            WHEN COALESCE(DATETIME_PRECISION,0) IN (3,4)  THEN 2
            WHEN COALESCE(DATETIME_PRECISION,0) IN (5,6)  THEN 3
            ELSE 0
            END)
        WHEN DATA_TYPE = 'datetime'                                    THEN 5 + (
            CASE
            WHEN COALESCE(DATETIME_PRECISION,0) IN (0)    THEN 0
            WHEN COALESCE(DATETIME_PRECISION,0) IN (1,2)  THEN 1
            WHEN COALESCE(DATETIME_PRECISION,0) IN (3,4)  THEN 2
            WHEN COALESCE(DATETIME_PRECISION,0) IN (5,6)  THEN 3
            ELSE 0
            END)
        WHEN DATA_TYPE = 'timestamp'                                   THEN 4 + (
            CASE
            WHEN COALESCE(DATETIME_PRECISION,0) IN (0)    THEN 0
            WHEN COALESCE(DATETIME_PRECISION,0) IN (1,2)  THEN 1
            WHEN COALESCE(DATETIME_PRECISION,0) IN (3,4)  THEN 2
            WHEN COALESCE(DATETIME_PRECISION,0) IN (5,6)  THEN 3
            ELSE 0
            END)

        /* ======= ENUM / SET (best-effort) ======= */
        WHEN DATA_TYPE = 'enum'                                        THEN IF(
            ((LENGTH(SUBSTRING_INDEX(SUBSTRING_INDEX(COLUMN_TYPE, '(', -1), ')', 1))
            - LENGTH(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(COLUMN_TYPE, '(', -1), ')', 1), ',', '')))
            + 1) <= 255, 1, 2)
        WHEN DATA_TYPE = 'set'                                         THEN CEIL(
            ((LENGTH(SUBSTRING_INDEX(SUBSTRING_INDEX(COLUMN_TYPE, '(', -1), ')', 1))
            - LENGTH(REPLACE(SUBSTRING_INDEX(SUBSTRING_INDEX(COLUMN_TYPE, '(', -1), ')', 1), ',', '')))
            + 1) / 8)

        /* ======= Excluded variable/internal types ======= */
        WHEN DATA_TYPE IN ('tinytext','text','mediumtext','longtext',
                            'tinyblob','blob','mediumblob','longblob',
                            'json',
                            'geometry','point','linestring','polygon',
                            'multipoint','multilinestring','multipolygon','geometrycollection')
            THEN 0

        /* Fallback */
        ELSE 0
        END AS col_bytes
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
        AND TABLE_NAME   = '{safe_table}'
    ) AS per_column;
    """

    result = execute_query_and_get_results_with_headers(avg_row_size_query)

    row_size_without_strings = 0

    # result should be: [(estimated_row_bytes,)]
    if result and len(result) > 0 and result[0][0] is not None:
        row_size_without_strings = int(result[0][0][0])
        
    
    row_strings_size = 0

    table_strings_columns_query = f"""
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = '{safe_table}'
    AND TABLE_SCHEMA = '{config.target_database_name}'
    AND DATA_TYPE IN ('char', 'varchar', 'binary', 'varbinary');
    """

    result, _, _, _ = execute_query_and_get_results_with_headers(table_strings_columns_query)
    
    for r in result:
        
        string_column_name = '`' + r[0] + '`'

        sql_query = f"SELECT AVG(LENGTH({string_column_name})) AS avg_length FROM {safe_table}"

        string_column_actual_avg_size, _, _, _ = execute_query_and_get_results_with_headers(sql_query)


        if len(string_column_actual_avg_size) > 0:
            if string_column_actual_avg_size[0][0] is not None:
                row_strings_size += string_column_actual_avg_size[0][0]


    row_size = row_size_without_strings + row_strings_size

    return row_size 

def get_sum_of_average_row_size_of_all_parents_of_parent_tables(dependencies: list, child_table: str, excluded_parent: str):
    total_avg_row_size = 0
    for d in dependencies:
        parent_table = d[0]
        if parent_table == excluded_parent:
            continue
        child_table_name = d[1]
        join_condition = d[2]
        if child_table_name == child_table:
            total_avg_row_size += get_table_average_row_size(parent_table)
    return total_avg_row_size

def get_number_of_parent_tables(dependencies: list, child_table: str, excluded_parent: str):
    count = 0
    for d in dependencies:
        parent_table = d[0]
        child_table_name = d[1]
        join_condition = d[2]
        if child_table_name == child_table and parent_table != excluded_parent:
            count += 1
    return count

def get_children_tables_cardinality(dependencies: list, table_name_of_target_column: str, target_column_name: str, selected_potential_data_points_str: str):
    
    distinct_count_queries = []
    has_children = False

    pk_columns_names = get_pk_columns_names_of_a_table(table_name_of_target_column)
    pk_columns_str = ""
    for pk_col in pk_columns_names:
        pk_columns_str += f"parent_table.{pk_col}, "
    pk_columns_str = pk_columns_str[:-2]

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if parent_table == table_name_of_target_column:
            has_children = True
            join_condition_str = ""
            for k, v in join_condition.items():
                join_condition_str += f"child_table.{k} = parent_table.{v} and "
            join_condition_str = join_condition_str[:-5] + " "
            
            sql_query = f"select {pk_columns_str}, parent_table.{target_column_name} target_column, "
            sql_query += f"'{child_table}' child_table, "
            sql_query += f"count(*) number_of_matching_children_rows, "
            sql_query += f"{get_table_average_row_size(child_table)} average_child_row_size, "
            sql_query += f"{get_number_of_parent_tables(dependencies, child_table, table_name_of_target_column)} AS number_of_other_parents_of_the_child_table, "
            sql_query += f"{get_sum_of_average_row_size_of_all_parents_of_parent_tables(dependencies, child_table, table_name_of_target_column)} AS sum_of_other_parents_avgerage_row_size_of_the_child_table "

            sql_query += f" from {selected_potential_data_points_str} parent_table inner join {child_table} child_table on "
            sql_query += join_condition_str
            sql_query += f" where parent_table.{target_column_name} is not null "
            sql_query += f" group by {pk_columns_str}, parent_table.{target_column_name} "
            distinct_count_queries.append(sql_query)

    pk_columns_str = pk_columns_str.replace("parent_table.", "")
    
    if has_children == False:
        final_query_str = f"select {pk_columns_str}, {target_column_name} target_column, "
        final_query_str += "0 number_of_matching_children_tables, "
        final_query_str += "0 number_of_matching_rows_in_all_children, "
        final_query_str += "0 estimated_size_of_all_children_rows, "
        final_query_str += "0 total_number_of_other_parents_of_all_children_tables, "
        final_query_str += "0 maximum_estimated_size_of_all_children_rows_including_their_other_parents "
        final_query_str += f"from {table_name_of_target_column}  "
        return final_query_str
    
    union_of_all_queries_str = " UNION ALL ".join(distinct_count_queries)
    final_query_str = f"select {pk_columns_str}, target_column, "
    final_query_str += "count(*) number_of_matching_children_tables, "
    final_query_str += "sum(number_of_matching_children_rows) number_of_matching_rows_in_all_children, "
    final_query_str += "sum(number_of_matching_children_rows * average_child_row_size) estimated_size_of_all_children_rows, "
    final_query_str += "sum(number_of_other_parents_of_the_child_table) total_number_of_other_parents_of_all_children_tables, "
    final_query_str += "sum(number_of_matching_children_rows * (average_child_row_size + sum_of_other_parents_avgerage_row_size_of_the_child_table)) maximum_estimated_size_of_all_children_rows_including_their_other_parents "
    final_query_str += f"from ( {union_of_all_queries_str} ) a "
    final_query_str += f"group by {pk_columns_str}, target_column "
    


    return final_query_str

def get_sibling_tables_cardinality(dependencies: list, table_name_of_target_column: str, target_column_name: str, selected_potential_data_points_str: str):
    
    distinct_count_queries = []
    has_siblings = False
    parent_tables_set = set()

    pk_columns_names = get_pk_columns_names_of_a_table(table_name_of_target_column)
    pk_columns_str = ""
    for pk_col in pk_columns_names:
        pk_columns_str += f"target_table.{pk_col}, "
    pk_columns_str = pk_columns_str[:-2]

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if child_table == table_name_of_target_column:
            parent_pk_columns_str = ""
            join_condition_str = ""
            for k, v in join_condition.items():
                parent_pk_columns_str += f"parent_table.{v}, "
                join_condition_str += f"target_table.{k} = parent_table.{v} and "
            parent_pk_columns_str = parent_pk_columns_str[:-2] + " "
            join_condition_str = join_condition_str[:-5] + " "
            
            for d in dependencies:
                sibling_table = d[1]
                sibling_join_condition = d[2]

                if parent_table == d[0] and table_name_of_target_column != sibling_table:
                    has_siblings = True

                    another_join_condition_str = ""
                    for k, v in sibling_join_condition.items():
                        another_join_condition_str += f"parent_table.{v} = sibling_table.{k} and "
                    another_join_condition_str = another_join_condition_str[:-5] + " "

                    parent_tables_set.add(parent_table)

                    sql_query = f"select {pk_columns_str}, target_table.{target_column_name} target_column, "
                    sql_query += f"'{parent_table}' parent_table, "
                    sql_query += f"'{sibling_table}' sibling_table, "
                    sql_query += "count(*) number_of_rows_of_sibling_table, "
                    sql_query += f"{get_table_average_row_size(sibling_table)} AS average_row_size_of_the_sibling_table "

                    sql_query += f" from {selected_potential_data_points_str} target_table inner join {parent_table} parent_table on "
                    sql_query += join_condition_str
                    sql_query += f" inner join {sibling_table} sibling_table on "
                    sql_query += another_join_condition_str
                    
                    sql_query += f" where target_table.{target_column_name} is not null "
                    sql_query += f" group by {pk_columns_str}, target_table.{target_column_name} "
                    distinct_count_queries.append(sql_query)
                                        
    if has_siblings == False:
        final_query_str = f"select {pk_columns_str}, {target_column_name} target_column, "
        final_query_str += "0 number_of_sibling_tables, "
        final_query_str += "0 number_of_rows_of_all_sibling_tables, "
        final_query_str += f"0 sum_of_parent_tables_rows_sizes, "
        final_query_str += "0 estimated_size_of_all_sibling_rows "
        final_query_str += f"from {table_name_of_target_column} target_table "
        final_query_str += f"group by {pk_columns_str}, {target_column_name} "


        return final_query_str
    
    sum_of_parent_tables_rows_sizes = 0
    for parent_table in parent_tables_set:
        sum_of_parent_tables_rows_sizes += get_table_average_row_size(parent_table)

    union_of_all_queries_str = " UNION ALL ".join(distinct_count_queries)
    
    pk_columns_str = pk_columns_str.replace("target_table.", "")

    final_query_str = f"select {pk_columns_str}, target_column, "
    final_query_str += "count(*) number_of_sibling_tables, "
    final_query_str += "sum(number_of_rows_of_sibling_table) number_of_rows_of_all_sibling_tables, "
    final_query_str += f"{sum_of_parent_tables_rows_sizes} sum_of_parent_tables_rows_sizes, "
    final_query_str += "sum(number_of_rows_of_sibling_table * average_row_size_of_the_sibling_table) estimated_size_of_all_sibling_rows "
    final_query_str += f"from ({union_of_all_queries_str}) a "
    final_query_str += f"group by {pk_columns_str}, target_column "
    return final_query_str



def prepare_target_table_selected_data_points_condition_str(pk_columns_str, selected):
    
    condition_str = ""
    for row in selected:
        condition_str += " ( "
        for i in range(len(row)-2):
            pk_col_value = row[i]
            if isinstance(pk_col_value, str) or isinstance(pk_col_value, date) or isinstance(pk_col_value, datetime) :
                if isinstance(pk_col_value, str):
                    pk_col_value = pk_col_value.replace("'", "''")  # escape single quotes
                if "," in pk_columns_str:
                    condition_str += f"{pk_columns_str.split(', ')[i]} = '{pk_col_value}' and "
                else:
                    condition_str += f"{pk_columns_str} = '{pk_col_value}' and "
            else:
                if "," in pk_columns_str:
                    condition_str += f"{pk_columns_str.split(', ')[i]} = {pk_col_value} and "
                else:
                    condition_str += f"{pk_columns_str} = {pk_col_value} and "
        condition_str = condition_str[:-5]  # remove last ' and '
        condition_str += " ) or "
    condition_str = condition_str[:-4]  # remove last ' or '


    return condition_str


data_sharing_table = ""
data_sharing_max_limit_in_bytes = 0

def select_data_for_sharing(is_only_children: bool = False):
    
    sql_query = f"SELECT {pk_columns_names_of_target_table_str}"
    sql_query += ", number_of_matching_children_tables "
    sql_query += ", number_of_sibling_tables "
    sql_query += ", target_column, (maximum_estimated_size_of_all_children_rows_including_their_other_parents + sum_of_parent_tables_rows_sizes "
    if is_only_children == False:
        sql_query += " + estimated_size_of_all_sibling_rows "
    sql_query += f") estimated_size "
    
    '''sql_query += """(CASE 
                    WHEN IFNULL(number_of_matching_children_tables, 0) > 0 AND IFNULL(number_of_sibling_tables, 0) > 0 THEN 3
                    WHEN IFNULL(number_of_matching_children_tables, 0) > 0 AND IFNULL(number_of_sibling_tables, 0) = 0 THEN 2
                    WHEN IFNULL(number_of_sibling_tables, 0) > 0 AND IFNULL(number_of_matching_children_tables, 0) = 0 THEN 1
                    ELSE 0 END 
                ) factor """'''
    
    sql_query += ", (10 * number_of_matching_children_tables) + number_of_sibling_tables factor "
    
    
    sql_query += f"FROM ({data_sharing_table}) a "
    sql_query += "where "
    sql_query += f"maximum_estimated_size_of_all_children_rows_including_their_other_parents + sum_of_parent_tables_rows_sizes "
    if is_only_children == False:
        sql_query += f" + estimated_size_of_all_sibling_rows "
    sql_query += f" < {data_sharing_max_limit_in_bytes} "
    sql_query += "order by "
    sql_query += """
                (CASE 
                    WHEN IFNULL(number_of_matching_children_tables, 0) > 0 AND IFNULL(number_of_sibling_tables, 0) > 0 THEN 3
                    WHEN IFNULL(number_of_matching_children_tables, 0) > 0 AND IFNULL(number_of_sibling_tables, 0) = 0 THEN 2
                    WHEN IFNULL(number_of_sibling_tables, 0) > 0 AND IFNULL(number_of_matching_children_tables, 0) = 0 THEN 1
                    ELSE 0 END
                ) desc,
    """

    sql_query += "(number_of_matching_children_tables  "
    if is_only_children == False:
        sql_query += " + number_of_sibling_tables "
    sql_query += ") desc, "

    sql_query += "(number_of_matching_rows_in_all_children "
    if is_only_children == False:
        sql_query += " + number_of_rows_of_all_sibling_tables "
    sql_query += ") desc, "

    sql_query += "number_of_matching_children_tables desc, "
    if is_only_children == False:
        sql_query += "number_of_sibling_tables desc, "
    
    sql_query += "number_of_matching_rows_in_all_children desc "
    
    if is_only_children == False:
        sql_query += ", number_of_rows_of_all_sibling_tables desc"
    


    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)


    
    
    selected = []

    headers = headers[:-1]

    
    result = [row[:-1] for row in result]

    
    
    

    selected = select_diverse_points(result, data_sharing_max_limit_in_bytes, X=config.number_of_data_points_from_target_table_to_send, headers=headers)
    
    #if len(selected) == 0:
    #    return []
    
    

    
    return selected
    
    
    experiment_results_sql_file = config.work_space + f"/results_sql.sql"
    file_utils.create_file_if_not_exists(experiment_results_sql_file)
    file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
    file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
    file_utils.append_to_file(experiment_results_sql_file, "######################################################################\n")
    file_utils.append_to_file(experiment_results_sql_file, f"{sql_query};\n")
    
    
    if len(result) == 1:
        print(f"Selected row for data sharing: {result[0]}")
        file_utils.append_to_file(experiment_results_sql_file, f"#Selected row for data sharing: {result[0]};\n")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################\n")
        exit()
        return True, result[0]
    else:
        print("XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX No row found for data sharing XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.")
        file_utils.append_to_file(experiment_results_sql_file, "#XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX No row found for data sharing XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################")
        file_utils.append_to_file(experiment_results_sql_file, "######################################################################\n")
        exit()
        return False, None  
    

target_table_query = []
children_tables_queries = []
another_parents_of_children_tables_queries = []
parent_tables_queries = []
sibling_tables_queries = []

def get_filtered_columns_names_of_a_table(table_name: str, table_alias: str = ""):
    sql_query = f"""
    SELECT COLUMN_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{config.target_database_name}'
    AND TABLE_NAME = '{table_name}'
    AND DATA_TYPE NOT IN (
    'tinytext','text','mediumtext','longtext',
    'tinyblob','blob','mediumblob','longblob',
    'json',
    'geometry','point','linestring','polygon',
    'multipoint','multilinestring','multipolygon','geometrycollection'
    )
    AND (
    CHARACTER_MAXIMUM_LENGTH IS NULL
    OR CHARACTER_MAXIMUM_LENGTH <= 255
    )

    ORDER BY ORDINAL_POSITION;
    """
    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
    columns_names = ["`" + row[0] + "`" for row in result]
    columns_names_str = ", ".join(columns_names)

    if table_alias != "":
        columns_names_str = ", ".join([f"`{table_alias}`.{col}" for col in columns_names])
    return columns_names_str

def prepare_to_fill_queries():
    
    global target_table_query
    global children_tables_queries
    global another_parents_of_children_tables_queries
    global parent_tables_queries
    global sibling_tables_queries
    
    target_table_query = []
    children_tables_queries = []
    another_parents_of_children_tables_queries = []
    parent_tables_queries = []
    sibling_tables_queries = []

def fill_target_table_query():
    global target_table_query
    

    columns_names_str = get_filtered_columns_names_of_a_table(config.target_table_name)
    
    sql_query = f"select distinct {columns_names_str} from {config.target_table_name} "
    sql_query += f" where {prepare_target_table_selected_data_points_condition_str(pk_columns_names_of_target_table_str, selected_datapoints)} "

    
    
    target_table_query.append((config.target_table_name, sql_query))


def fill_children_tables_queries():
    global children_tables_queries
    
    
    pk_columns_str = ", ".join([f"target_table.{col}" for col in pk_columns_names_of_target_table])

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if parent_table == config.target_table_name:
            
            join_condition_str = ""
            for k, v in join_condition.items():
                join_condition_str += f"child_table.{k} = target_table.{v} and "
            join_condition_str = join_condition_str[:-5] + " "
            
            columns_names_str = get_filtered_columns_names_of_a_table(child_table, "child_table")
            
            sql_query = f"select distinct {columns_names_str} "
            sql_query += f" from {config.target_table_name} target_table inner join {child_table} child_table on "
            sql_query += join_condition_str
            sql_query += f" where {prepare_target_table_selected_data_points_condition_str(pk_columns_str, selected_datapoints)} "
            
            
            children_tables_queries.append((child_table, sql_query))


def fill_children_parents_tables_queries():
    global another_parents_of_children_tables_queries
    
    pk_columns_str = ", ".join([f"target_table.{col}" for col in pk_columns_names_of_target_table])

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if parent_table == config.target_table_name:

            join_condition_str = ""
            for k, v in join_condition.items():
                join_condition_str += f"child_table.{k} = target_table.{v} and "
            join_condition_str = join_condition_str[:-5] + " "

            for d2 in dependencies:
                another_parent = d2[0]
                if d2[1] == child_table and another_parent != parent_table:
                    
                    columns_names_str = get_filtered_columns_names_of_a_table(another_parent, "another_parent_table")
                    
                    sql_query = f"select distinct {columns_names_str} "
                    sql_query += f" from {config.target_table_name} target_table inner join {child_table} child_table on "
                    sql_query += join_condition_str
                    sql_query += f" inner join {another_parent} another_parent_table on "
                    for k, v in d2[2].items():
                        sql_query += f"another_parent_table.{v} = child_table.{k} and "
                    sql_query = sql_query[:-5] + " "
                    sql_query += f" where {prepare_target_table_selected_data_points_condition_str(pk_columns_str, selected_datapoints)} "


                    another_parents_of_children_tables_queries.append((another_parent, sql_query))

    
    

def fill_parent_tables_queries():
    global parent_tables_queries
    
    pk_columns_str = ", ".join([f"target_table.{col}" for col in pk_columns_names_of_target_table])

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if child_table == config.target_table_name:
            
            join_condition_str = ""
            for k, v in join_condition.items():
                join_condition_str += f"target_table.{k} = parent_table.{v} and "
            join_condition_str = join_condition_str[:-5] + " "

            columns_names_str = get_filtered_columns_names_of_a_table(parent_table, "parent_table")

            sql_query = f"select distinct {columns_names_str} "
            sql_query += f" from {config.target_table_name} target_table inner join {parent_table} parent_table on "
            sql_query += join_condition_str
            sql_query += f" where {prepare_target_table_selected_data_points_condition_str(pk_columns_str, selected_datapoints)} "


            parent_tables_queries.append((parent_table, sql_query))

    
def fill_sibling_tables_queries():
    global sibling_tables_queries
    
    pk_columns_str = ", ".join([f"target_table.{col}" for col in pk_columns_names_of_target_table])

    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    for d in dependencies:
        parent_table = d[0]
        child_table = d[1]
        join_condition = d[2]
        if child_table == config.target_table_name:

            join_condition_str = ""
            for k, v in join_condition.items():
                join_condition_str += f"target_table.{k} = parent_table.{v} and "
            join_condition_str = join_condition_str[:-5] + " "

            for d2 in dependencies:
                sibling_table = d2[1]
                if d2[0] == parent_table and sibling_table != config.target_table_name:
                    columns_names_str = get_filtered_columns_names_of_a_table(sibling_table, "sibling_table")

                    sql_query = f"select distinct {columns_names_str} "
                    sql_query += f" from {config.target_table_name} target_table inner join {parent_table} parent_table on "
                    sql_query += join_condition_str
                    sql_query += f" inner join {sibling_table} sibling_table on "
                    for k, v in d2[2].items():
                        sql_query += f"sibling_table.{k} = parent_table.{v} and "
                    sql_query = sql_query[:-5] + " "
                    sql_query += f" where {prepare_target_table_selected_data_points_condition_str(pk_columns_str, selected_datapoints)} "


                    sibling_tables_queries.append((sibling_table, sql_query))


def get_selected_potential_data_points():

    pk_columns_names_of_target_table_str = ""

    pk_columns_names_of_target_table = get_pk_columns_names_of_a_table(config.target_table_name)
    
    for pk_col in pk_columns_names_of_target_table:
        pk_columns_names_of_target_table_str += f"{pk_col}, "
        
    if len(pk_columns_names_of_target_table) == 0:
        return config.target_table_name
    
    pk_columns_names_of_target_table_str = pk_columns_names_of_target_table_str[:-2]
    
    sql_query = f"SELECT count(*) FROM {config.target_table_name} WHERE {config.target_column_name} IS NOT NULL;"

        
    results, _, _, _ = execute_query_and_get_results_with_headers(sql_query)
        

    print(f"count of rows in target table is: {results[0][0]}")

    selected_potential_data_points_sql_query = config.target_table_name

    condition_str = ""

    if results[0][0] > config.maximum_potential_data_points_in_target_table:

        sql_query = f"SELECT {pk_columns_names_of_target_table_str} FROM {config.target_table_name} WHERE {config.target_column_name} IS NOT NULL ORDER BY RAND() LIMIT {config.maximum_potential_data_points_in_target_table};"



        results, _, _, _ = execute_query_and_get_results_with_headers(sql_query)


        

        selected_potential_data_points_sql_query = f"(select * from {config.target_table_name} where "

        
        
        for r in results: 
            condition_str += "("
            
            i = 0
            for pk_col in pk_columns_names_of_target_table:
                condition_str += f"{pk_col} = '{r[i]}' and "
                i += 1
            condition_str = condition_str[:-5]

            condition_str += ") or "
        condition_str = condition_str[:-4]

        selected_potential_data_points_sql_query += condition_str

        selected_potential_data_points_sql_query += ") "
            
        

    return selected_potential_data_points_sql_query, condition_str
    








pk_columns_names_of_target_table = []
pk_columns_names_of_target_table_str = ""

def prepare_statistics_of_target_table():
    
    global data_sharing_table
    global pk_columns_names_of_target_table
    global pk_columns_names_of_target_table_str

    data_sharing_table = ""
    
    dependencies, headers = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])


    selected_potential_data_points_str, condition_str = get_selected_potential_data_points()
    

    children_tables_query = get_children_tables_cardinality(dependencies, config.target_table_name, config.target_column_name, selected_potential_data_points_str)
    
    
    sibling_tables_query = get_sibling_tables_cardinality(dependencies, config.target_table_name, config.target_column_name, selected_potential_data_points_str)
    

    pk_columns_names_of_target_table = get_pk_columns_names_of_a_table(config.target_table_name)

    if len(pk_columns_names_of_target_table) == 0:
        return
    
    pk_columns_names_of_target_table_str = ""
    join_condition = ""
    for pk_col in pk_columns_names_of_target_table:
        pk_columns_names_of_target_table_str += f"{pk_col}, "
        join_condition += f"children_tables_info.{pk_col} = sibling_tables_info.{pk_col} and "
    pk_columns_names_of_target_table_str = pk_columns_names_of_target_table_str[:-2]
    join_condition = join_condition[:-5] + " "


    # Inputs you already have:
    # children_tables_query: SQL subquery for the children side (string)
    # sibling_tables_query:  SQL subquery for the sibling side (string)
    # join_condition: e.g., "children_tables_info.id = sibling_tables_info.id"
    # pk_columns: list of join key column names (same on both sides), e.g. ["id"] or ["k1","k2"]
    # pk_columns_str: a projection string for the PKs if you want them at the front; e.g. "children_tables_info.id"

    # Build null-predicate clauses automatically for multi-column keys
    sibling_null_predicate = " AND ".join([f"sibling_tables_info.{col} IS NULL" for col in pk_columns_names_of_target_table])
    children_null_predicate = " AND ".join([f"children_tables_info.{col} IS NULL" for col in pk_columns_names_of_target_table])

    # If your ON clause is symmetric (most equality joins are), we can reuse it.
    # If you have side-specific predicates, define a swapped version accordingly.
    join_condition_swapped = join_condition

    children_tables_info_pk_columns_str = ""
    sibling_tables_info_pk_columns_str = ""
    for col in pk_columns_names_of_target_table:
        children_tables_info_pk_columns_str += f"children_tables_info.{col}, "
        sibling_tables_info_pk_columns_str += f"sibling_tables_info.{col}, "
    children_tables_info_pk_columns_str = children_tables_info_pk_columns_str[:-2]
    sibling_tables_info_pk_columns_str = sibling_tables_info_pk_columns_str[:-2]


    non_key_columns_str = """
        ifnull(children_tables_info.number_of_matching_children_tables, 0) number_of_matching_children_tables, 
        ifnull(children_tables_info.number_of_matching_rows_in_all_children, 0) number_of_matching_rows_in_all_children,  
        ifnull(children_tables_info.estimated_size_of_all_children_rows, 0) estimated_size_of_all_children_rows,  
        ifnull(children_tables_info.total_number_of_other_parents_of_all_children_tables, 0) total_number_of_other_parents_of_all_children_tables,  
        ifnull(children_tables_info.maximum_estimated_size_of_all_children_rows_including_their_other_parents, 0) maximum_estimated_size_of_all_children_rows_including_their_other_parents, 
        ifnull(sibling_tables_info.number_of_sibling_tables, 0) number_of_sibling_tables, 
        ifnull(sibling_tables_info.number_of_rows_of_all_sibling_tables, 0) number_of_rows_of_all_sibling_tables, 
        ifnull(sibling_tables_info.sum_of_parent_tables_rows_sizes, 0) sum_of_parent_tables_rows_sizes, 
        ifnull(sibling_tables_info.estimated_size_of_all_sibling_rows, 0) estimated_size_of_all_sibling_rows
    """
    
    data_sharing_table_inner = f"""
    (
    -- 1) Inner matches (A ∩ B)
    SELECT
        {children_tables_info_pk_columns_str}, children_tables_info.target_column target_column,
        {non_key_columns_str}
    FROM ({children_tables_query}) AS children_tables_info
    JOIN ({sibling_tables_query})  AS sibling_tables_info
        ON {join_condition}
    WHERE children_tables_info.target_column is not null
    )
    UNION ALL
    (
    -- 2) Children-only (A \\ B)
    SELECT
        {children_tables_info_pk_columns_str}, children_tables_info.target_column target_column, 
        {non_key_columns_str}
    FROM ({children_tables_query}) AS children_tables_info
    LEFT JOIN ({sibling_tables_query})  AS sibling_tables_info
        ON {join_condition}
    WHERE {sibling_null_predicate} and children_tables_info.target_column is not null
    )
    UNION ALL
    (
    -- 3) Sibling-only (B \\ A)
    SELECT
        {sibling_tables_info_pk_columns_str}, sibling_tables_info.target_column target_column,
        {non_key_columns_str}
    FROM ({sibling_tables_query})  AS sibling_tables_info
    LEFT JOIN ({children_tables_query}) AS children_tables_info
        ON {join_condition_swapped}
    WHERE {children_null_predicate} and sibling_tables_info.target_column is not null
    )
    """

    data_sharing_table = f"select * from ({data_sharing_table_inner}) data_sharing_table "
    if condition_str != "":
        data_sharing_table += f"where {condition_str} "



selected_datapoints = []

def select_data_points():
    global selected_datapoints

    selected_datapoints = []

    if data_sharing_table == "":
        return
    
    is_only_children_mode = False
    selected_datapoints = select_data_for_sharing()


    

def fill_tables_for_sending():

    prepare_to_fill_queries()

    if len(selected_datapoints) == 0:
        return
    
    fill_target_table_query()
    fill_children_tables_queries()
    fill_children_parents_tables_queries()
    fill_parent_tables_queries()
    fill_sibling_tables_queries()



    
tables_rows_to_be_shared_list = []
tables_rows_to_be_shared = {}


def add_to_tables_rows_to_be_shared(table_name: str, query_str: str, union_keyword: str = "UNION"):
    """
    Insert a new query into tables_rows_to_be_shared[table_name] if the key does not exist.
    Otherwise, append `UNION <query_str>` to the existing value.

    Args:
        table_name (str): The dict key.
        query_str (str): The SQL subquery to add.
        union_keyword (str): UNION operator, e.g., "UNION" or "UNION ALL".
    """
    global tables_rows_to_be_shared
    global tables_rows_to_be_shared_list

    if table_name not in tables_rows_to_be_shared_list:
        tables_rows_to_be_shared_list.append(table_name)

    if not query_str or not query_str.strip():
        # Ignore empty or whitespace-only queries
        return

    # Normalize spacing and wrap each query in parentheses
    new_part = f"({query_str.strip()})"

    existing = tables_rows_to_be_shared.get(table_name)
    if existing is None or not str(existing).strip():
        # First insert
        tables_rows_to_be_shared[table_name] = new_part
    else:
        # Append with UNION / UNION ALL; ensure spacing
        union_op = union_keyword.strip().upper()  # "UNION" or "UNION ALL"
        tables_rows_to_be_shared[table_name] = f"{existing.strip()} {union_op} {new_part}"

data_sharing_prompt_text = ""
def prepare_data_sharing():

    global data_sharing_max_limit_in_bytes
    global tables_rows_to_be_shared_list
    global tables_rows_to_be_shared
    global data_sharing_prompt_text

    data_sharing_max_limit_in_bytes = ceil(config.data_sharing_size_limit_in_bytes / 2)

    prepare_statistics_of_target_table()
    
    try_number = 0
    increase_try_number = 1

    try_info = []
    
    number_of_data_points_for_now = 0

    while try_number < 5:

        data_sharing_max_limit_in_bytes = ceil(data_sharing_max_limit_in_bytes * 2)

        try_number += 1

        tables_rows_to_be_shared_list = []
        tables_rows_to_be_shared = {}

        select_data_points()


        if len(selected_datapoints) > number_of_data_points_for_now:
            number_of_data_points_for_now = len(selected_datapoints)
        else:
            continue

        fill_tables_for_sending()

        if len(target_table_query) == 0:
            continue

        target_table_name = target_table_query[0][0]
        target_table_query_str = target_table_query[0][1]
        
        columns = get_columns_of_a_table(target_table_name)
        columns_names_str = ""
        for col in columns:
            columns_names_str += f"{col[0]}, "
        columns_names_str = columns_names_str[:-2]


        add_to_tables_rows_to_be_shared(target_table_name, target_table_query_str)

        for parent_table_tuple in parent_tables_queries:
            parent_table_name = parent_table_tuple[0]
            parent_table_query_str = parent_table_tuple[1]


            add_to_tables_rows_to_be_shared(parent_table_name, parent_table_query_str)

        for child_table_tuple in children_tables_queries:
            child_table_name = child_table_tuple[0]
            child_table_query_str = child_table_tuple[1]


            add_to_tables_rows_to_be_shared(child_table_name, child_table_query_str)

        for another_parent_table_tuple in another_parents_of_children_tables_queries:
            another_parent_table_name = another_parent_table_tuple[0]
            another_parent_table_query_str = another_parent_table_tuple[1]


            add_to_tables_rows_to_be_shared(another_parent_table_name, another_parent_table_query_str)
        

        for sibling_table_tuple in sibling_tables_queries:
            sibling_table_name = sibling_table_tuple[0]
            sibling_table_query_str = sibling_table_tuple[1]


            add_to_tables_rows_to_be_shared(sibling_table_name, sibling_table_query_str)

        prompt_text = get_tables_rows_to_be_shared_list_as_prompt()



        expected_number_of_tockens = ceil(len(prompt_text)/4)

        if expected_number_of_tockens > config.data_sharing_max_number_of_tockens:
            if try_number == 1:
                print(f"XXXXXXXXXXXXXXXXXXXXXXXXXXXX No data sharing XXXXXXXXXXXXXXXXXXXXXXXXXXXX\n")
            break



        

        try_info.append((try_number, expected_number_of_tockens, selected_datapoints, tables_rows_to_be_shared, prompt_text))

        if number_of_data_points_for_now >= config.number_of_data_points_from_target_table_to_send:
            break



        

    selected_try = None

    for t in try_info:
        try_number = t[0]
        try_expected_number_of_tockens = t[1]
        try_number_of_selected_data_points = t[2]
        try_tables_rows_to_be_shared = t[3]
        try_prompt_text = t[4]

        if try_expected_number_of_tockens < config.data_sharing_max_number_of_tockens:
            if selected_try is None:
                selected_try = t
                
            
            selected_try_expected_number_of_tockens = selected_try[1]
            selected_try_number_of_selected_data_points = selected_try[2]

            if len(selected_try_number_of_selected_data_points) > 1:
                selected_try_effeciency = len(selected_try_number_of_selected_data_points) / selected_try_expected_number_of_tockens
                current_try_effeciency = len(try_number_of_selected_data_points) / try_expected_number_of_tockens
                if current_try_effeciency > selected_try_effeciency:
                    selected_try = t

        #else:

    report.data_sharing_number_of_tries = len(try_info)

    
    if selected_try is not None:
        data_sharing_prompt_text = selected_try[4]
        report.data_sharing_selected_try_number = selected_try[0]
        report.size_number_of_shared_data_points_in_tockens = selected_try[1]
        report.number_of_shared_data_points = len(selected_try[2])
        return data_sharing_prompt_text
    
    return ""
        




    




def get_tables_rows_to_be_shared_list_as_prompt():
    
    prompt_str = ""

    for table_name in tables_rows_to_be_shared_list:
        prompt_str += f" Here are rows from table {table_name}"

        columns = get_columns_of_a_table(table_name)
        columns_names_str = ""
        for col in columns:
            columns_names_str += f"{col[0]}, "
        columns_names_str = columns_names_str[:-2]

        tables_rows_to_be_shared_query_str = tables_rows_to_be_shared[table_name]

        
        results, headers, _, _ = execute_query_and_get_results_with_headers(tables_rows_to_be_shared_query_str)
        

        if results is not None and len(results) > 0:
            prompt_str += f": columns names are ({columns_names_str}) rows are {results}. "
        
        

        
    
    return prompt_str

def get_tables_names_of_a_database():
   
    sql_query = f"""SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = '{config.target_database_name}'
"""

    
    tables, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

    tables = [row[0] for row in tables]
    

    return tables


def get_columns_of_a_table(table_name: str):
    sql_query = f"SHOW COLUMNS FROM {table_name};"

    
    
    columns, _, _, _ = execute_query_and_get_results_with_headers(sql_query)
    

    return columns

def get_pk_columns_names_of_a_table(table_name: str):
    
    sql_query = f"SHOW KEYS FROM {table_name} WHERE Key_name = 'PRIMARY';"
    
    
    pk_columns_names, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

    pk_columns_names = [row[4] for row in pk_columns_names]
    

    

    if len(pk_columns_names) == 0:
        
        sql_query = f"""
        SELECT
            s.Column_name,
            MAX(s.cardinality) AS max_cardinality
        FROM information_schema.statistics AS s
        WHERE s.table_schema = DATABASE()
            AND s.table_name   = '{table_name}'
        GROUP BY s.Column_name
        ORDER BY max_cardinality DESC limit 1;
        """


    
        k_column_name_with_highest_cardinality, _, _, _ = execute_query_and_get_results_with_headers(sql_query)


        if len(k_column_name_with_highest_cardinality) > 0:

            k_column_name_with_highest_cardinality, k_cardinality_name_with_highest_cardinality = k_column_name_with_highest_cardinality[0]

            sql_query = f"SELECT count(*) cnt FROM {table_name} where `{k_column_name_with_highest_cardinality}` is not null;"

    
            cnt, _, _, _ = execute_query_and_get_results_with_headers(sql_query)


            number_of_distinct_values = cnt[0][0]

            #TODO detect composite pk: usecase GOSales.go_daily_sales.Quantity

            if number_of_distinct_values == k_cardinality_name_with_highest_cardinality or number_of_distinct_values == k_cardinality_name_with_highest_cardinality -1:
                pk_columns_names = []
                pk_columns_names.append(k_column_name_with_highest_cardinality)

    return pk_columns_names

def get_fk_columns_names_of_a_table(table_name: str):
    
    sql_query = f"""
    SELECT COLUMN_NAME 
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE 
    WHERE TABLE_NAME = '{table_name}' 
    AND TABLE_SCHEMA = '{config.target_database_name}' 
    AND REFERENCED_TABLE_NAME IS NOT NULL
    """
    
    
    fk_columns_names, _, _, _ = execute_query_and_get_results_with_headers(sql_query)

    fk_columns_names = [row[0] for row in fk_columns_names]
    

    return fk_columns_names


def get_columns_info_of_a_table(table_name: str):

    columns = get_columns_of_a_table(table_name)

    pk_columns_names = get_pk_columns_names_of_a_table(table_name)

    fk_columns_names = get_fk_columns_names_of_a_table(table_name)

    table_columns = []
        
    column_order_in_table = 0
    
    for column in columns:
        col_name = column[0]
        data_type = column[1]
        main_data_type = ""
        is_PK = col_name in pk_columns_names
        is_FK = col_name in fk_columns_names
        
        skip_min_max_avg = False
        if data_type == "geometry" or "char" in data_type:
            skip_min_max_avg = True
        column_statistics = get_statistics_of_a_column(table_name, col_name, skip_min_max_avg)

        column_order_in_table += 1

        number_of_distinct_values = 0
        number_of_non_null_values = 0

        if column_statistics["number_of_distinct_values"] is not None:
            number_of_distinct_values = column_statistics["number_of_distinct_values"]
        if column_statistics["total_number_of_values"] is not None and column_statistics["number_of_null_values"] is not None:
            number_of_non_null_values = column_statistics["total_number_of_values"] - column_statistics["number_of_null_values"]
        
        column_statistics["is_category"] = False
        if "int" in data_type or "year" in data_type:
            main_data_type = "integer"
            if number_of_distinct_values < 100 and number_of_non_null_values > 1000:
                column_statistics["is_category"] = True
        elif "date" in data_type or "datetime" in data_type or "time" in data_type or "timestamp" in data_type:
            main_data_type = "date and/or time"
        elif "decimal" in data_type or "double" in data_type or "float" in data_type:
            main_data_type = "float"
        elif "char" in data_type:
            main_data_type = "string"
            if number_of_distinct_values < 100 and number_of_non_null_values > 1000:
                column_statistics["is_category"] = True    
        elif "bit" in data_type:
            main_data_type = "boolean"
        elif "enum" in data_type:
            main_data_type = "string"
            column_statistics["is_category"] = True
        
        if main_data_type == "": # not supported data type
            print(f"Non supported data type: {config.target_database_name}.{table_name}.{col_name} ({data_type})")
            continue

        table_columns.append((column_order_in_table, col_name, is_PK, is_FK, data_type, main_data_type, column_statistics))
    
    
    return table_columns

def rename_table_in_database(old_table_name: str, new_table_name: str):
    
    sql_query = f"RENAME TABLE {old_table_name} to {new_table_name};"



    execute_query(sql_query)

    

def rename_column_in_database(table_name: str, old_column_name: str, new_column_name: str):
    
    sql_query = f"ALTER TABLE {table_name} RENAME COLUMN `{old_column_name}` TO `{new_column_name}`;"



    execute_query(sql_query)



def get_column_distribution(tbl_name: str, col_name: str):
    
    sql_query = f"SELECT `{col_name}` value, COUNT(*) frequency FROM {tbl_name} GROUP BY `{col_name}`"

    
    column_distribution_values, column_distribution_headers, _, _ = execute_query_and_get_results_with_headers(sql_query)

    
    column_values_distribution_list = column_distribution_headers
    column_values_distribution_list += column_distribution_values

    
        
    
    return column_values_distribution_list


def get_statistics_of_a_column(table_name: str, column_name: str, skip_min_max_avg: bool = False): #TODO: customized metadata and detect classes

    sql_query = f"""
    
    SELECT 
        MIN(`{column_name}`) AS min_value, 
        (
            SELECT `{column_name}`
            FROM {table_name}
            WHERE `{column_name}` > (SELECT MIN(`{column_name}`) FROM {table_name})
            ORDER BY `{column_name}` ASC
            LIMIT 1
        ) AS second_min_value, 
        MAX(`{column_name}`) AS max_value, 
        (
            SELECT `{column_name}`
            FROM {table_name}
            WHERE `{column_name}` < (SELECT MAX(`{column_name}`) FROM {table_name})
            ORDER BY `{column_name}` DESC
            LIMIT 1
        ) AS second_max_value,
        AVG(`{column_name}`) AS average_value, 
        COUNT(DISTINCT `{column_name}`) AS number_of_distinct_values, 
        SUM(CASE WHEN `{column_name}` IS NULL THEN 1 ELSE 0 END) AS number_of_null_values,
        COUNT(*) AS total_number_of_values
    FROM {table_name};
    """

    if skip_min_max_avg:
        sql_query = f"""
        SELECT 
            COUNT(DISTINCT `{column_name}`) AS number_of_distinct_values, 
            SUM(CASE WHEN `{column_name}` IS NULL THEN 1 ELSE 0 END) AS number_of_null_values,
            COUNT(*) AS total_number_of_values
        FROM {table_name};
        """




    int_column_statistics_values, int_column_statistics_headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
    

    int_column_statistics = {}

    int_column_statistics_values = int_column_statistics_values[0]
    
    number_of_distinct_values = 0
    number_of_null_values = 0
    total_number_of_values = 0
    for index, value in enumerate(int_column_statistics_headers):
        int_column_statistics[int_column_statistics_headers[index]] = int_column_statistics_values[index]
        if int_column_statistics_values[index] is not None:
            if int_column_statistics_headers[index] == 'number_of_distinct_values':
                number_of_distinct_values = int_column_statistics_values[index]
            elif int_column_statistics_headers[index] == 'number_of_null_values':
                number_of_null_values = int_column_statistics_values[index]
            elif int_column_statistics_headers[index] == 'total_number_of_values':
                total_number_of_values = int_column_statistics_values[index]
    
    distinct_values_ratio = 0
    is_categorical = False
    if (total_number_of_values - number_of_null_values) > 0:
        distinct_values_ratio = number_of_distinct_values / (total_number_of_values - number_of_null_values)
        if distinct_values_ratio < 0.05:
            is_categorical = True
    
    int_column_statistics['is_categorical'] = is_categorical


    if is_categorical and number_of_distinct_values < 100:
        column_values_distribution_list = get_column_distribution(table_name, column_name)
        int_column_statistics['column_values_distribution'] = column_values_distribution_list

        




    

    return int_column_statistics

def get_join_condition_as_dict(join_condition_str):

    # Split by AND
    conditions = join_condition_str.split("AND")

    join_dict = {}

    for condition in conditions:
        left, right = condition.split("=")
        left_col = left.strip().split(".")[-1]
        right_col = right.strip().split(".")[-1]
        join_dict[left_col] = right_col

    return join_dict

def get_tables_dependencies_in_the_database():
    
    sql_query = f"""

SELECT
  kcu.REFERENCED_TABLE_NAME AS parent_table,
  kcu.TABLE_NAME            AS child_table,
  GROUP_CONCAT(DISTINCT
    CONCAT(
      'parent_table.', kcu.COLUMN_NAME,
      ' = ',
      'child_table.', kcu.REFERENCED_COLUMN_NAME
    )
    ORDER BY COALESCE(kcu.POSITION_IN_UNIQUE_CONSTRAINT, kcu.ORDINAL_POSITION)
    SEPARATOR ' AND '
  ) AS join_condition
FROM information_schema.KEY_COLUMN_USAGE AS kcu
WHERE kcu.CONSTRAINT_SCHEMA       = '{config.target_database_name}'
  AND kcu.REFERENCED_TABLE_SCHEMA = '{config.target_database_name}'
  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL         -- only FK rows
GROUP BY
  kcu.REFERENCED_TABLE_NAME,
  kcu.TABLE_NAME,
  kcu.CONSTRAINT_NAME
ORDER BY parent_table, child_table;

    """


    
    dependencies, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
    

    return dependencies, headers


def validate_a_query_generated_from_llm_and_rewrite_if_needed(sql_query: str, chat_history_key : str = ""):
    
    
    is_succeed, new_query = validate_a_non_guarenteed_query_and_rewrite_if_needed(sql_query, chat_history_key)

    if not is_succeed:
        flush_cursor()


    return is_succeed, new_query




def execute_validation_query_and_get_accuracy(query: str):

    validation_sql_query = query
    

    result, headers, validation_sql_query, query_validation_succeed = execute_query_and_get_results_with_headers(validation_sql_query, True, 1)


    if not query_validation_succeed:
        return -2, ""

    number_of_matches = 0
    number_of_mismatches = 0


    if result == None or result[0] == None or result[1] == None:
        return -2, ""
    elif result[0] == "NULL" or result[1] == "NULL":
        return -2, ""        
    else:
        if "matches" in headers[0] and "mismatches" in headers[1]:
            number_of_matches = result[0]
            number_of_mismatches = result[1]
        elif "mismatches" in headers[0] and "matches" in headers[1]:        
            number_of_mismatches = result[0]
            number_of_matches = result[1]
            
        if (number_of_matches + number_of_mismatches) > 0:
            accuracy = 100 * number_of_matches / (number_of_matches + number_of_mismatches)
            return accuracy, validation_sql_query
            
    return -2, ""


def execute_diagnoses_query_and_result_as_string(diagnoses_sql_qry: str):
    
    
    diagnoses_sql_query = diagnoses_sql_qry

    result, headers, diagnoses_sql_query, diagnoses_validation_succeed = execute_query_and_get_results_with_headers(diagnoses_sql_query, False)

    if not diagnoses_validation_succeed:
        return ""

    diagnoses_sql_query_result_str = "(" + str(headers[0]) + " - " + str(headers[1]) + ") " 

    for r in result:
        diagnoses_sql_query_result_str += "(" + str(r[0]) + " - " + str(r[1]) + ") "
        
    return diagnoses_sql_query_result_str



def get_distinct_values_str(database_name: str, tbl_name: str, col_name: str):
    
    sql_query = f"SELECT DISTINCT `{col_name}` FROM {tbl_name} WHERE `{col_name}` IS NOT NULL LIMIT {config.data_sharing_strategy_2_number_of_distinct_samples};"


    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
    

    
    distinct_values_str = ""
    for distinct_value in result:
        distinct_values_str += f"{distinct_value[0]}, "
    distinct_values_str = distinct_values_str[:-2]


    return distinct_values_str


def get_distinct_values_list(database_name: str, tbl_name: str, col_name: str):
    
    sql_query = f"SELECT DISTINCT `{col_name}` FROM {tbl_name} WHERE `{col_name}` IS NOT NULL LIMIT 100;"


    result, headers, _, _ = execute_query_and_get_results_with_headers(sql_query)
    

    
    distinct_values_list = []
    for distinct_value in result:
        distinct_values_list.append(distinct_value[0])

    return distinct_values_list