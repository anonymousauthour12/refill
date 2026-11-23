#!/usr/bin/env python3
"""c.py - discover derivation formulas for one column of a MySQL database.

Usage: python c.py --column <database>.<table>.<column> --llm <gpt5|sonnet55>

The program is generic: schema, keys, relationships and data are discovered at run time.
The LLM proposes formulas; every formula is executed against the database and measured
against the stored column values. Everything is traced to output/*.jsonl.
"""
import json
import math
import os
import random
import re
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

# --------------------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------------------
TIME_LIMIT = float(os.environ.get("C_TIME_LIMIT", 3600))   # wall clock seconds per column
SAFETY_MARGIN = min(150.0, TIME_LIMIT * 0.05)               # no new LLM round after limit - margin
HARD_MARGIN = min(20.0, TIME_LIMIT * 0.01)                  # watchdog fires at limit - margin
ACCEPT_MIN_CONF = 75.0          # minimal conformity (%) for a formula to be considered
SAMPLE_ROWS = 20000             # rows used for a first quick evaluation on very large tables
FULL_EVAL_THRESHOLD = 60000     # tables larger than this are screened on a sample first
MAX_ROUNDS = 8
MAX_FORMULAS_PER_ROUND = 6
MAX_REPAIRS = 3
LLM_CALL_TIMEOUT = 480.0
SCHEMA_BUDGET = 60000           # characters of schema description sent to the LLM
OUT_DIR = "output"

NUMERIC_TYPES = {"tinyint", "smallint", "mediumint", "int", "integer", "bigint", "decimal", "numeric",
                 "float", "double", "real", "bit", "year", "boolean", "bool"}
FLOAT_TYPES = {"float", "double", "real"}
TEMPORAL_TYPES = {"date", "datetime", "timestamp", "time"}
STRING_TYPES = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext", "enum", "set"}

START = time.monotonic()


def remaining():
    return TIME_LIMIT - (time.monotonic() - START)


def time_up(margin=0.0):
    return remaining() <= margin


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fmt_conf(x):
    if x >= 100:
        return "100"
    x = math.floor(x * 100) / 100.0
    s = ("%.2f" % x).rstrip("0").rstrip(".")
    return s if s else "0"


def qid(name):
    return "`" + str(name).replace("`", "``") + "`"


def clip(v, n=60):
    if v is None:
        return "NULL"
    if isinstance(v, (bytes, bytearray)):
        return "<binary %d bytes>" % len(v)
    s = str(v).replace("\n", "\\n").replace("\r", "")
    return s if len(s) <= n else s[:n] + "..."


def fmt_rows(cols, rows, maxrows=10, maxw=50, maxcols=40):
    cols = list(cols)[:maxcols]
    lines = [" | ".join(cols)]
    for r in rows[:maxrows]:
        lines.append(" | ".join(clip(v, maxw) for v in list(r)[:maxcols]))
    if len(rows) > maxrows:
        lines.append("... (%d more rows)" % (len(rows) - maxrows))
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# exceptions
# --------------------------------------------------------------------------------------
class Permanent(Exception):
    """A permanent failure: no retry, write an error file."""


class LLMFatal(Permanent):
    pass


class LLMGiveUp(Exception):
    """One LLM request could not be completed (after retries)."""


class QueryError(Exception):
    pass


class TimeUp(Exception):
    pass


# --------------------------------------------------------------------------------------
# output: trace, llm call log, outcome files
# --------------------------------------------------------------------------------------
class Out:
    def __init__(self, base):
        self.base = base
        self.lock = threading.RLock()
        os.makedirs(OUT_DIR, exist_ok=True)
        self.trace_path = os.path.join(OUT_DIR, base + "_trace.jsonl")
        self.llm_path = os.path.join(OUT_DIR, base + "_llm_calls.jsonl")
        for p in (self.trace_path, self.llm_path):
            open(p, "w").close()
        for fn in os.listdir(OUT_DIR):
            if fn == base + "_not_derived.txt" or fn == base + "_error.txt" or \
                    re.fullmatch(re.escape(base) + r"_formula_\d+\.sql", fn):
                try:
                    os.remove(os.path.join(OUT_DIR, fn))
                except OSError:
                    pass
        self.done = False

    def _append(self, path, obj):
        line = json.dumps(obj, default=str, ensure_ascii=False)
        with self.lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()

    def trace(self, step, **content):
        try:
            self._append(self.trace_path, {"ts": now_iso(), "elapsed_s": round(time.monotonic() - START, 2),
                                           "step": step, **content})
        except Exception:
            pass

    def llm_log(self, **content):
        try:
            self._append(self.llm_path, {"ts": now_iso(), **content})
        except Exception:
            pass

    def write_file(self, suffix, text):
        with open(os.path.join(OUT_DIR, self.base + suffix), "w", encoding="utf-8") as f:
            f.write(text)


# --------------------------------------------------------------------------------------
# SQL helpers (read-only guard, literal stripping, reference checks)
# --------------------------------------------------------------------------------------
_LIT_RE = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"")
_COMMENT_RE = re.compile(r"/\*.*?\*/|--[^\n]*|#[^\n]*", re.S)


def strip_literals(sql):
    s = _LIT_RE.sub("''", sql)
    s = _COMMENT_RE.sub(" ", s)
    return s.replace("`", "")


_FORBIDDEN_RE = re.compile(r"\b(INTO|SLEEP|BENCHMARK|GET_LOCK|RELEASE_LOCK|LOAD_FILE|LOCK\s+IN\s+SHARE|FOR\s+UPDATE)\b",
                           re.I)


def check_readonly(sql):
    """Raise QueryError unless sql is a single read-only SELECT statement."""
    clean = strip_literals(sql).strip()
    while clean.endswith(";"):
        clean = clean[:-1].rstrip()
    if ";" in clean:
        raise QueryError("only a single statement is allowed")
    head = clean.lstrip("( \t\r\n").upper()
    if not (head.startswith("SELECT") or head.startswith("WITH")):
        raise QueryError("only SELECT statements are allowed")
    m = _FORBIDDEN_RE.search(clean)
    if m:
        raise QueryError("forbidden construct in query: " + m.group(1))


_ALIAS_KW = {"WHERE", "ON", "LEFT", "RIGHT", "INNER", "OUTER", "CROSS", "JOIN", "GROUP", "ORDER", "LIMIT",
             "USING", "SET", "HAVING", "UNION", "NATURAL", "STRAIGHT_JOIN", "FULL", "AND", "OR", "AS",
             "FOR", "WINDOW", "SELECT", "FROM", "INTERSECT", "EXCEPT", "USE", "FORCE", "IGNORE", "PARTITION"}
_FROM_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w$]*(?:\s*\.\s*[A-Za-z_][\w$]*)?)"
                      r"(?:\s+(?:AS\s+)?([A-Za-z_][\w$]*))?", re.I)


def alias_map(sql_clean, target_db, target_table):
    """alias(lower) -> (db or None, table) for tables found after FROM / JOIN."""
    amap = {"t": (target_db.lower(), target_table.lower())}
    for m in _FROM_RE.finditer(sql_clean):
        parts = [p.strip() for p in m.group(1).split(".")]
        if len(parts) == 2:
            db, tb = parts[0].lower(), parts[1].lower()
        else:
            db, tb = None, parts[0].lower()
        alias = m.group(2)
        if alias and alias.upper() in _ALIAS_KW:
            alias = None
        amap[(alias or parts[-1]).lower()] = (db, tb)
    return amap


def is_target_table(entry, target_db, target_table):
    db, tb = entry
    return tb == target_table.lower() and (db is None or db == target_db.lower())


def check_formula_static(expr, joins, target_db, target_table, target_col):
    """Return an error message if the formula is not acceptable, else None."""
    if not expr or not expr.strip():
        return "empty expression"
    full = (joins or "") + " " + expr
    clean = strip_literals(full)
    if ";" in clean:
        return "semicolons are not allowed"
    try:
        check_readonly("SELECT " + full)
    except QueryError as e:
        return str(e)
    amap = alias_map(clean, target_db, target_table)
    col = target_col.lower()
    for m in re.finditer(r"(?<![\w$.])([A-Za-z_][\w$]*)\s*\.\s*([A-Za-z_][\w$]*|\*)", clean):
        a, c = m.group(1).lower(), m.group(2).lower()
        if a in amap and is_target_table(amap[a], target_db, target_table) and (c == col or c == "*"):
            return ("the formula reads the stored value of the target column (%s.%s); a formula must be computed "
                    "from other columns only" % (m.group(1), m.group(2)))
    for m in re.finditer(r"(?<![\w$.])([A-Za-z_][\w$]*)\s*\.\s*([A-Za-z_][\w$]*)\s*\.\s*([A-Za-z_][\w$]*)", clean):
        if m.group(1).lower() == target_db.lower() and m.group(2).lower() == target_table.lower() \
                and m.group(3).lower() == col:
            return "the formula reads the stored value of the target column"
    if re.search(r"(?<![\w$.])" + re.escape(col) + r"(?![\w$.(])", clean, re.I):
        return ("the identifier '%s' (the target column name) appears unqualified; qualify every column with a table "
                "alias, never read the target column, and do not use that word as an alias" % target_col)
    refs = [m for m in re.finditer(r"(?<![\w$.])([A-Za-z_][\w$]*)\s*\.\s*([A-Za-z_][\w$]*)", clean)
            if m.group(1).lower() in amap]
    if not refs:
        return "the formula does not reference any column (constant formulas are not derivations)"
    return None


