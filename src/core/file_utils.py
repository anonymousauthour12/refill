"""File utilities module"""

import os

import logging
logging.basicConfig(level=logging.INFO)


def is_file_exists(file_path):
    if not os.path.exists(file_path):
        return False
    return True

def create_file_if_not_exists(file_path):
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            pass  # Creates an empty file

def delete_file_if_exists(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)

def append_to_file(file_path: str, text_to_append: str):
    create_file_if_not_exists(file_path)
    if text_to_append != None:
        with open(file_path, 'a', encoding='utf-8') as file:
            file.write(text_to_append + '\n')

def read_file(path: str) -> str:
    """Read the entire content of a text file and return it as a string."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()




def write_file(path: str, content: str) -> None:
    """Create the file (if missing) and write the given string into it."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

