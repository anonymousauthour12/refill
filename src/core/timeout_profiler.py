import csv
import os
from datetime import datetime

_COLS = ["event_type", "timestamp", "duration_ms", "threshold_ms", "column", "detail"]


def log_timeout(event_type: str, duration_ms: float, threshold_ms: float = 0, detail: str = ""):
    """Append one timeout event to {work_space}/timeout_profile.csv.

    Silently no-ops if work_space is not yet configured (safe to call at any point).
    duration_ms = 0 when the duration is not measurable at the call site.
    """
    try:
        from src.core.config import config
        if not config.work_space:
            return
        col = (f"{config.target_database_name}."
               f"{config.target_table_name}."
               f"{config.target_column_name}")
        path = os.path.join(config.work_space, "timeout_profile.csv")
        write_header = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if write_header:
                w.writerow(_COLS)
            w.writerow([
                event_type,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                round(duration_ms),
                round(threshold_ms),
                col,
                str(detail)[:300],
            ])
    except Exception:
        pass