def build_formula_sql(expr, joins, db, table):
    src = "%s.%s" % (qid(db), qid(table))
    j = ("\n" + joins.strip()) if joins and joins.strip() else ""
    return "SELECT %s AS derived\nFROM %s AS t%s" % (expr.strip(), src, j)


def target_kind(data_type):
    dt = (data_type or "").lower()
    if dt in NUMERIC_TYPES:
        return "numeric"
    if dt in TEMPORAL_TYPES:
        return "temporal"
    if dt in STRING_TYPES:
        return "string"
    return "binary"


def compare_sql(kind, data_type, scale, tv, dv):
    """SQL boolean (may be NULL) telling whether derived value dv conforms to stored value tv."""
    dt = (data_type or "").lower()
    if kind == "numeric":
        if dt in FLOAT_TYPES:
            return "ABS(%s - %s) <= GREATEST(ABS(%s) * 0.000001, 0.000000001)" % (dv, tv, tv)
        if dt in ("decimal", "numeric") and scale is not None and scale > 0:
            tol = "%.*f" % (scale + 1, 0.5 * 10 ** (-scale))
            return "ABS(%s - %s) <= %s" % (dv, tv, tol)
        return "ABS(%s - %s) <= 0.000000001" % (dv, tv)
    if kind == "temporal":
        return "(%s) = (%s)" % (dv, tv)
    if kind == "string":
        return "BINARY CAST(%s AS CHAR) = BINARY CAST(%s AS CHAR)" % (dv, tv)
    return "CAST(%s AS BINARY) = CAST(%s AS BINARY)" % (dv, tv)


# --------------------------------------------------------------------------------------
# database access
# --------------------------------------------------------------------------------------
class DB:
    PERMANENT_CODES = {1045, 1044, 1130, 1251, 1698, 1049}
    LOST_CODES = {2006, 2013, 2055, 2003, 2002, 2005, 2026}

    def __init__(self, cfg, out):
        import pymysql
        self.pymysql = pymysql
        self.cfg = cfg
        self.out = out
        self.conn = None
        self.timeout_ms = None
        self.timeout_style = None
        self.nq = 0

    def connect(self, attempts=4):
        pm = self.pymysql
        last = None
        for i in range(attempts):
            if time_up(10):
                raise TimeUp()
            try:
                kw = dict(user=self.cfg["user"], password=self.cfg.get("password", ""), charset="utf8mb4",
                          connect_timeout=15, read_timeout=1200, write_timeout=120, autocommit=True)
                if self.cfg.get("unix_socket"):
                    kw["unix_socket"] = self.cfg["unix_socket"]
                else:
                    kw["host"] = self.cfg["host"]
                    kw["port"] = int(self.cfg.get("port", 3306))
                self.conn = pm.connect(**kw)
                self.timeout_ms = None
                self.timeout_style = None
                self.out.trace("db_connect", ok=True, attempt=i + 1)
                try:
                    cur = self.conn.cursor()
                    cur.execute("SET SESSION TRANSACTION READ ONLY")
                    cur.close()
                except Exception:
                    pass
                return
            except pm.err.OperationalError as e:
                code = e.args[0] if e.args else None
                last = e
                self.out.trace("db_connect", ok=False, attempt=i + 1, error=str(e), code=code)
                if code in self.PERMANENT_CODES:
                    raise Permanent("database connection refused (permanent): %s" % e)
            except Exception as e:  # network errors, bad config
                last = e
                self.out.trace("db_connect", ok=False, attempt=i + 1, error="%s: %s" % (type(e).__name__, e))
                if isinstance(e, (KeyError, TypeError, ValueError)):
                    raise Permanent("invalid database configuration: %r" % e)
            if i < attempts - 1:
                time.sleep(min(2 * 2 ** i, 20))
        raise Permanent("cannot connect to the database after %d attempts: %s" % (attempts, last))

    def _set_timeout(self, seconds):
        ms = int(max(1, seconds) * 1000)
        if self.timeout_ms == ms or self.timeout_style == "none":
            return
        cur = self.conn.cursor()
        try:
            if self.timeout_style in (None, "mysql"):
                try:
                    cur.execute("SET SESSION MAX_EXECUTION_TIME = %d" % ms)
                    self.timeout_style = "mysql"
                    self.timeout_ms = ms
                    return
                except Exception:
                    self.timeout_style = "maria"
            if self.timeout_style == "maria":
                try:
                    cur.execute("SET SESSION max_statement_time = %d" % max(1, int(seconds)))
                    self.timeout_ms = ms
                    return
                except Exception:
                    self.timeout_style = "none"
        finally:
            cur.close()

    def query(self, sql, purpose="", max_rows=None, timeout=None, args=None):
        """Run a read-only query. Returns (columns, rows). Raises QueryError; Permanent only if the
        connection cannot be re-established."""
        t0 = time.monotonic()
        err = None
        cols, rows = [], []
        shown = sql
        try:
            check_readonly(sql)
        except QueryError as e:
            self.out.trace("db_query", purpose=purpose, sql=sql, rows=0, seconds=0.0, error=str(e))
            raise
        tmo = min(timeout if timeout else 600.0, max(5.0, remaining() - 20))
        for attempt in range(3):
            try:
                if self.conn is None:
                    self.connect()
                self._set_timeout(tmo)
                cur = self.conn.cursor()
                try:
                    if args is not None:
                        shown = cur.mogrify(sql, args)
                    cur.execute(sql, args)
                    cols = [d[0] for d in (cur.description or [])]
                    rows = list(cur.fetchmany(max_rows)) if max_rows else list(cur.fetchall())
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                err = None
                break
            except self.pymysql.err.Error as e:
                code = e.args[0] if e.args else None
                if code in self.LOST_CODES or isinstance(e, (self.pymysql.err.InterfaceError,)):
                    err = "connection lost: %s" % e
                    self.conn = None
                    time.sleep(1 + attempt * 2)
                    continue
                err = "%s: %s" % (type(e).__name__, e)
                break
            except (OSError, TimeoutError) as e:
                err = "connection error: %s: %s" % (type(e).__name__, e)
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
                time.sleep(1 + attempt * 2)
                continue
        self.nq += 1
        self.out.trace("db_query", purpose=purpose, sql=shown, rows=len(rows),
                       seconds=round(time.monotonic() - t0, 3), error=err)
        if err:
            raise QueryError(err)
        return cols, rows


# --------------------------------------------------------------------------------------
# schema discovery
# --------------------------------------------------------------------------------------
class Schema:
    def __init__(self):
        self.tables = {}      # table -> {"type","rows","comment","cols":[...]}
        self.fks = []         # (table, col, ref_table, ref_col)
        self.inferred = []    # (table, col, ref_table, ref_col)


def load_schema(db, dbname, out):
    sch = Schema()
    _, rows = db.query(
        "SELECT table_name, table_type, table_rows, table_comment FROM information_schema.tables "
        "WHERE table_schema = %s", purpose="schema: tables", args=(dbname,))
    for r in rows:
        sch.tables[r[0]] = {"type": r[1], "rows": r[2], "comment": r[3] or "", "cols": []}
    _, rows = db.query(
        "SELECT table_name, column_name, data_type, column_type, numeric_scale, column_key, extra, "
        "generation_expression, column_comment, is_nullable FROM information_schema.columns "
        "WHERE table_schema = %s ORDER BY table_name, ordinal_position", purpose="schema: columns", args=(dbname,))
    for r in rows:
        if r[0] not in sch.tables:
            sch.tables[r[0]] = {"type": "?", "rows": None, "comment": "", "cols": []}
        sch.tables[r[0]]["cols"].append({
            "name": r[1], "data_type": (r[2] or "").lower(), "column_type": r[3], "scale": r[4], "key": r[5] or "",
            "extra": r[6] or "", "gen": r[7] or "", "comment": r[8] or "", "nullable": r[9] == "YES"})
    try:
        _, rows = db.query(
            "SELECT table_name, column_name, referenced_table_schema, referenced_table_name, referenced_column_name "
            "FROM information_schema.key_column_usage WHERE table_schema = %s AND referenced_table_name IS NOT NULL",
            purpose="schema: foreign keys", args=(dbname,))
        for r in rows:
            sch.fks.append((r[0], r[1], r[3] if r[2] == dbname else "%s.%s" % (r[2], r[3]), r[4]))
    except QueryError:
        pass
    # inferred relationships: same column name where one side is a key; column named <x>_<pk of other table>
    by_name = {}
    for t, info in sch.tables.items():
        for c in info["cols"]:
            by_name.setdefault(c["name"].lower(), []).append((t, c))
    ntab = max(1, len(sch.tables))
    fkset = set(sch.fks)
    inferred = set()
    for name, lst in by_name.items():
        if len(lst) < 2 or len(lst) > max(4, 0.3 * ntab):
            continue
        keyed = [(t, c) for t, c in lst if c["key"] in ("PRI", "UNI")]
        for t, c in keyed:
            for t2, c2 in lst:
                if t2 != t and (t2, c2["name"], t, c["name"]) not in fkset:
                    inferred.add((t2, c2["name"], t, c["name"]))
    single_pk = {}
    for t, info in sch.tables.items():
        pks = [c["name"] for c in info["cols"] if c["key"] == "PRI"]
        if len(pks) == 1:
            single_pk[t] = pks[0]
    for t, info in sch.tables.items():
        for c in info["cols"]:
            for t2, pk in single_pk.items():
                if t2 == t or c["name"].lower() == pk.lower():
                    continue
                if len(pk) >= 3 and c["name"].lower().endswith("_" + pk.lower()):
                    if (t, c["name"], t2, pk) not in fkset:
                        inferred.add((t, c["name"], t2, pk))
    sch.inferred = sorted(inferred)[:300]
    return sch


