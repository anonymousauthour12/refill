
#!/usr/bin/env python3
"""
Strip all keys and constraints from a MySQL schema dump while preserving only column definitions.

What it does:
- Keeps only CREATE TABLE statements (skips comments, SET statements, DROP TABLE, etc.).
- Removes table-level: PRIMARY KEY, FOREIGN KEY, CONSTRAINT, UNIQUE KEY, KEY, FULLTEXT KEY, SPATIAL KEY.
- Removes inline (column-level): PRIMARY KEY, UNIQUE, REFERENCES ... (foreign key).
- Optionally strips AUTO_INCREMENT from column definitions (default: True), to avoid MySQL errors
  when primary keys are removed (MySQL requires AUTO_INCREMENT to be indexed).

Usage:
    python strip_mysql_keys.py --input path/to/schema.sql --output path/to/new_schema.sql
    # Optional flags:
    --keep-auto-increment    # Keep column-level AUTO_INCREMENT
    --keep-nonfk-indexes     # Keep non-FK indexes (KEY/UNIQUE/FULLTEXT/SPATIAL) - default is to remove all

Notes:
- This script is robust for typical mysqldump output (MySQL 5.7/8.0).
- It preserves table options like ENGINE/CHARSET.
"""

import argparse
import re
from typing import List, Tuple


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_file(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def split_create_table_statement(stmt: str) -> Tuple[str, str, str]:
    """
    Split a CREATE TABLE statement into: prefix (up to the first '('),
    columns block (between outermost parentheses), and suffix (after the matching ')').

    Uses a simple parenthesis depth counter to find the correct closing ')'.
    """
    # Find the first '(' after CREATE TABLE
    m = re.search(r"CREATE\s+TABLE\s.*?\(", stmt, re.IGNORECASE | re.DOTALL)
    if not m:
        return stmt, "", ""
    start = m.end()  # position right after first '('
    depth = 1
    i = start
    while i < len(stmt) and depth > 0:
        ch = stmt[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    if depth != 0:
        # Unbalanced parentheses; return raw
        return stmt, "", ""
    prefix = stmt[:start]
    columns_block = stmt[start - 1:i]  # include both parentheses for convenience
    suffix = stmt[i:]
    # columns_block is like "( ... )"; strip outer parens but keep content
    if columns_block.startswith("(") and columns_block.endswith(")"):
        inner = columns_block[1:-1]
    else:
        inner = columns_block
    return prefix, inner, suffix


def split_top_level_comma_items(s: str) -> List[str]:
    """
    Split a string by commas that are NOT inside parentheses (top-level items).
    Returns a list of definition elements (columns or table constraints).
    """
    items = []
    buf = []
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    # last item
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def looks_like_table_index_or_constraint(item: str) -> bool:
    """
    Detect if a top-level item is a table-level index or constraint we should remove.
    """
    s = item.strip()
    s_upper = s.upper()
    # Table-level keys/constraints
    if s_upper.startswith("PRIMARY KEY"):
        return True
    if "FOREIGN KEY" in s_upper:
        return True
    if s_upper.startswith("CONSTRAINT"):
        return True
    if s_upper.startswith("UNIQUE KEY"):
        return True
    if s_upper.startswith("KEY"):
        return True
    if s_upper.startswith("FULLTEXT KEY"):
        return True
    if s_upper.startswith("SPATIAL KEY"):
        return True
    return False


def sanitize_column_item(
    item: str,
    strip_auto_increment: bool = True,
    strip_inline_unique: bool = True,
    strip_inline_primary: bool = True,
    strip_inline_references: bool = True,
) -> str:
    """
    Remove inline column-level constraints and optional AUTO_INCREMENT.
    """
    s = item

    # Remove inline PRIMARY KEY
    if strip_inline_primary:
        s = re.sub(r"\bPRIMARY\s+KEY\b", "", s, flags=re.IGNORECASE)

    # Remove inline UNIQUE (rare but possible)
    if strip_inline_unique:
        # Careful not to remove 'UNIQUE' in comments or identifiers (unlikely in column defs)
        s = re.sub(r"\bUNIQUE\b", "", s, flags=re.IGNORECASE)

    # Remove inline REFERENCES ... (foreign key at column level)
    if strip_inline_references:
        s = re.sub(r"\bREFERENCES\b.*", "", s, flags=re.IGNORECASE)

    # Optionally remove AUTO_INCREMENT at column level
    if strip_auto_increment:
        s = re.sub(r"\bAUTO_INCREMENT\b", "", s, flags=re.IGNORECASE)

    # Clean up double spaces created by removals
    s = re.sub(r"\s+", " ", s).strip()

    return s


def process_create_table(
    stmt: str,
    keep_nonfk_indexes: bool = False,
    keep_auto_increment: bool = False,
) -> str:
    """
    Return a sanitized CREATE TABLE statement with only column definitions.
    """
    prefix, inner, suffix = split_create_table_statement(stmt)
    if not inner:
        # malformed; return original
        return stmt

    items = split_top_level_comma_items(inner)

    sanitized_items = []
    for it in items:
        it_stripped = it.strip()

        # If it's a table-level index/constraint:
        if looks_like_table_index_or_constraint(it_stripped):
            if keep_nonfk_indexes:
                # Keep only non-FK indexes (drop PRIMARY KEY, FOREIGN KEY, CONSTRAINT)
                up = it_stripped.upper()
                if up.startswith("PRIMARY KEY") or "FOREIGN KEY" in up or up.startswith("CONSTRAINT"):
                    # drop
                    continue
                else:
                    # KEY/UNIQUE/FULLTEXT/SPATIAL without FOREIGN KEY
                    sanitized_items.append(it_stripped)
            else:
                # Remove all table-level keys/constraints
                continue
        else:
            # Column definition: sanitize inline constraints
            sanitized_items.append(
                sanitize_column_item(
                    it_stripped,
                    strip_auto_increment=(not keep_auto_increment),
                    strip_inline_unique=(not keep_nonfk_indexes),
                    strip_inline_primary=True,
                    strip_inline_references=True,
                )
            )

    # Ensure commas are correct
    body = ""
    if sanitized_items:
        body = ",\n  ".join(sanitized_items)
        body = "(\n  " + body + "\n)"
    else:
        # Should not happen, but guard anyway
        body = "(\n  /* no columns after stripping */\n)"

    # Reconstruct statement; keep suffix (ENGINE/CHARSET/etc.)
    out = prefix + body + suffix

    # Optional: normalize table-level AUTO_INCREMENT=n in suffix is okay to keep
    # but if you want to remove table-level auto_increment seed, uncomment below:

    # Remove any accidental ', )' from pathological inputs
    out = re.sub(r",\s*\)", ")", out)

    # Ensure terminator semicolon exists
    if not out.strip().endswith(";"):
        out = out.rstrip() + ";"

    return out


def extract_create_table_statements(schema_text: str) -> List[str]:
    """
    Extract full CREATE TABLE ... ; statements from the schema, preserving each block.
    """
    stmts = []
    i = 0
    text = schema_text

    # Simple scan for 'CREATE TABLE' followed by balanced parsing until semicolon after closing ')'
    while True:
        m = re.search(r"CREATE\s+TABLE\s", text[i:], flags=re.IGNORECASE)
        if not m:
            break
        start = i + m.start()
        # Now capture until the terminating ';'
        # Use a small state machine to ensure we pass the columns block properly.
        j = start
        paren_depth = 0
        seen_first_paren = False
        while j < len(text):
            ch = text[j]
            if ch == "(":
                paren_depth += 1
                seen_first_paren = True
            elif ch == ")":
                if paren_depth > 0:
                    paren_depth -= 1
            elif ch == ";" and seen_first_paren and paren_depth == 0:
                j += 1
                break
            j += 1
        stmts.append(text[start:j])
        i = j

    return stmts




