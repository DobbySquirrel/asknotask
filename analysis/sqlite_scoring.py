"""Original read-only SQLite execution and normalization routines."""
from __future__ import annotations
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Optional,Sequence
@dataclass
class ExecResult:
    ok: bool
    rows: Optional[list[tuple]]
    n_rows: int
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None

def norm_cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except Exception:
            return v
    return v

def norm_row(row: Sequence[Any]) -> tuple:
    return tuple(norm_cell(c) for c in row)

def sort_key(x: Any):
    if x is None:
        return (0, "")
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return (1, float(x))
    return (2, str(x))

def compare_results(
    pred_rows: list[tuple],
    gold_rows: list[tuple],
    mode: str = "bird",
    order_by: bool = False,
) -> bool:
    """mode=bird: set of tuples. mode=clear: CLEAR evaluation.py."""
    if mode == "clear":
        if not pred_rows:
            return False
        if order_by:
            if len(gold_rows) != len(pred_rows):
                return False
            if gold_rows and any(
                len(row) != len(gold_rows[0]) for row in gold_rows + pred_rows
            ):
                return False
            for g, p in zip(gold_rows, pred_rows):
                if tuple(sorted(g, key=sort_key)) != tuple(sorted(p, key=sort_key)):
                    return False
            return True
        flat_gold = Counter(item for row in gold_rows for item in row)
        flat_pred = Counter(item for row in pred_rows for item in row)
        return flat_gold == flat_pred

    pred_set = {norm_row(r) for r in pred_rows}
    gold_set = {norm_row(r) for r in gold_rows}
    return pred_set == gold_set

def _sqlite_run(sql: str, db_path: str, timeout_s: float) -> ExecResult:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=min(timeout_s, 30))
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    start = time.time()

    def handler():
        return 1 if time.time() - start > timeout_s else 0

    conn.set_progress_handler(handler, 50_000)
    try:
        cur = conn.execute(sql)
        rows = [tuple(r) for r in cur.fetchall()]
        return ExecResult(ok=True, rows=rows, n_rows=len(rows))
    except Exception as e:
        msg = str(e) or "sql_error"
        if "interrupted" in msg.lower() or time.time() - start > timeout_s:
            msg = f"timeout>{timeout_s}s"
        return ExecResult(ok=False, rows=None, n_rows=0, error=msg)
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()

def _mysql_run(sql: str, db_path: str, timeout_s: float, dsn: dict[str, Any]) -> ExecResult:
    try:
        import pymysql
    except ImportError:
        return ExecResult(
            ok=False, rows=None, n_rows=0, skipped=True,
            skip_reason="pymysql not installed",
        )
    kwargs = {
        "user": dsn.get("user") or "root",
        "password": dsn.get("password") or "",
        "database": dsn.get("database") or db_path,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.Cursor,
        "connect_timeout": min(int(timeout_s), 30),
        "read_timeout": int(timeout_s),
        "write_timeout": int(timeout_s),
    }
    if dsn.get("unix_socket"):
        kwargs["unix_socket"] = dsn["unix_socket"]
    else:
        kwargs["host"] = dsn.get("host") or "127.0.0.1"
        kwargs["port"] = int(dsn.get("port") or 13306)
    conn = None
    try:
        conn = pymysql.connect(**kwargs)
        with conn.cursor() as cur:
            pin = (dsn.get("timestamp") or "").strip()
            if pin and pin.lower() not in {"now", "off", "none"}:
                cur.execute("SET timestamp = UNIX_TIMESTAMP(%s)", (pin,))
            # 服务端杀超时 SELECT；pymysql read_timeout 杀不掉正在算的 JOIN
            cur.execute("SET SESSION max_execution_time = %s", (max(1, int(timeout_s * 1000)),))
            cur.execute(sql)
            rows = [tuple(r) for r in cur.fetchall()]
        return ExecResult(ok=True, rows=rows, n_rows=len(rows))
    except Exception as e:
        return ExecResult(ok=False, rows=None, n_rows=0, error=str(e) or "mysql_error")
    finally:
        if conn is not None:
            conn.close()

def run_sql(
    sql: str,
    db_path: str,
    dialect: str = "sqlite",
    timeout_s: float = 30.0,
    mysql_dsn: Optional[dict[str, Any]] = None,
) -> ExecResult:
    sql = (sql or "").strip().rstrip(";")
    if not sql:
        return ExecResult(ok=False, rows=None, n_rows=0, error="empty_sql")
    if dialect == "mysql":
        if not mysql_dsn:
            return ExecResult(
                ok=False, rows=None, n_rows=0, skipped=True,
                skip_reason="mysql_dsn not configured",
            )
        return _mysql_run(sql, db_path, timeout_s, mysql_dsn)
    from pathlib import Path
    if not db_path or not Path(db_path).exists():
        return ExecResult(
            ok=False, rows=None, n_rows=0, skipped=True,
            skip_reason=f"missing sqlite: {db_path}",
        )
    return _sqlite_run(sql, db_path, timeout_s)