# --------------------------------------------------------------------------------------
# LLM access
# --------------------------------------------------------------------------------------
def extract_json(text):
    if not text:
        return None
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


class LLM:
    def __init__(self, cfg, out):
        self.cfg = cfg
        self.out = out
        self.client = None
        self.ncalls = 0
        self.nsuccess = 0
        self.conn_fail_streak = 0
        self.provider = cfg.get("provider", "")
        self.model = cfg.get("model")
        self._build()

    def _build(self):
        import httpx
        cfg = self.cfg
        kw = {}
        try:
            if cfg.get("unix_socket"):
                kw["http_client"] = httpx.Client(transport=httpx.HTTPTransport(uds=cfg["unix_socket"]),
                                                 trust_env=False, timeout=LLM_CALL_TIMEOUT)
            if self.provider == "azure_openai":
                import openai
                self.client = openai.AzureOpenAI(azure_endpoint=cfg["azure_endpoint"], api_key=cfg["api_key"],
                                                 api_version=cfg["api_version"], max_retries=0, **kw)
                self.kind = "openai"
            elif self.provider == "anthropic_foundry":
                import anthropic
                self.client = anthropic.AnthropicFoundry(api_key=cfg["api_key"], base_url=cfg["base_url"],
                                                         max_retries=0, **kw)
                self.kind = "anthropic"
            else:
                raise Permanent("unknown LLM provider %r" % self.provider)
        except Permanent:
            raise
        except Exception as e:
            raise Permanent("cannot create the LLM client: %s: %s" % (type(e).__name__, e))

    def _raw(self, prompt, timeout):
        if self.kind == "openai":
            r = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}],
                                                    timeout=timeout)
            text = r.choices[0].message.content if r.choices else None
            u = getattr(r, "usage", None)
            return text or "", getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None)
        r = self.client.messages.create(model=self.model, max_tokens=16000,
                                        messages=[{"role": "user", "content": prompt}], timeout=timeout)
        text = "".join(getattr(b, "text", "") or "" for b in (r.content or []) if getattr(b, "type", "") == "text")
        u = getattr(r, "usage", None)
        return text, getattr(u, "input_tokens", None), getattr(u, "output_tokens", None)

    @staticmethod
    def _classify(e):
        """-> ('fatal'|'giveup'|'ratelimit'|'conn'|'server', retry_after)"""
        status = getattr(e, "status_code", None)
        ra = None
        try:
            ra = float(e.response.headers.get("retry-after"))
        except Exception:
            pass
        if status in (401, 403, 404):
            return "fatal", ra
        if status in (400, 413, 422):
            return "giveup", ra
        if status == 429:
            return "ratelimit", ra
        if (status is not None and status >= 500) or status in (408, 409):
            return "server", ra
        return "conn", ra

    def complete(self, prompt, purpose):
        """Return the text of an answer. Retries temporary failures; raises LLMFatal / LLMGiveUp / TimeUp."""
        attempt = 0
        empty = 0
        while True:
            if time_up(30):
                raise TimeUp()
            attempt += 1
            t0 = time.monotonic()
            self.ncalls += 1
            err = None
            text, tin, tout = "", None, None
            kind = None
            ra = None
            try:
                text, tin, tout = self._raw(prompt, min(LLM_CALL_TIMEOUT, max(10.0, remaining() - 20)))
            except Exception as e:
                err = "%s: %s" % (type(e).__name__, str(e)[:500])
                kind, ra = self._classify(e)
            secs = round(time.monotonic() - t0, 2)
            self.out.llm_log(model=self.model, purpose=purpose, input_tokens=tin, output_tokens=tout,
                             seconds=secs, error=err)
            self.out.trace("llm_call", purpose=purpose, model=self.model, input_tokens=tin, output_tokens=tout,
                           seconds=secs, attempt=attempt, prompt=prompt, response=text, error=err)
            if err is None:
                self.conn_fail_streak = 0
                if text and text.strip():
                    self.nsuccess += 1
                    return text
                empty += 1
                kind = "empty"
                err = "empty answer"
            if kind == "fatal":
                raise LLMFatal("LLM request refused (permanent): %s" % err)
            if kind == "giveup":
                raise LLMGiveUp(err)
            if kind == "conn":
                self.conn_fail_streak += 1
                limit = 15 if self.nsuccess else 6
                if self.conn_fail_streak >= limit:
                    if self.nsuccess == 0:
                        raise LLMFatal("LLM endpoint unreachable after %d attempts: %s" % (limit, err))
                    raise LLMGiveUp("LLM endpoint unreachable: %s" % err)
            if kind == "empty" and empty >= 5:
                raise LLMGiveUp("LLM returned empty answers %d times" % empty)
            if kind in ("ratelimit", "server") and attempt >= 40:
                raise LLMGiveUp(err)
            wait = min(60.0, 2.0 * 2 ** min(attempt - 1, 6)) * random.uniform(0.8, 1.2)
            if ra:
                wait = min(max(wait, ra), 120.0)
            wait = min(wait, max(0.0, remaining() - 30))
            self.out.trace("llm_retry", purpose=purpose, kind=kind, error=err, wait_s=round(wait, 1))
            time.sleep(wait)

    def ask_json(self, prompt, purpose):
        bad = 0
        while True:
            text = self.complete(prompt, purpose)
            obj = extract_json(text)
            if obj is not None:
                return obj
            bad += 1
            self.out.trace("llm_parse_failure", purpose=purpose, attempt=bad,
                           reason="answer does not contain a JSON object")
            if bad >= 4:
                raise LLMGiveUp("LLM answer could not be parsed as JSON %d times" % bad)
            time.sleep(min(2 * bad, 10))


# --------------------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------------------
FORMULA_SPEC = """FORMULA FORMAT
A formula is described by two strings, "joins" and "expr", that are assembled into
    SELECT <expr> AS derived
    FROM `{db}`.`{table}` AS t
    <joins>
The alias `t` is the row of the target table; the query must return exactly one value per row of the table.
Rules:
- "expr" is a single MySQL scalar expression. Always qualify every column with a table alias, and always write
  tables as `database`.`table`.
- "joins" is optional (use "" if not needed). Only LEFT JOINs of tables that match at most ONE row per row of t
  (many-to-one lookups, one-to-one) are allowed; a join that multiplies or drops rows makes the formula invalid.
  Use explicit JOIN ... ON syntax, never comma joins.
- To use data of other tables that has many rows per target row (aggregation, e.g. SUM/COUNT/MAX/GROUP_CONCAT), use a
  correlated scalar subquery inside "expr" that refers to `t`, e.g.
      (SELECT SUM(li.qty * li.unit_price) FROM `acme`.`invoice_lines` AS li WHERE li.invoice_no = t.invoice_no)
  Subqueries may also read other rows of the target table through another alias (but never its target column).
  Use COALESCE when a missing related row should give 0 (or another value) instead of NULL, if the data supports it.
- The formula MUST NOT read the stored value of the target column in any way (not from t, not via another alias of the
  target table, not in a subquery). It must be computed from other columns.
- The formula must be the real, general rule that produces the value for every row - not an approximation, not a
  statistical fit, and no hard-coded per-row or per-id values (no CASE listing individual keys or values observed in
  the data). Constants that are part of a genuine rule (a fixed rate, a unit conversion, a rounding precision) are fine.
- Reproduce the stored value exactly: apply the rounding / casting / formatting the stored value shows (e.g. ROUND(x, 2),
  CONCAT, DATE_FORMAT, DATEDIFF, TIMESTAMPDIFF, CASE for category rules, etc.).
- Comparison is done per row between your value and the stored value: numbers must be equal up to the precision of the
  column (half a unit of its last decimal), strings must be identical (case-sensitive), dates equal.
- Plain MySQL only; no variables, no CTEs inside "expr", no statements other than SELECT."""

