"""Step 2 module"""
from queue import Queue
import logging
import subprocess

from src.core import llm_layer
from src.core import db_layer
from src.core import prompt_templates as pt
from src.core.db_functions import get_tables_dependencies_in_the_database, rename_column_in_database, rename_table_in_database, get_distinct_values_str
from src.core.db_layer import disconnect_from_db
from src.core.utils import get_singular_word, get_json_object
logging.basicConfig(level=logging.INFO)

from src.core import connect_to_db

from src.steps.collect_statistical_metadata import rename_column_in_tables_info, rename_table_in_tables_info, tables_info

from collections import defaultdict, deque

from src.core.config import config

tables_ordered_from_children_to_parents = []
tables_ordered_from_parents_to_children = []
dependencies = []

def traverse_starting_from_children(dependencies: list):
    """
    Traverse tables starting from children first, then their parents.
    Handles multiple parents and multiple children.
    
    Args:
        dependencies (list): [(parent, child, join_condition), ...]
    
    Returns:
        list: Traversal order of tables
    """
    # Build graph and child count
    parents_map = defaultdict(set)  # child -> set of parents
    children_map = defaultdict(set)  # parent -> set of children
    tables = set()

    dependencies = [item for item in dependencies if item[0] != item[1]]

    for parent, child, _ in dependencies:
        children_map[parent].add(child)
        parents_map[child].add(parent)
        tables.add(parent)
        tables.add(child)

    # Count of unvisited children for each parent
    unvisited_children_count = {table: len(children_map.get(table, [])) for table in tables}

    # Start with tables that have no children (true leaves)
    queue = deque([t for t in tables if unvisited_children_count[t] == 0])
    visited = []

    while queue:
        node = queue.popleft()
        visited.append(node)

        # Notify parents that this child is visited
        for parent in parents_map.get(node, []):
            unvisited_children_count[parent] -= 1
            if unvisited_children_count[parent] == 0:

                queue.append(parent)

    return visited

def rename_table(old_table_name: str, new_table_name: str):

    global dependencies
    
    rename_table_in_database(old_table_name, new_table_name)

    tables_ordered_from_children_to_parents[tables_ordered_from_children_to_parents.index(old_table_name)] = new_table_name
    tables_ordered_from_parents_to_children[tables_ordered_from_parents_to_children.index(old_table_name)] = new_table_name

    rename_table_in_tables_info(old_table_name, new_table_name)

    for dependency in dependencies:
        if dependency[0] == old_table_name:
            dependency[0] = new_table_name
        if dependency[1] == old_table_name:
            dependency[1] = new_table_name

    if config.target_table_name == old_table_name:
        config.target_table_name = new_table_name


def rename_tables_with_singular_words():

    for table_name in tables_ordered_from_parents_to_children:
        singular_table_name = get_singular_word(table_name)
        if table_name != singular_table_name:
            rename_table(table_name, singular_table_name)
            

def rename_column(table_name: str, old_column_name: str, new_column_name: str):

    global tables_info
    
    rename_column_in_database(table_name, old_column_name, new_column_name)

    rename_column_in_tables_info(table_name, old_column_name, new_column_name)

    for dependency in dependencies:
        if dependency[0] == table_name:
            join_conditions_dict = dependency[2]
            if old_column_name in join_conditions_dict:
                join_conditions_dict[new_column_name] = join_conditions_dict.pop(old_column_name)
            
        if dependency[1] == table_name:
            join_conditions_dict = dependency[2]
            for k, v in join_conditions_dict.items():
                if v == old_column_name:
                    join_conditions_dict[k] = new_column_name
    
    if config.target_table_name == table_name and config.target_column_name == old_column_name:
        config.target_column_name = new_column_name


def rename_tables():

    print("rename_tables")

    for table_name in tables_ordered_from_parents_to_children:

        llm_layer.flush_chat_history()

        db_layer.db_export_schema()
        _, table_headers, table_sample_rows = pt.get_initial_prompt_str(config.target_database_name, table_name)

        columns = tables_info[table_name]

        column_names_str = ""
        for column in columns:
            column_names_str += column[1] + ", "
        column_names_str = column_names_str[:-2]

        include_data = config.data_sharing_strategy > 3

        prompt_text = pt.prompt_rename_table(
            table_name,
            column_names_str,
            table_headers,
            table_sample_rows,
            include_data=include_data
        )

        response = llm_layer.get_response(prompt_text, "global", False)


        response = response.replace("`", "")
        response = response.strip()
        if len(response.split()) > 1:
            response = llm_layer.get_response(pt.prompt_rename_table_retry(), "global")
            data = get_json_object(response)
            if data and "table_name" in data:
                response = data["table_name"]

        if "representative_name" in response.strip():
            print(f"{table_name} not changed")
        else:
            if table_name.strip() != response.strip():
                print(f"{table_name} -> {response}")
                rename_table(table_name, response)


def rename_columns():

    for table_name in tables_ordered_from_parents_to_children:

        llm_layer.flush_chat_history()

        db_layer.db_export_schema()
        _, table_headers, table_sample_rows = pt.get_initial_prompt_str(config.target_database_name, table_name)

        columns = tables_info[table_name]

        column_names_str = ""
        for column in columns:
            column_names_str += column[1] + ", "
        column_names_str = column_names_str[:-2]



        for column in columns:
            is_PK = column[2]
            is_FK = column[3]

            if is_PK or is_FK:
                continue

            column_name = column[1]

            distinct_values_str = get_distinct_values_str(config.target_database_name, table_name, column_name)

            include_data = config.data_sharing_strategy > 3
            include_distinct_values = config.data_sharing_strategy > 2

            prompt_text = pt.prompt_rename_column(
                column_name,
                table_name,
                column_names_str,
                distinct_values_str,
                table_headers,
                table_sample_rows,
                include_data=include_data,
                include_distinct_values=include_distinct_values
            )

            response = llm_layer.get_response(prompt_text, "global")

            response = response.replace("`", "")
            response = response.strip()
            if len(response.split()) > 1:
                response = llm_layer.get_response(pt.prompt_rename_column_retry(), "global")
                data = get_json_object(response)
                if data and "column_name" in data:
                    response = data["column_name"]

            if "representative_name" in response.strip():
                print(f"{table_name}.{column_name} not changed")
            else:
                if table_name.strip() != response.strip():
                    print(f"{table_name}.{column_name} -> {response}")
                    rename_column(table_name, column_name, response)


def run():

    global tables_ordered_from_children_to_parents
    global tables_ordered_from_parents_to_children
    global dependencies

    """Run step 2 (placeholder)"""
    logging.info("Running Step 2...")


    
    
    dependencies, _ = get_tables_dependencies_in_the_database()

    dependencies = [list(dep) for dep in dependencies]  # one-time conversion

    for d in dependencies:
        d[2] = get_join_condition_as_dict(d[2])

    
    # TODO: What if the database has no pk-fk dependencies -> discovery pk-fk dependencies

    traverse_starting_from_children(dependencies)
    tables_ordered_from_children_to_parents = traverse_starting_from_children(dependencies)
    tables_ordered_from_parents_to_children = tables_ordered_from_children_to_parents[::-1]
    
    rename_tables_with_singular_words()

    rename_tables()
    rename_columns()
