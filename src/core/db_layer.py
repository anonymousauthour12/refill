
import json
import logging
import re
import subprocess
from contextlib import contextmanager
from time import time
import yaml
from pathlib import Path
import mysql.connector

import time

from src.core import file_utils, llm_layer
from src.core import prompt_templates as pt
from src.core.config import config
from src.core.kill_tracer import log_kill_event
from src.core.utils import get_json_object

logging.basicConfig(level=logging.INFO)

from dataclasses import dataclass
import logging
import mysql.connector
from typing import List, Tuple, Any, Optional


@dataclass
class DBPerformanceMetrics:
    number_of_calls_to_db: int = 0
    total_db_time: int = 0
    number_of_guarenteed_queries: int = 0
    number_of_non_guarenteed_queries: int = 0
    number_of_errors_of_non_guarenteed_queries: int = 0

db_metrics = DBPerformanceMetrics()


def _log_warning(message: str):
    if not config.work_space:
        return
    try:
        import os
        with open(os.path.join(config.work_space, "warnings.log"), "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


_SLOW_QUERY_THRESHOLD_MS = 5 * 60 * 1000  # 5 minutes

def _log_slow_query(query: str, duration_ms: int):
    if duration_ms < _SLOW_QUERY_THRESHOLD_MS:
        return
    if not config.work_space:
        return
    try:
        import os
        col = f"{config.target_database_name}.{config.target_table_name}.{config.target_column_name}"
        with open(os.path.join(config.work_space, "slow_queries.sql"), "a") as f:
            f.write(f"-- [{time.strftime('%Y-%m-%d %H:%M:%S')}] duration={duration_ms}ms  column={col}\n")
            f.write(query.strip())
            f.write(";\n\n")
    except Exception:
        pass
    from src.core.timeout_profiler import log_timeout
    log_timeout("DB_SLOW_QUERY", duration_ms, _SLOW_QUERY_THRESHOLD_MS, query)


# ── module-level state ───────────────────────────────────────────────────────

# Target database name — set by connect_to_db(), used by every _db_conn() call.
database: str = None

# Kept as None stubs so external code that does
#   from src.core.db_layer import cursor, ...
# still works at import time (cursor is imported but never used in callers).
connection = None
cursor = None

# Connection ID of the currently-active per-query connection.
# Updated inside _db_conn() so that kill_running_query() can issue
# KILL QUERY even though there is no persistent connection object.
_active_thread_id: int = None

_QUERY_TIMEOUT_SEC = 700   # Python drops connection if MySQL is silent >11 min

# Path of the file that holds the currently active MySQL thread ID.
# Written when a connection opens, deleted when it closes.  The shell
# wrapper (parallel_experiment.sh) reads this file after the Python
# process exits and issues KILL QUERY so zombie queries cannot survive
# a SIGKILL that bypasses Python's cleanup code.
_THREAD_ID_FILE: str = None


def _write_thread_id_file(tid: int):
    """Write the active MySQL thread ID to disk for shell-level cleanup."""
    global _THREAD_ID_FILE
    if not config.work_space:
        return
    try:
        import os
        _THREAD_ID_FILE = os.path.join(config.work_space, "active_mysql_thread.txt")
        with open(_THREAD_ID_FILE, "w") as f:
            f.write(str(tid))
    except Exception:
        pass


def _clear_thread_id_file():
    """Delete the thread ID file once the connection has been fully cleaned up."""
    global _THREAD_ID_FILE
    try:
        import os
        if _THREAD_ID_FILE and os.path.exists(_THREAD_ID_FILE):
            os.remove(_THREAD_ID_FILE)
    except Exception:
        pass


@contextmanager
def _db_conn():
    """Open a fresh per-query connection with timeout; close on exit.

    When the context exits (normally or via exception) the connection is
    closed and the active MySQL thread ID is killed.  The thread ID is
    also written to active_mysql_thread.txt so that parallel_experiment.sh
    can issue KILL via the shell if the Python process is killed by
    SIGKILL before this cleanup code can run.

    Every abnormal exit and every KILL attempt is written to
    experiments/experiment_XX/kill_trace.log via kill_tracer.log_kill_event().
    """
    global _active_thread_id
    conn = None
    cur = None
    _exit_exc = [None]       # captures exception that caused the with-block to exit
    _query_start = [None]    # wall-clock time right before yield (i.e. query start)

    try:
        conn = mysql.connector.connect(
            host=config.database_host,
            port=config.database_port,
            user=config.database_user,
            password=config.database_pw,
            database=database if database else None,
            read_timeout=_QUERY_TIMEOUT_SEC,    # Python-level hard kill: drop if silent >11 min
            connection_timeout=30,              # fail fast if MySQL is unreachable
        )
        cur = conn.cursor(buffered=True)
        # Skip statistics refresh on INFORMATION_SCHEMA queries.
        # Without this, the first query on a table after a MySQL restart
        # triggers a full table scan to recompute row counts / avg row sizes,
        # which takes hundreds of seconds on large tables (e.g. StackOverflow).
        cur.execute("SET SESSION information_schema_stats_expiry=0")
        cur.execute("SET SESSION MAX_EXECUTION_TIME=600000")
        # All pipeline queries are read-only SELECTs — no writes ever.
        # READ ONLY  : lets InnoDB skip write-path overhead and makes threads
        #              more responsive to KILL.
        # READ UNCOMMITTED : eliminates all lock waiting; dirty reads are
        #              acceptable since we only need ~80% accuracy threshold.
        cur.execute("SET SESSION TRANSACTION READ ONLY")
        cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        _active_thread_id = conn.connection_id
        _write_thread_id_file(_active_thread_id)
        _query_start[0] = time.time()
        try:
            yield conn, cur
        except BaseException as exc:
            _exit_exc[0] = exc
            raise
    finally:
        elapsed = (time.time() - _query_start[0]) if _query_start[0] else None
        exc = _exit_exc[0]
        tid = _active_thread_id
        _active_thread_id = None

        # ── Log what caused this exit ─────────────────────────────────────
        if exc is not None:
            errno = getattr(exc, "errno", None)
            exc_msg = str(exc)[:200]
            if isinstance(exc, mysql.connector.Error):
                if errno in (3024, 1969):          # MAX_EXECUTION_TIME exceeded
                    log_kill_event("MAX_EXEC_TIME_HIT", tid=tid,
                                   elapsed_sec=elapsed, detail=exc_msg)
                elif errno in (2013, 2055):         # Lost connection / read_timeout
                    log_kill_event("READ_TIMEOUT_HIT", tid=tid,
                                   elapsed_sec=elapsed, detail=exc_msg)
                else:
                    # SQL syntax errors (1064) and other routine DB errors are
                    # normal LLM output handled by the retry loop — only log
                    # them if the query had been running long enough to matter.
                    if elapsed is not None and elapsed > 60:
                        log_kill_event("DB_ERROR", tid=tid,
                                       elapsed_sec=elapsed,
                                       detail=f"errno={errno} | {exc_msg}")
            else:
                # Non-MySQL exception (e.g. socket.timeout, ContextTooLargeError)
                log_kill_event("DB_ERROR", tid=tid,
                               elapsed_sec=elapsed,
                               detail=f"{type(exc).__name__}: {exc_msg}")

        # ── Kill the MySQL thread ─────────────────────────────────────────
        # KILL (without QUERY) terminates the entire MySQL thread, including
        # queries stuck in the 'statistics' phase (optimizer planning), which
        # KILL QUERY and MAX_EXECUTION_TIME cannot touch.
        # Only log kill events for timeout/non-MySQL exceptions, or any query
        # that ran longer than 60 seconds. Fast SQL errors (e.g. errno 1064
        # syntax errors) are routine LLM output handled by the retry loop
        # and should not pollute the kill trace.
        _exc_errno = getattr(exc, "errno", None) if exc is not None else None
        _is_timeout_exc = isinstance(exc, mysql.connector.Error) and _exc_errno in (3024, 1969, 2013, 2055)
        _is_non_mysql_exc = exc is not None and not isinstance(exc, mysql.connector.Error)
        _log_this_kill = _is_timeout_exc or _is_non_mysql_exc or (elapsed is not None and elapsed > 60)
        if tid is not None:
            source = "finally_block"
            if _log_this_kill:
                reason = (f"reason={type(exc).__name__}" if exc is not None
                          else "reason=long_running_cleanup")
                log_kill_event("KILL_ATTEMPT", tid=tid, elapsed_sec=elapsed,
                               detail=f"source={source} | {reason}")
            try:
                killer = mysql.connector.connect(
                    host=config.database_host,
                    port=config.database_port,
                    user=config.database_user,
                    password=config.database_pw,
                    connection_timeout=5,
                )
                killer.cmd_query(f"KILL {tid}")
                killer.close()
                if _log_this_kill:
                    log_kill_event("KILL_SUCCESS", tid=tid, elapsed_sec=elapsed,
                                   detail=f"source={source}", success=True)
                    _verify_kill(tid, elapsed, source)
            except Exception as kill_err:
                if _log_this_kill:
                    log_kill_event("KILL_FAILED", tid=tid, elapsed_sec=elapsed,
                                   detail=f"source={source} | {str(kill_err)[:120]}",
                                   success=False)

        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        # Delete the thread ID file only after full cleanup so that a
        # concurrent shell cleanup sees the ID if Python dies mid-finally.
        _clear_thread_id_file()


def _verify_kill(tid: int, elapsed_sec, source: str):
    """Query processlist to confirm the thread is actually gone after KILL.

    MySQL's KILL is asynchronous — the thread may still appear in processlist
    for a moment (or indefinitely if KILL had no effect).  This check logs:
      KILL_VERIFY_DEAD          — thread is no longer in processlist
      KILL_VERIFY_STILL_RUNNING — thread is still alive (includes state + time)
      KILL_VERIFY_FAILED        — could not open checker connection
    """
    try:
        checker = mysql.connector.connect(
            host=config.database_host,
            port=config.database_port,
            user=config.database_user,
            password=config.database_pw,
            connection_timeout=5,
            read_timeout=3,
        )
        cur = checker.cursor()
        cur.execute(
            "SELECT command, state, time "
            "FROM information_schema.processlist WHERE id = %s",
            (tid,),
        )
        row = cur.fetchone()
        cur.close()
        checker.close()
        if row is None:
            log_kill_event("KILL_VERIFY_DEAD", tid=tid, elapsed_sec=elapsed_sec,
                           detail=f"source={source} | thread not in processlist",
                           success=True)
        else:
            command, state, running_time = row
            log_kill_event("KILL_VERIFY_STILL_RUNNING", tid=tid, elapsed_sec=elapsed_sec,
                           detail=(f"source={source} | command={command}"
                                   f" | state={state} | running_time={running_time}s"),
                           success=False)
    except Exception as e:
        log_kill_event("KILL_VERIFY_FAILED", tid=tid, elapsed_sec=elapsed_sec,
                       detail=f"source={source} | {str(e)[:120]}")


def connect_to_db(db_name=None):
    """Record the target database name.  No persistent connection is opened."""
    global database
    database = db_name
    logging.info(f"connect_to_db: target database set to '{database}'")


def disconnect_from_db():
    """No-op: per-query connections are closed by _db_conn() automatically."""
    pass


def execute_ddl(query: str) -> str:
    """Execute a DDL statement (CREATE TABLE, DROP TABLE, etc.) outside READ-ONLY mode.

    Opens a plain connection (no READ ONLY session setting) so DDL succeeds.
    read_timeout=30 prevents the call from blocking indefinitely when MySQL is
    waiting on a metadata lock (e.g. DROP TABLE blocked by a running query).
    Returns an empty string on success or the error message on failure.
    """
    try:
        conn = mysql.connector.connect(
            host=config.database_host,
            port=config.database_port,
            user=config.database_user,
            password=config.database_pw,
            database=database if database else None,
            connection_timeout=10,
            read_timeout=30,
        )
        cur = conn.cursor()
        cur.execute(query)
        conn.commit()
        cur.close()
        conn.close()
        return ""
    except mysql.connector.Error as err:
        return str(err)


def check_db_connection():
    """No-op: connection validity is ensured inside each _db_conn() call."""
    pass


def flush_cursor():
    """No-op: per-query connections have no shared cursor state to drain."""
    pass


def kill_running_query():
    """Issue KILL for the currently-active per-query connection.

    Called from the SIGTERM handler in main.py.  Works because
    _active_thread_id is set while a _db_conn() context is active.
    """
    log_kill_event("SIGTERM_RECEIVED", tid=_active_thread_id,
                   detail="kill_running_query() called from SIGTERM handler")
    if _active_thread_id is None:
        return
    tid = _active_thread_id
    log_kill_event("KILL_ATTEMPT", tid=tid, detail="source=sigterm_handler")
    try:
        killer = mysql.connector.connect(
            host=config.database_host,
            port=config.database_port,
            user=config.database_user,
            password=config.database_pw,
            connection_timeout=5,
        )
        killer.cmd_query(f"KILL {tid}")
        killer.close()
        log_kill_event("KILL_SUCCESS", tid=tid, detail="source=sigterm_handler", success=True)
        _verify_kill(tid, None, "sigterm_handler")
        _log_warning(f"SIGTERM_KILL | issued KILL {tid}")
    except Exception as e:
        log_kill_event("KILL_FAILED", tid=tid,
                       detail=f"source=sigterm_handler | {str(e)[:120]}", success=False)
        _log_warning(f"SIGTERM_KILL | failed: {e}")


def execute_query(query: str, error_free_guarentee=True):
    logging.info("Execute a query in the database.")

    if not error_free_guarentee:
        print("Validation is needed for the SQL query")

    start_timestamp = int(time.time() * 1000)
    with _db_conn() as (conn, cur):
        cur.execute(query)
        end_timestamp = int(time.time() * 1000)
        duration_ms = end_timestamp - start_timestamp
        db_metrics.total_db_time += duration_ms
        _log_slow_query(query, duration_ms)

    db_metrics.number_of_calls_to_db += 1


def validate_a_non_guarenteed_query_and_rewrite_if_needed(query: str, chat_history_key: str = ""):
    db_metrics.number_of_calls_to_db += 1
    db_metrics.number_of_non_guarenteed_queries += 1

    is_succeed, new_query = execute_non_guarenteed_query_on_cursor(query, chat_history_key)

    return is_succeed, new_query


def execute_query_and_get_results_with_headers(
    query: str,
    error_free_guarentee: bool = True,
    limit: Optional[int] = None,
) -> Tuple[List[Tuple[Any, ...]], List[str]]:
    logging.info("Execute a query in the database.")

    if not error_free_guarentee:
        logging.warning("Validation is needed for the SQL query")

    if limit is not None and limit <= 0:
        raise ValueError("`limit` must be a positive integer when provided.")

    db_metrics.number_of_calls_to_db += 1
    db_metrics.number_of_guarenteed_queries += 1

    # For the non-guaranteed path: validate and LLM-rewrite if needed, then
    # run the final (possibly rewritten) query in a fresh connection below.
    final_query = query
    if not error_free_guarentee:
        is_succeed, final_query = execute_non_guarenteed_query_on_cursor(query)
        if not is_succeed:
            return "", "", final_query, False

    start_timestamp = int(time.time() * 1000)
    try:
        with _db_conn() as (conn, cur):
            cur.execute(final_query)
            end_timestamp = int(time.time() * 1000)
            duration_ms = end_timestamp - start_timestamp
            db_metrics.total_db_time += duration_ms
            _log_slow_query(final_query, duration_ms)

            headers = [desc[0] for desc in cur.description]
            if limit is None:
                result = cur.fetchall()
            elif limit == 1:
                result = cur.fetchone()
            else:
                result = cur.fetchmany(size=limit)
            return result, headers, final_query, True
    except mysql.connector.Error as err:
        end_timestamp = int(time.time() * 1000)
        duration_ms = end_timestamp - start_timestamp
        _log_slow_query(final_query, duration_ms)
        err_str = str(err)
        _log_warning(f"DB_TIMEOUT_OR_ERROR | error={err_str[:120]}")
        return "", [], final_query, False


def db_export_schema():

   global schema_file_path
   global sql_log_file

   print(f"Exporting database: {database}")

   schema_file_path = f"{config.work_space}/schema_{database}.sql"
   sql_log_file = f"{config.work_space}/sql_log.sql"

   command = rf"""
   mysqldump -u {config.database_user} -p{config.database_pw} \
    --no-data --no-tablespaces --skip-add-drop-table --skip-comments --compact {database} \
        | sed -E '/^--/d; /^\/\*!/d' > {schema_file_path}
    """.strip()

   subprocess.run(command, shell=True)


def validate_query(query):

    start_timestamp = int(time.time() * 1000)
    try:
        with _db_conn() as (conn, cur):
            cur.execute(query)
            end_timestamp = int(time.time() * 1000)
            cur.fetchall()  # fetch all rows to trigger full evaluation
            duration_ms = end_timestamp - start_timestamp
            db_metrics.total_db_time += duration_ms
            _log_slow_query(query, duration_ms)
            return ""  # No error
    except mysql.connector.Error as err:
        end_timestamp = int(time.time() * 1000)
        duration_ms = end_timestamp - start_timestamp
        _log_slow_query(query, duration_ms)
        return str(err)


_TIMEOUT_KEYWORDS = (
    "maximum statement execution time exceeded",
    "lost connection to mysql",
    "query execution was interrupted",
)

def _is_timeout_error(err_str: str) -> bool:
    """Return True if the MySQL error string indicates a timeout (not a syntax error)."""
    err_lower = err_str.lower()
    return any(kw in err_lower for kw in _TIMEOUT_KEYWORDS)


def execute_non_guarenteed_query_on_cursor(query: str, chat_history_key: str = ""):

    db_metrics.number_of_calls_to_db += 1
    db_metrics.number_of_non_guarenteed_queries += 1

    execute_query_tries = 0

    err = validate_query(query)

    while err and execute_query_tries < config.execute_query_max_tries:
        db_metrics.number_of_errors_of_non_guarenteed_queries += 1
        _log_warning(f"DB_ERROR | try={execute_query_tries} | error={str(err)[:120]}")

        if _is_timeout_error(err):
            # Query has correct syntax but is too slow — ask LLM to rewrite
            # it using a 1000-row subset with non-NULL, diverse target column values.
            _log_warning(f"TIMEOUT_SUBSET_PROMPT | try={execute_query_tries}")
            prompt_text = pt.prompt_fix_timeout_with_subset(
                query, err,
                config.target_table_name,
                config.target_column_name,
            )
        else:
            prompt_text = pt.prompt_fix_sql_query_error(query, err)

        response = llm_layer.get_response(prompt_text, chat_history_key)
        data = get_json_object(response)
        query = data["computation_sql_query"]

        err = validate_query(query)
        execute_query_tries += 1

    if execute_query_tries < config.execute_query_max_tries:
        file_utils.append_to_file(sql_log_file, "##########################################################################################################################################################################################################################################")
        file_utils.append_to_file(sql_log_file, query)
        execute_query_tries = 0
        return True, query
    else:
        execute_query_tries = 0
        return False, query