OUTPUT_NOTE = "Answer with ONE JSON object only (no prose before or after it, no markdown fences)."


class Ctx:
    """Everything known about the target column; rendered into prompts."""

    def __init__(self):
        self.db = self.table = self.col = None
        self.info = None
        self.kind = None
        self.n_rows = 0
        self.n_nonnull = 0
        self.n_distinct = None
        self.top_share = 0.0
        self.profile_text = ""
        self.schema_text = ""
        self.rel_text = ""
        self.samples_text = ""
        self.hints_text = ""
        self.semantics = ""
        self.semantics_obj = {}
        self.explore = []          # (sql, text)
        self.probe_text = ""


def render_schema(sch, db, table, budget=SCHEMA_BUDGET):
    """Prioritised description of all tables: target, FK neighbours, name-linked tables, rest."""
    prio = {table: 0}
    for a, _, b, _ in sch.fks:
        if a == table:
            prio.setdefault(b, 1)
        if b == table:
            prio.setdefault(a, 1)
    for a, _, b, _ in sch.inferred:
        if a == table:
            prio.setdefault(b, 2)
        if b == table:
            prio.setdefault(a, 2)
    first = [t for t, p in prio.items() if p in (1, 2)]
    for a, _, b, _ in sch.fks + sch.inferred:
        if a in first:
            prio.setdefault(b, 3)
        if b in first:
            prio.setdefault(a, 3)
    order = sorted(sch.tables, key=lambda t: (prio.get(t, 9), t.lower()))
    lines, used, omitted = [], 0, []
    for t in order:
        info = sch.tables[t]
        head = "TABLE %s.%s%s  (~%s rows)" % (db, t, " [VIEW]" if "VIEW" in (info["type"] or "") else "",
                                              info["rows"] if info["rows"] is not None else "?")
        if info["comment"]:
            head += "  -- " + info["comment"][:150]
        cl = []
        for c in info["cols"]:
            s = "  %s %s" % (c["name"], c["column_type"] if len(str(c["column_type"])) < 60 else c["data_type"])
            if c["key"]:
                s += " [%s]" % {"PRI": "PK", "UNI": "UNIQUE", "MUL": "indexed"}.get(c["key"], c["key"])
            if c["gen"]:
                s += " [GENERATED AS %s]" % c["gen"]
            if c["comment"]:
                s += "  -- " + c["comment"][:120]
            cl.append(s)
        block = head + "\n" + "\n".join(cl)
        if used + len(block) > budget and prio.get(t, 9) > 1:
            omitted.append(t)
            continue
        lines.append(block)
        used += len(block)
    text = "\n".join(lines)
    if omitted:
        text += "\n(tables not shown in detail: %s)" % ", ".join(omitted[:200])
    return text


def render_relationships(sch):
    lines = []
    for a, b, c, d in sch.fks:
        lines.append("%s.%s -> %s.%s  (declared foreign key)" % (a, b, c, d))
    for a, b, c, d in sch.inferred:
        lines.append("%s.%s ~ %s.%s  (same name / naming pattern, not declared)" % (a, b, c, d))
    if len(lines) > 400:
        lines = lines[:400] + ["..."]
    return "\n".join(lines) if lines else "(none found)"


def context_block(ctx):
    ti = ctx.info
    parts = []
    parts.append("TARGET COLUMN: `%s`.`%s`.`%s`  type=%s  nullable=%s%s" % (
        ctx.db, ctx.table, ctx.col, ti["column_type"], "yes" if ti["nullable"] else "no",
        ("  comment=" + ti["comment"]) if ti["comment"] else ""))
    parts.append("The target table has %d rows; %d of them have a non-NULL value in the target column." %
                 (ctx.n_rows, ctx.n_nonnull))
    if ctx.hints_text:
        parts.append("METADATA HINTS FROM THE DATABASE:\n" + ctx.hints_text)
    parts.append("TARGET COLUMN PROFILE:\n" + ctx.profile_text)
    blocks = ctx.samples_text.split("\n=====\n")
    parts.append("SAMPLE ROWS OF THE TARGET TABLE:\n" + blocks[0])
    parts.append("DATABASE SCHEMA (database %s):\n%s" % (ctx.db, ctx.schema_text))
    parts.append("RELATIONSHIPS BETWEEN TABLES:\n" + ctx.rel_text)
    if len(blocks) > 1:
        parts.append("SAMPLE ROWS OF RELATED TABLES:\n" + "\n\n".join(blocks[1:]))
    return "\n\n".join(parts)


def semantics_prompt(ctx):
    return f"""You are an expert in relational databases and data engineering. You analyse one column of a MySQL
database in order to find out whether it is a *derived* column, i.e. whether its value can be computed by a formula from
other columns of the same database (possibly in other tables), and what its meaning is.

{context_block(ctx)}

TASK 1 - SEMANTICS. Explain what the target column means in the context of its table and the database: what real-world
quantity or attribute it holds, its unit/format, and how it relates to other columns. Then judge whether it looks
like a derived value (computed from other data: totals, counts, differences, durations, concatenations, lookups copied
from a parent table, flags/categories obtained by a rule, ...) or an original/base value that is entered, measured or
identified (keys, names, free text, timestamps of events, base prices, ...). Say which columns (as
`table.column`) could be the inputs of a derivation.

You may also ask for up to 4 read-only exploration queries (single SELECT statements, fully qualified table names)
whose results you would like to see before proposing formulas.

{OUTPUT_NOTE} Schema:
{{"semantics": "<what the column means>", "derivable": "yes" | "no" | "unclear", "reasoning": "<short>",
  "candidate_sources": ["table.column", ...], "explore_queries": ["SELECT ...", ...]}}"""


def history_block(attempts, max_detail=10):
    if not attempts:
        return "(no attempts yet)"
    lines = []
    for a in attempts[:-max_detail]:
        lines.append("- [#%d] expr=%s | joins=%s -> %s" % (a["id"], a["expr"][:200], (a["joins"] or "")[:100],
                                                          a["summary"]))
    for a in attempts[-max_detail:]:
        s = "- [#%d] %s\n    joins: %s\n    expr: %s\n    result: %s" % (
            a["id"], a["description"][:150], a["joins"] or "(none)", a["expr"], a["summary"])
        if a.get("mismatch_text"):
            s += "\n    examples of rows where it does NOT match:\n" + \
                 "\n".join("      " + l for l in a["mismatch_text"].split("\n"))
        lines.append(s)
    return "\n".join(lines)


def proposal_prompt(ctx, accepted, attempts, round_no):
    acc = "\n".join("- [#%d] conformity %s%%: %s | %s" % (c["id"], fmt_conf(c["conf"]), c["description"][:150],
                                                         c["expr"][:300]) for c in accepted) or "(none yet)"
    expl = "\n\n".join("QUERY: %s\nRESULT:\n%s" % (q, r) for q, r in ctx.explore[-8:]) or "(none)"
    probe = ctx.probe_text or "(no result)"
    if accepted:
        task = ("Formulas already found and verified are listed under ALREADY ACCEPTED. Look for ADDITIONAL formulas "
                "that are genuinely DIFFERENT derivations of the same column (different source columns, different "
                "tables, a different way of computing it) - not rewrites, reorderings, or equivalent variants of "
                "an accepted formula. If there are none, return an empty list and set \"complete\" to true.")
    elif round_no == 1:
        task = ("Propose formulas (up to %d, the most plausible first, each a different derivation) that compute the "
                "target column. If after careful analysis you believe the column is NOT derived, return an empty "
                "list and set \"complete\" to true." % MAX_FORMULAS_PER_ROUND)
    else:
        task = ("None of the attempts so far was accepted. Study the results and mismatch examples, and propose "
                "improved or new formulas (up to %d). Consider other tables, other source columns, rounding, NULL "
                "handling, conditions for special cases. If you are convinced that no formula exists (the column "
                "is an original, entered value), return an empty list and set \"complete\" to true."
                % MAX_FORMULAS_PER_ROUND)
    return f"""You are an expert in relational databases and SQL (MySQL). You must discover formulas that derive the
values of one target column from other columns of the same database.

{context_block(ctx)}

SEMANTICS OF THE TARGET COLUMN (from an earlier analysis):
{ctx.semantics}

AUTOMATIC DATA PROBE (simple same-table patterns tested on a sample of rows):
{probe}

EXPLORATION RESULTS SO FAR:
{expl}

ALREADY ACCEPTED FORMULAS:
{acc}

ATTEMPTS SO FAR (formulas that were tried, with measured results):
{history_block(attempts)}

{FORMULA_SPEC.format(db=ctx.db, table=ctx.table)}

A derived column can have several different formulas (e.g. computed from different columns or from different
tables). The "conformity" of a formula is the percentage of non-NULL stored values that equal the formula value.

TASK (round {round_no}): {task}
You may also request up to 4 read-only exploration queries (single SELECT statements) to inspect data; their results are
shown to you in the next round.

{OUTPUT_NOTE} Schema:
{{"analysis": "<short reasoning>",
  "formulas": [{{"description": "<the rule in words>", "joins": "<LEFT JOIN ... or empty>", "expr": "<scalar SQL expression>"}}],
  "explore_queries": ["SELECT ..."],
  "complete": true | false}}"""


