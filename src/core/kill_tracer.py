"""
kill_tracer.py — append-only log of every MySQL kill event and Python signal.

Output file : experiments/experiment_XX/kill_trace.log
              (parent directory of config.work_space, shared across all workers
               in the same experiment)

CSV columns : timestamp, event, tid, column, elapsed_sec, detail

Events
------
READ_TIMEOUT_HIT     Python socket read_timeout fired; MySQL query still running
MAX_EXEC_TIME_HIT    MySQL MAX_EXECUTION_TIME fired; query killed by MySQL itself
DB_ERROR             Other mysql.connector error exiting a _db_conn() context
KILL_ATTEMPT         KILL {tid} is about to be sent to MySQL
KILL_SUCCESS         KILL {tid} was accepted by MySQL
KILL_FAILED          KILL {tid} could not be sent (killer connection failed)
SIGTERM_RECEIVED     Python _sigterm_handler() was invoked (xargs 1-hour timeout)
SIGKILL_DETECTED     Shell saw Python exited without deleting active_mysql_thread.txt
SHELL_KILL_ATTEMPT   Shell is about to send  mysql -e "KILL {tid}"
SHELL_KILL_SUCCESS   Shell KILL command returned exit 0
SHELL_KILL_FAILED    Shell KILL command returned non-zero
"""

import os
import time as _time

_HEADER = "timestamp,event,tid,column,elapsed_sec,detail\n"


def _log_path():
    """Return kill_trace.log path inside the experiment directory, or None."""
    try:
        from src.core.config import config
        if not config.work_space:
            return None
        # work_space is the per-column dir; experiment dir is its parent
        exp_dir = os.path.dirname(os.path.abspath(config.work_space))
        return os.path.join(exp_dir, "kill_trace.log")
    except Exception:
        return None


def _col():
    try:
        from src.core.config import config
        return (f"{config.target_database_name}."
                f"{config.target_table_name}."
                f"{config.target_column_name}")
    except Exception:
        return "unknown"


def log_kill_event(
    event: str,
    tid=None,
    elapsed_sec=None,
    detail: str = "",
    success=None,
):
    """
    Append one event row to kill_trace.log.

    Parameters
    ----------
    event       : one of the event-type strings listed at the top of this module
    tid         : MySQL thread ID (int), if known
    elapsed_sec : how long the query had been running when the event occurred
    detail      : free-text extra info (commas are escaped to semicolons)
    success     : True / False / None — prepended to detail when not None
    """
    path = _log_path()
    if path is None:
        return
    try:
        ts = _time.strftime("%Y-%m-%d %H:%M:%S")
        tid_str = str(tid) if tid is not None else ""
        elapsed_str = f"{elapsed_sec:.1f}" if elapsed_sec is not None else ""
        if success is not None:
            detail = f"success={success} | {detail}"
        detail_clean = str(detail).replace(",", ";").replace("\n", " ")[:250]
        row = f"{ts},{event},{tid_str},{_col()},{elapsed_str},{detail_clean}\n"
        needs_header = not os.path.exists(path)
        with open(path, "a") as fh:
            if needs_header:
                fh.write(_HEADER)
            fh.write(row)
    except Exception:
        pass
