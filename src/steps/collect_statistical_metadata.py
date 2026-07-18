"""Step 1 module"""
import logging

logging.basicConfig(level=logging.INFO)

from src.core import get_tables_names_of_a_database, get_columns_info_of_a_table

from src.core.config import config

tables_info = {}

def run():
    
    global tables_info
    
    """Run step 1 (placeholder)"""
    logging.info("Running Step 1: Collecting Metadata...")
    
    tables_names = get_tables_names_of_a_database()
    
    for table_name in tables_names:
        tables_info[table_name] = get_columns_info_of_a_table(table_name) 
        for column in tables_info[table_name]:
            column = list(column)
        
    

tables_info = {}

def rename_column_in_tables_info(table_name: str, old_column_name: str, new_column_name: str):
    """
    Renames a column inside tables_info[table_name] by replacing col[1] with new_column_name.
    Expects each column entry to be a tuple/list where index 1 is the column name.
    """
    global tables_info

    # Validate table presence
    if table_name not in tables_info:
        raise KeyError(f"Table '{table_name}' not found in tables_info.")

    columns = tables_info[table_name]
    if not isinstance(columns, list):
        raise TypeError(f"tables_info['{table_name}'] must be a list of column entries.")

    # Find the index of the column to rename
    target_idx = None
    for i, col in enumerate(columns):
        # Ensure the structure is indexable and has at least two elements
        if not hasattr(col, "__getitem__") or len(col) < 2:
            raise ValueError(f"Column entry at index {i} has an unexpected structure: {col}")
        if (str(col[1]).strip() == str(old_column_name).strip()):
            target_idx = i
            break

    if target_idx is None:
        raise ValueError(f"Column '{old_column_name}' not found in table '{table_name}'.")

    #if old_column_name =="end_date":


    # Create a modified entry preserving original type (tuple vs list)
    original_entry = columns[target_idx]
    #if old_column_name =="end_date":
    entry_is_tuple = isinstance(original_entry, tuple)
    mutable_entry = list(original_entry)
    mutable_entry[1] = new_column_name
    updated_entry = tuple(mutable_entry) if entry_is_tuple else mutable_entry

    # **Write it back** in place
    columns[target_idx] = updated_entry

    # Optional: return the updated entry or the whole columns list

def rename_table_in_tables_info(old_table_name: str, new_table_name: str):
    global tables_info
    
    tables_info[new_table_name] = tables_info.pop(old_table_name)