def repair_prompt(ctx, cand, problem):
    return f"""You are an expert in MySQL. A candidate formula for the column `{ctx.db}`.`{ctx.table}`.`{ctx.col}` failed.

TARGET COLUMN: type {ctx.info['column_type']}. Semantics: {ctx.semantics[:600]}

CANDIDATE
description: {cand['description']}
joins: {cand['joins'] or '(none)'}
expr: {cand['expr']}
Complete query that was run:
{cand['sql']}

PROBLEM
{problem}

DATABASE SCHEMA (database {ctx.db}):
{ctx.schema_text}

{FORMULA_SPEC.format(db=ctx.db, table=ctx.table)}

Fix the formula so that it runs and keeps the same intended rule (or, if the rule itself cannot work, give the best
corrected derivation). {OUTPUT_NOTE} Schema:
{{"description": "<rule in words>", "joins": "<joins or empty>", "expr": "<scalar SQL expression>"}}"""


def judge_prompt(ctx, cand, baseline):
    return f"""You are a careful data engineer. A candidate formula was found for the column `{ctx.db}`.`{ctx.table}`.`{ctx.col}`.
It does not match every stored value or the column has very few distinct values, so decide whether it is a GENUINE
derivation rule (the stored values are really computed that way, mismatches being explainable by data-quality noise,
edge cases or historic data) or a COINCIDENCE / overfit / approximation.

Semantics of the column: {ctx.semantics[:800]}
Type: {ctx.info['column_type']}
Candidate rule: {cand['description']}
joins: {cand['joins'] or '(none)'}
expr: {cand['expr']}
Conformity: {fmt_conf(cand['conf'])}% of {cand['n_nonnull']} non-NULL values ({cand['n_nonnull'] - cand['n_match']} do not match,
of which {cand.get('n_null', 0)} because the formula gives NULL).
Number of distinct stored values: {ctx.n_distinct}. Share of the most frequent stored value (a trivial baseline): {baseline:.1f}%.
Examples of non-matching rows:
{cand.get('mismatch_text') or '(none)'}

Accept only if the rule is semantically meaningful and plausibly the actual way the value is produced.
Reject if it is a coincidence (e.g. it only reproduces the most frequent value or a handful of values), an
approximation, or the mismatches show that the rule is wrong for a systematic sub-population.
{OUTPUT_NOTE} Schema: {{"verdict": "accept" | "reject", "reason": "<short>"}}"""


def dedup_prompt(ctx, new, accepted):
    lst = "\n".join("[#%d] conformity %s%%\n  description: %s\n  joins: %s\n  expr: %s" % (
        c["id"], fmt_conf(c["conf"]), c["description"], c["joins"] or "(none)", c["expr"]) for c in accepted)
    return f"""Two formulas for the same column are *rewrites* of each other if they use the same source columns/tables
and the same logic, differing only in syntax, ordering of terms, aliases, equivalent functions, redundant casts or
rounding. They are *different derivations* if they compute the value from different source columns or tables, or by
a different logic (even if on the current data they give the same values).

NEW FORMULA [#{new['id']}]
  description: {new['description']}
  joins: {new['joins'] or '(none)'}
  expr: {new['expr']}

ALREADY ACCEPTED FORMULAS
{lst}

Is the new formula a rewrite of one of the accepted formulas? {OUTPUT_NOTE} Schema:
{{"duplicate_of": <id number of the accepted formula it rewrites, or null>, "reason": "<short>"}}"""


# --------------------------------------------------------------------------------------
# main workflow
# --------------------------------------------------------------------------------------
class Run:
    def __init__(self, db_name, table, col, out, db, llm):
        self.dbname, self.table, self.col = db_name, table, col
        self.out, self.db, self.llm = out, db, llm
        self.ctx = Ctx()
        self.sch = None
        self.accepted = []
        self.attempts = []
        self.cands = []
        self.next_id = 1
        self.fatal = None
        self.llm_rounds_ok = 0
        self.llm_evaluated = 0       # LLM formulas executed successfully against the data
        self.llm_declared_none = False
        self.all_null = False
        self.best_conf = 0.0

    # ---------------- setup -----------------
    def setup(self):
        out, db = self.out, self.db
        sch = self.sch = load_schema(db, self.dbname, out)
        if not sch.tables:
            raise Permanent("database '%s' does not exist or has no tables visible to this account" % self.dbname)
        tname = next((t for t in sch.tables if t == self.table), None) or \
            next((t for t in sch.tables if t.lower() == self.table.lower()), None)
        if tname is None:
            raise Permanent("table '%s' does not exist in database '%s'" % (self.table, self.dbname))
        self.table = tname
        cinfo = next((c for c in sch.tables[tname]["cols"] if c["name"] == self.col), None) or \
            next((c for c in sch.tables[tname]["cols"] if c["name"].lower() == self.col.lower()), None)
        if cinfo is None:
            raise Permanent("column '%s' does not exist in table '%s.%s'" % (self.col, self.dbname, tname))
        self.col = cinfo["name"]
        ctx = self.ctx
        ctx.db, ctx.table, ctx.col, ctx.info = self.dbname, self.table, self.col, cinfo
        ctx.kind = target_kind(cinfo["data_type"])
        full = "%s.%s" % (qid(self.dbname), qid(self.table))
        try:
            _, rows = db.query("SELECT COUNT(*), COUNT(%s) FROM %s" % (qid(self.col), full), purpose="row counts")
        except QueryError as e:
            raise Permanent("cannot read the target table: %s" % e)
        ctx.n_rows, ctx.n_nonnull = int(rows[0][0]), int(rows[0][1])
        if ctx.n_rows == 0:
            raise Permanent("the target table '%s.%s' is empty" % (self.dbname, self.table))
        out.trace("target_resolved", database=self.dbname, table=self.table, column=self.col,
                  column_type=cinfo["column_type"], kind=ctx.kind, rows=ctx.n_rows, non_null=ctx.n_nonnull)
        if ctx.n_nonnull == 0:
            self.all_null = True
            return
        hints = []
        if cinfo["gen"]:
            hints.append("The database declares this column as a GENERATED column: %s  (expression: %s)" %
                         (cinfo["extra"], cinfo["gen"]))
        if cinfo["comment"]:
            hints.append("Column comment: " + cinfo["comment"])
        if sch.tables[self.table]["comment"]:
            hints.append("Table comment: " + sch.tables[self.table]["comment"])
        try:
            _, rows = db.query(
                "SELECT trigger_name, action_timing, event_manipulation, action_statement FROM "
                "information_schema.triggers WHERE event_object_schema = %s AND event_object_table = %s",
                purpose="triggers of the target table", args=(self.dbname, self.table))
            for r in rows[:6]:
                hints.append("Trigger %s (%s %s): %s" % (r[0], r[1], r[2], str(r[3])[:1500]))
        except QueryError:
            pass
        ctx.hints_text = "\n".join(hints)
        ctx.schema_text = render_schema(sch, self.dbname, self.table)
        ctx.rel_text = render_relationships(sch)
        self.profile()
        self.samples()

    def profile(self):
        ctx, db = self.ctx, self.db
        c = qid(self.col)
        full = "%s.%s" % (qid(self.dbname), qid(self.table))
        lines = []
        longish = ctx.info["data_type"] in ("text", "mediumtext", "longtext", "blob", "mediumblob", "longblob", "json")
        try:
            if longish:
                _, r = db.query("SELECT COUNT(DISTINCT LEFT(CAST(%s AS CHAR), 200)), MIN(LENGTH(%s)), MAX(LENGTH(%s)) FROM %s"
                                % (c, c, c, full), purpose="profile: distinct/length")
                ctx.n_distinct = int(r[0][0])
                lines.append("distinct values: %s; min length: %s; max length: %s" % (r[0][0], r[0][1], r[0][2]))
            else:
                _, r = db.query("SELECT COUNT(DISTINCT %s), MIN(%s), MAX(%s) FROM %s" % (c, c, c, full),
                                purpose="profile: distinct/min/max")
                ctx.n_distinct = int(r[0][0])
                lines.append("distinct values: %s; min: %s; max: %s" % (r[0][0], clip(r[0][1]), clip(r[0][2])))
        except QueryError as e:
            lines.append("(profile failed: %s)" % str(e)[:100])
        lines.append("NULL values: %d of %d rows" % (ctx.n_rows - ctx.n_nonnull, ctx.n_rows))
        try:
            expr = "LEFT(CAST(%s AS CHAR), 100)" % c if longish else c
            _, r = db.query("SELECT %s AS v, COUNT(*) AS n FROM %s WHERE %s IS NOT NULL GROUP BY v ORDER BY n DESC, v "
                            "LIMIT 8" % (expr, full, c), purpose="profile: most frequent values")
            lines.append("most frequent values (value: count): " + "; ".join("%s: %s" % (clip(a), b) for a, b in r))
            ctx.top_share = 100.0 * float(r[0][1]) / max(1, ctx.n_nonnull) if r else 0.0
        except QueryError:
            ctx.top_share = 0.0
        ctx.profile_text = "\n".join(lines)

    def samples(self):
        ctx, db, sch = self.ctx, self.db, self.sch
        full = "%s.%s" % (qid(self.dbname), qid(self.table))
        blocks = []
        try:
            cols, rows = db.query("SELECT * FROM %s WHERE %s IS NOT NULL LIMIT 8" % (full, qid(self.col)),
                                  purpose="sample rows of target table", max_rows=8)
            blocks.append(fmt_rows(cols, rows, 8, 40, 60))
        except QueryError as e:
            blocks.append("(sample failed: %s)" % str(e)[:100])
        rel = []
        for a, _, b, _ in sch.fks + sch.inferred:
            if a == self.table and b not in rel and b != self.table:
                rel.append(b)
            elif b == self.table and a not in rel and a != self.table:
                rel.append(a)
        for t in rel[:8]:
            if t not in sch.tables:
                continue
            try:
                cols, rows = db.query("SELECT * FROM %s.%s LIMIT 4" % (qid(self.dbname), qid(t)),
                                      purpose="sample rows of related table", max_rows=4)
                blocks.append("TABLE %s:\n%s" % (t, fmt_rows(cols, rows, 4, 30, 30)))
            except QueryError:
                pass
        ctx.samples_text = "\n=====\n".join(blocks)

    # ---------------- evaluation -----------------
    def _src(self, sample):
        src = "%s.%s" % (qid(self.dbname), qid(self.table))
        if sample:
            src = "(SELECT * FROM %s LIMIT %d)" % (src, int(sample))
        return src

    def evaluate(self, expr, joins, sample=None, purpose="evaluate formula"):
        """Run the formula against the stored column. Returns dict with counts, raises QueryError."""
        ctx = self.ctx
        j = ("\n" + joins.strip()) if joins and joins.strip() else ""
        inner = "SELECT t.%s AS tv, (%s) AS dv FROM %s AS t%s" % (qid(self.col), expr.strip(), self._src(sample), j)
        cmp_ = compare_sql(ctx.kind, ctx.info["data_type"], ctx.info["scale"], "e.tv", "e.dv")
        sql = ("SELECT COUNT(*) AS n_rows, "
               "COALESCE(SUM(CASE WHEN e.tv IS NOT NULL THEN 1 ELSE 0 END), 0) AS n_nonnull, "
               "COALESCE(SUM(CASE WHEN e.tv IS NOT NULL AND e.dv IS NOT NULL AND (%s) THEN 1 ELSE 0 END), 0) AS n_match, "
               "COALESCE(SUM(CASE WHEN e.tv IS NOT NULL AND e.dv IS NULL THEN 1 ELSE 0 END), 0) AS n_null "
               "FROM (%s) AS e" % (cmp_, inner))
        _, rows = self.db.query(sql, purpose=purpose, timeout=min(600.0, max(30.0, remaining() - 90)))
        r = rows[0]
        return {"n_rows": int(r[0]), "n_nonnull": int(r[1]), "n_match": int(r[2]), "n_null": int(r[3]),
                "sample": sample}

    def mismatches(self, expr, joins, limit=8):
        ctx = self.ctx
        j = ("\n" + joins.strip()) if joins and joins.strip() else ""
        cmp_ = compare_sql(ctx.kind, ctx.info["data_type"], ctx.info["scale"], "e.`__tv`", "e.`__dv`")
        sql = ("SELECT * FROM (SELECT t.%s AS `__tv`, (%s) AS `__dv`, t.* FROM %s AS t%s) AS e "
               "WHERE e.`__tv` IS NOT NULL AND NOT COALESCE((%s), 0) LIMIT %d" %
               (qid(self.col), expr.strip(), self._src(None), j, cmp_, limit))
        try:
            cols, rows = self.db.query(sql, purpose="mismatch examples", max_rows=limit, timeout=120)
        except QueryError as e:
            return "(could not fetch mismatch examples: %s)" % str(e)[:150]
        if not rows:
            return ""
        cols = ["stored", "formula"] + list(cols[3:])
        rows = [list(r[:2]) + list(r[3:]) for r in rows]
        return fmt_rows(cols, rows, limit, 30, 14)

    def new_cand(self, source, description, joins, expr, rnd):
        cand = {"id": self.next_id, "source": source, "description": (description or "").strip() or "(no description)",
                "joins": (joins or "").strip(), "expr": (expr or "").strip(), "round": rnd, "status": "new",
                "conf": 0.0, "n_nonnull": 0, "n_match": 0, "n_null": 0, "summary": "", "repairs": 0,
                "mismatch_text": ""}
        self.next_id += 1
        cand["sql"] = build_formula_sql(cand["expr"], cand["joins"], self.dbname, self.table)
        self.cands.append(cand)
        self.out.trace("formula_proposed", id=cand["id"], source=source, round=rnd, description=cand["description"],
                       joins=cand["joins"], expr=cand["expr"], sql=cand["sql"])
        return cand

    def record_attempt(self, cand):
        self.attempts = [a for a in self.attempts if a["id"] != cand["id"]] + [cand]

    @staticmethod
    def _key(cand):
        return re.sub(r"\s+", " ", (cand["joins"] + " " + cand["expr"]).lower()).strip()

    def process_candidate(self, cand):
        """Static check, execution (with LLM repair of SQL errors), evaluation, decision."""
        ctx = self.ctx
        cand["key"] = self._key(cand)
        for o in self.cands:
            if o is not cand and o.get("key") == cand["key"] and o["status"] != "new":
                cand["status"] = "duplicate_text"
                cand["summary"] = "identical text to attempt #%d; skipped" % o["id"]
                self.out.trace("formula_decision", id=cand["id"], decision="skip", reason=cand["summary"])
                return
        res = None
        for _ in range(MAX_REPAIRS + 1):
            if time_up(SAFETY_MARGIN / 2):
                raise TimeUp()
            problem = check_formula_static(cand["expr"], cand["joins"], self.dbname, self.table, self.col)
            res = None
            if problem is not None:
                self.out.trace("formula_static_check", id=cand["id"], ok=False, reason=problem)
            else:
                try:
                    use_sample = SAMPLE_ROWS if ctx.n_rows > FULL_EVAL_THRESHOLD else None
                    res = self.evaluate(cand["expr"], cand["joins"], sample=use_sample)
                    exp_rows = min(ctx.n_rows, use_sample) if use_sample else ctx.n_rows
                    if res["n_rows"] != exp_rows:
                        problem = ("the query returns %d rows but the table has %d rows: the joins duplicate or drop "
                                   "rows. Use only LEFT JOINs that match at most one row, or correlated subqueries "
                                   "for aggregations" % (res["n_rows"], exp_rows))
                        res = None
                    elif use_sample and res["n_nonnull"] and res["n_match"] / res["n_nonnull"] >= 0.5:
                        res = self.evaluate(cand["expr"], cand["joins"], sample=None,
                                            purpose="evaluate formula (full table)")
                        if res["n_rows"] != ctx.n_rows:
                            problem = "the query returns %d rows but the table has %d rows" % (res["n_rows"], ctx.n_rows)
                            res = None
                except QueryError as e:
                    problem = "SQL error: %s" % e
                    res = None
            if problem is None and res is not None:
                break
            cand["status"] = "error"
            cand["summary"] = "FAILED: " + problem[:300]
            self.record_attempt(cand)
            low = problem.lower()
            if "maximum statement execution time" in low or "interrupted" in low or "timeout" in low:
                problem += " (the query is too slow: use cheaper constructs, avoid unneeded subqueries)"
            if cand["repairs"] >= MAX_REPAIRS or time_up(SAFETY_MARGIN):
                self.out.trace("formula_decision", id=cand["id"], decision="reject", reason=problem)
                return
            cand["repairs"] += 1
            self.out.trace("formula_repair_request", id=cand["id"], problem=problem, attempt=cand["repairs"])
            try:
                fix = self.llm.ask_json(repair_prompt(ctx, cand, problem), "repair formula #%d" % cand["id"])
            except LLMGiveUp as e:
                self.out.trace("formula_decision", id=cand["id"], decision="reject",
                               reason="repair failed: %s; last problem: %s" % (e, problem))
                return
            nexpr = str(fix.get("expr") or "").strip()
            if not nexpr:
                self.out.trace("formula_decision", id=cand["id"], decision="reject",
                               reason="repair returned no expression; last problem: " + problem)
                return
            cand["expr"] = nexpr
            cand["joins"] = str(fix.get("joins") or "").strip()
            cand["description"] = str(fix.get("description") or cand["description"])
            cand["sql"] = build_formula_sql(cand["expr"], cand["joins"], self.dbname, self.table)
            cand["key"] = self._key(cand)
            self.out.trace("formula_changed", id=cand["id"], how="LLM repair after: " + problem[:300],
                           description=cand["description"], joins=cand["joins"], expr=cand["expr"], sql=cand["sql"])
        else:
            return
        same = next((o for o in self.cands if o is not cand and o.get("key") == cand["key"] and
                     o["status"] in ("accepted", "evaluated", "rejected", "superseded", "duplicate")), None)
        if same is not None:
            cand["status"] = "duplicate_text"
            cand["summary"] = "after repair identical to attempt #%d; skipped" % same["id"]
            self.out.trace("formula_decision", id=cand["id"], decision="skip", reason=cand["summary"])
            return
        if cand["source"] == "llm":
            self.llm_evaluated += 1
        nn = res["n_nonnull"]
        conf = 100.0 * res["n_match"] / nn if nn else 0.0
        cand.update(conf=conf, n_nonnull=nn, n_match=res["n_match"], n_null=res["n_null"], status="evaluated")
        cand["summary"] = "conformity %s%% (%d of %d non-NULL values match; %d NULL formula values)" % (
            fmt_conf(conf), res["n_match"], nn, res["n_null"])
        cand["mismatch_text"] = self.mismatches(cand["expr"], cand["joins"]) if res["n_match"] < nn else ""
        self.record_attempt(cand)
        self.best_conf = max(self.best_conf, conf)
        self.out.trace("formula_evaluated", id=cand["id"], conformity=conf, n_rows=res["n_rows"], n_nonnull=nn,
                       n_match=res["n_match"], n_null_formula=res["n_null"], mismatch_examples=cand["mismatch_text"])
        self.decide(cand)

    def decide(self, cand):
        ctx = self.ctx
        conf = cand["conf"]
        if conf < ACCEPT_MIN_CONF:
            cand["status"] = "rejected"
            self.out.trace("formula_decision", id=cand["id"], decision="reject", conformity=conf,
                           reason="conformity %s%% is below the acceptance threshold %s%%" % (fmt_conf(conf), ACCEPT_MIN_CONF))
            return
        need_judge = conf < 100.0 or (ctx.n_distinct is not None and ctx.n_distinct <= 3)
        if need_judge:
            baseline = ctx.top_share
            try:
                v = self.llm.ask_json(judge_prompt(ctx, cand, baseline), "judge formula #%d" % cand["id"])
            except LLMGiveUp as e:
                strong = conf >= 95.0 and conf > baseline + 5.0
                self.out.trace("formula_decision", id=cand["id"], decision="accept" if strong else "reject",
                               conformity=conf, baseline_share=baseline,
                               reason="judge unavailable (%s); strong evidence rule: conformity >= 95%% and > baseline + 5" % e)
                if not strong:
                    cand["status"] = "rejected"
                    return
            else:
                verdict = str(v.get("verdict", "")).lower()
                self.out.trace("formula_judge", id=cand["id"], verdict=verdict, reason=v.get("reason"),
                               conformity=conf, baseline_share=baseline, distinct=ctx.n_distinct)
                if verdict != "accept":
                    cand["status"] = "rejected"
                    cand["summary"] += "; rejected by review: " + str(v.get("reason"))[:200]
                    self.out.trace("formula_decision", id=cand["id"], decision="reject", conformity=conf,
                                   reason="judged not a genuine derivation: %s" % v.get("reason"))
                    return
        if self.accepted:
            try:
                d = self.llm.ask_json(dedup_prompt(ctx, cand, self.accepted), "duplicate check #%d" % cand["id"])
                dup = d.get("duplicate_of")
                dup_c = next((c for c in self.accepted if str(c["id"]) == str(dup)), None) if dup is not None else None
            except LLMGiveUp:
                dup_c, d = None, {"reason": "check unavailable"}
            if dup_c is not None:
                if conf > dup_c["conf"]:
                    self.accepted = [c for c in self.accepted if c is not dup_c] + [cand]
                    dup_c["status"] = "superseded"
                    cand["status"] = "accepted"
                    self.out.trace("formula_decision", id=cand["id"], decision="accept (replaces #%d)" % dup_c["id"],
                                   reason="rewrite of #%d (%s) with higher conformity %s%% > %s%%" % (
                                       dup_c["id"], d.get("reason"), fmt_conf(conf), fmt_conf(dup_c["conf"])))
                else:
                    cand["status"] = "duplicate"
                    self.out.trace("formula_decision", id=cand["id"], decision="duplicate", duplicate_of=dup_c["id"],
                                   reason=str(d.get("reason")))
                return
        cand["status"] = "accepted"
        self.accepted.append(cand)
        self.out.trace("formula_decision", id=cand["id"], decision="accept", conformity=conf,
                       reason="conformity %s%% over %d non-NULL values; different from accepted formulas" % (
                           fmt_conf(conf), cand["n_nonnull"]))

    # ---------------- exploration -----------------
    def run_explore(self, queries):
        if not isinstance(queries, list):
            return
        for q in queries[:4]:
            if not isinstance(q, str) or not q.strip():
                continue
            qq = q.strip().rstrip(";")
            if not re.search(r"\blimit\s+\d+\s*(,\s*\d+)?\s*$", qq, re.I):
                qq += " LIMIT 50"
            try:
                cols, rows = self.db.query(qq, purpose="LLM exploration query", max_rows=50, timeout=60)
                self.ctx.explore.append((q.strip(), fmt_rows(cols, rows, 25, 40, 20)))
            except QueryError as e:
                self.ctx.explore.append((q.strip(), "ERROR: %s" % str(e)[:300]))

    def _probe_chunk(self, chunk, sel, tv, src, results, depth):
        sql = "SELECT COUNT(%s) AS nn, %s FROM %s AS s" % (tv, ", ".join(sel), src)
        try:
            _, rows = self.db.query(sql, purpose="data probe (same-table patterns)", timeout=120)
        except QueryError:
            if depth < 3 and len(chunk) > 1:
                h = len(chunk) // 2
                self._probe_chunk(chunk[:h], sel[:h], tv, src, results, depth + 1)
                self._probe_chunk(chunk[h:], sel[h:], tv, src, results, depth + 1)
            return
        nn = int(rows[0][0] or 0)
        for idx, (lab, es, et) in enumerate(chunk):
            m = rows[0][idx + 1]
            if nn and m is not None:
                results.append((100.0 * float(m) / nn, lab, et))

    # ---------------- data probe (no LLM) -----------------
    def probe(self):
        ctx, db = self.ctx, self.db
        tinfo = self.sch.tables[self.table]
        others = [c for c in tinfo["cols"] if c["name"] != self.col]
        kind = ctx.kind
        src = self._src(min(ctx.n_rows, 5000))
        exprs = []   # (label, expr over alias s, expr over alias t)
        same = [c for c in others if target_kind(c["data_type"]) == kind]
        for c in same[:60]:
            exprs.append(("copy of %s" % c["name"], "s.%s" % qid(c["name"]), "t.%s" % qid(c["name"])))
        if kind == "numeric":
            num = [c for c in others if target_kind(c["data_type"]) == "numeric"][:40]
            ops = [("{a} + {b}", "{a} + {b}"), ("{a} - {b}", "{a} - {b}"), ("{b} - {a}", "{b} - {a}"),
                   ("{a} * {b}", "{a} * {b}"), ("{a} / {b}", "{a} / NULLIF({b}, 0)"),
                   ("{b} / {a}", "{b} / NULLIF({a}, 0)")]
            for i in range(len(num)):
                for j in range(i + 1, len(num)):
                    a, b = num[i]["name"], num[j]["name"]
                    for lab, f in ops:
                        exprs.append((lab.format(a=a, b=b),
                                      f.format(a="(s.%s + 0.0)" % qid(a), b="(s.%s + 0.0)" % qid(b)),
                                      f.format(a="t.%s" % qid(a), b="t.%s" % qid(b))))
        if not exprs:
            ctx.probe_text = "(nothing to probe: no other columns of a comparable type in the target table)"
            return []
        results = []
        tv = "s.%s" % qid(self.col)
        for k in range(0, len(exprs), 300):
            chunk = exprs[k:k + 300]
            sel = []
            for idx, (_, es, _) in enumerate(chunk):
                cmp_ = compare_sql(kind, ctx.info["data_type"], ctx.info["scale"], tv, "(%s)" % es)
                sel.append("SUM(CASE WHEN %s IS NOT NULL AND (%s) THEN 1 ELSE 0 END) AS m%d" % (tv, cmp_, idx))
            self._probe_chunk(chunk, sel, tv, src, results, 0)
        results.sort(key=lambda x: -x[0])
        cands = [r for r in results if r[0] >= 90.0][:4]
        lines = ["%s%% of sampled non-NULL values match: %s" % (fmt_conf(p), lab) for p, lab, _ in results[:6] if p >= 30]
        ctx.probe_text = "\n".join(lines) if lines else \
            "no simple same-table pattern (copy / arithmetic of two columns) reached 30%"
        self.out.trace("probe_result", tested=len(exprs), best=[(round(p, 2), lab) for p, lab, _ in results[:10]])
        return [(lab, et) for p, lab, et in cands]

    # ---------------- main loop -----------------
    def run(self):
        ctx, out = self.ctx, self.out
        self.setup()
        if self.all_null:
            return
        # Task 1: semantics
        try:
            obj = self.llm.ask_json(semantics_prompt(ctx), "semantics")
            ctx.semantics_obj = obj
            ctx.semantics = "%s\nDerivable: %s. %s\nCandidate sources: %s" % (
                obj.get("semantics", ""), obj.get("derivable", "?"), obj.get("reasoning", ""),
                ", ".join(str(x) for x in (obj.get("candidate_sources") or [])[:30]))
            out.trace("semantics", semantics=obj.get("semantics"), derivable=obj.get("derivable"),
                      reasoning=obj.get("reasoning"), candidate_sources=obj.get("candidate_sources"))
            self.run_explore(obj.get("explore_queries"))
        except LLMGiveUp as e:
            out.trace("semantics_failed", error=str(e))
            ctx.semantics = "(semantic analysis unavailable)"
        # data probe (independent of the LLM)
        try:
            probe_cands = self.probe()
        except QueryError:
            probe_cands = []
        for lab, et in probe_cands:
            c = self.new_cand("probe", "data probe: " + lab, "", et, 0)
            self.process_candidate(c)
        # discovery rounds
        stale = 0
        giveups = 0
        for rnd in range(1, MAX_ROUNDS + 1):
            if time_up(SAFETY_MARGIN):
                out.trace("info", message="time limit approaching; stopping the search")
                break
            before_acc, before_best = len(self.accepted), self.best_conf
            try:
                obj = self.llm.ask_json(proposal_prompt(ctx, self.accepted, self.attempts, rnd),
                                        "propose formulas round %d" % rnd)
            except LLMGiveUp as e:
                giveups += 1
                out.trace("round_failed", round=rnd, error=str(e))
                if giveups >= 3:
                    break
                continue
            self.llm_rounds_ok += 1
            forms = [f for f in (obj.get("formulas") or []) if isinstance(f, dict)][:MAX_FORMULAS_PER_ROUND]
            complete = bool(obj.get("complete"))
            out.trace("round", round=rnd, n_formulas=len(forms), complete=complete, analysis=obj.get("analysis"))
            self.run_explore(obj.get("explore_queries"))
            if not forms and complete and not self.accepted:
                self.llm_declared_none = True
            for f in forms:
                if time_up(SAFETY_MARGIN / 2):
                    break
                c = self.new_cand("llm", str(f.get("description") or ""), str(f.get("joins") or ""),
                                  str(f.get("expr") or ""), rnd)
                self.process_candidate(c)
            progressed = len(self.accepted) > before_acc or (
                not self.accepted and self.best_conf >= 40 and self.best_conf > before_best + 1.0)
            stale = 0 if progressed else stale + 1
            if stale >= 2 or (complete and not forms and self.accepted):
                break

    # ---------------- outcome -----------------
    def decide_outcome(self):
        """-> ('formulas', list) | ('not_derived', reason) | ('error', message)"""
        if self.accepted:
            return "formulas", sorted(self.accepted, key=lambda c: (-c["conf"], c["id"]))
        if self.all_null:
            return "not_derived", "all values of the column are NULL: nothing to derive"
        if self.fatal:
            return "error", self.fatal
        if self.llm_rounds_ok >= 1 and (self.llm_evaluated >= 1 or self.llm_declared_none):
            best = max((a["conf"] for a in self.attempts if a["status"] != "error"), default=0.0)
            return "not_derived", ("no formula reached the acceptance threshold (best conformity %s%%); %d formulas "
                                   "evaluated on the data, %d LLM rounds" % (fmt_conf(best), len(self.attempts),
                                                                             self.llm_rounds_ok))
        return "error", ("no data-based decision could be made: %d LLM rounds completed, %d LLM formulas could be "
                         "evaluated (LLM failures, malformed answers, unusable SQL or time limit)" %
                         (self.llm_rounds_ok, self.llm_evaluated))


def finalize(out, run, error_msg=None, partial=False):
    """Write exactly one outcome. Safe to call from the watchdog thread."""
    with out.lock:
        if out.done:
            return
        out.done = True
        try:
            if run is None or (error_msg and not run.accepted):
                kind, payload = "error", error_msg or "run did not start"
            else:
                kind, payload = run.decide_outcome()
            if kind == "formulas":
                files = []
                for i, c in enumerate(payload, 1):
                    out.write_file("_formula_%d.sql" % i, "-- confidence: %s\n%s\n" % (fmt_conf(c["conf"]), c["sql"]))
                    files.append({"file": "%s_formula_%d.sql" % (out.base, i), "id": c["id"],
                                  "confidence": c["conf"], "source": c["source"], "description": c["description"]})
                out.trace("final_decision", decision="derived", formulas=files,
                          reason="%d formula(s) verified against the stored values and accepted%s" % (
                              len(files), " (stopped at the time limit)" if partial else ""))
            elif kind == "not_derived":
                out.write_file("_not_derived.txt", "")
                out.trace("final_decision", decision="not_derived", reason=payload)
            else:
                out.write_file("_error.txt", str(payload) + "\n")
                out.trace("final_decision", decision="error", reason=str(payload))
        except Exception as e:  # last resort
            try:
                out.write_file("_error.txt", "internal error while writing results: %r\n" % e)
                out.trace("final_decision", decision="error", reason="internal error while writing results: %r" % e)
            except Exception:
                pass


def parse_args(argv):
    column = llm = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--column" and i + 1 < len(argv):
            column = argv[i + 1]
            i += 1
        elif a.startswith("--column="):
            column = a.split("=", 1)[1]
        elif a == "--llm" and i + 1 < len(argv):
            llm = argv[i + 1]
            i += 1
        elif a.startswith("--llm="):
            llm = a.split("=", 1)[1]
        i += 1
    return column, llm


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    column, llm_name = parse_args(sys.argv[1:])
    raw = column or "unknown_column"
    parts = raw.split(".")
    if len(parts) >= 3:
        dbname, table, col = parts[0], ".".join(parts[1:-1]), parts[-1]
        base = "%s.%s.%s" % (dbname, table, col)
    else:
        dbname = table = col = None
        base = re.sub(r"[^\w.\-]", "_", raw)
    out = Out(base)
    out.trace("start", argv=sys.argv[1:], time_limit_s=TIME_LIMIT)
    state = {"run": None}

    def watchdog():
        out.trace("watchdog", message="hard time limit reached; writing results found so far")
        finalize(out, state["run"], partial=True)
        os._exit(0)

    def on_signal(signum, frame):
        out.trace("signal", signum=signum, message="terminated by signal; writing results found so far")
        finalize(out, state["run"], partial=True)
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", signal.SIGTERM)):
        try:
            signal.signal(sig, on_signal)
        except Exception:
            pass
    timer = threading.Timer(max(1.0, TIME_LIMIT - HARD_MARGIN), watchdog)
    timer.daemon = True
    timer.start()
    try:
        if dbname is None:
            raise Permanent("--column must have the form <database>.<table>.<column>, got %r" % raw)
        if llm_name not in ("gpt5", "sonnet55"):
            raise Permanent("--llm must be gpt5 or sonnet55, got %r" % llm_name)
        try:
            db_cfg = load_json("db_access.json")
        except Exception as e:
            raise Permanent("cannot read db_access.json: %r" % e)
        try:
            llm_cfg = load_json("llm_%s.json" % llm_name)
        except Exception as e:
            raise Permanent("cannot read llm_%s.json: %r" % (llm_name, e))
        llm = LLM(llm_cfg, out)
        db = DB(db_cfg, out)
        db.connect()
        run = Run(dbname, table, col, out, db, llm)
        state["run"] = run
        try:
            run.run()
        except TimeUp:
            out.trace("info", message="time limit reached")
        except LLMFatal as e:
            out.trace("error", where="llm", error=str(e))
            run.fatal = str(e)
        if run.accepted:   # sanity-run each saved formula before finalizing
            for i, c in enumerate(sorted(run.accepted, key=lambda c: (-c["conf"], c["id"])), 1):
                if time_up(30):
                    break
                try:
                    db.query("SELECT * FROM (%s) AS f LIMIT 1" % c["sql"],
                             purpose="final check of saved formula %d" % i, max_rows=1, timeout=60)
                except Exception as e:
                    out.trace("final_check_failed", id=c["id"], error=str(e))
        finalize(out, run, partial=time_up(SAFETY_MARGIN))
    except Permanent as e:
        out.trace("error", where="permanent", error=str(e))
        finalize(out, state["run"], error_msg=str(e))
    except BaseException as e:  # never crash
        out.trace("error", where="unexpected", error=repr(e), traceback=traceback.format_exc())
        finalize(out, state["run"], error_msg="unexpected error: %r" % e)
    finally:
        timer.cancel()
        out.trace("end", elapsed_s=round(time.monotonic() - START, 1))
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
