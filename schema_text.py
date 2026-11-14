"""从本仓库 dataset/databases 的 sqlite 读表结构，并格式化成检测 / parser 用的 schema 文本。"""
from __future__ import annotations

import csv
import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional

REPO = Path(__file__).resolve().parent
_SKIP_TABLES = {"sqlite_sequence", "sqlite_master", "sqlite_stat1", "sqlite_stat4"}
Dialect = Literal["sqlite", "mysql"]


def resolve_db_path(db_path: str | None = None, dataset: str = "", db_id: str = "") -> str:
    """优先用给定路径（相对路径按仓库根算），找不到再试 dataset/databases。"""
    raw = (db_path or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = REPO / path
        if path.is_file():
            return str(path)
    if dataset and db_id:
        for cand in (
            REPO / "dataset" / "databases" / dataset / db_id / f"{db_id}.sqlite",
            REPO / "dataset" / "databases" / dataset / f"{db_id}.sqlite",
        ):
            if cand.is_file():
                return str(cand)
    return ""


@dataclass
class GoldItem:
    id: str
    dataset: str
    db_id: str
    question: str
    db_path: Optional[str] = None
    dialect: Dialect = "sqlite"
    gold_sql: Optional[str] = None
    gold_sqls: list[str] = field(default_factory=list)
    ambig_type: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def all_gold_sqls(self) -> list[str]:
        out: list[str] = []
        for s in [self.gold_sql, *self.gold_sqls]:
            t = (s or "").strip().rstrip(";")
            if t and t not in out:
                out.append(t)
        return out

    def resolved_db_path(self) -> str:
        return resolve_db_path(self.db_path, self.dataset or "", self.db_id or "")


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'



_SQL_TIMEOUT_S = 60.0


def _exec_sql(conn: sqlite3.Connection, sql: str, timeout_s: float | None = None):
    """Run one SQL and fetch all rows, aborting after timeout_s (progress_handler)."""
    deadline = time.monotonic() + (_SQL_TIMEOUT_S if timeout_s is None else float(timeout_s))
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.set_progress_handler(None, 0)

@lru_cache(maxsize=4096)
def load_sqlite_schema(db_path: str) -> dict[str, list[str]]:
    if not db_path or not Path(db_path).is_file():
        return {}
    schema: dict[str, list[str]] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
    try:
        tables = _exec_sql(conn, "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        for (table,) in tables:
            if not table or table.lower() in _SKIP_TABLES:
                continue
            cols = [
                row[1]
                for row in _exec_sql(conn, f"PRAGMA table_info({_qident(table)})")
                if row[1]
            ]
            if cols:
                schema[table] = cols
    finally:
        conn.close()
    return schema


def schema_map(gold: GoldItem) -> dict[str, list[str]]:
    return dict(load_sqlite_schema(gold.resolved_db_path()) or {})


def schema_map_for_prompt(gold: GoldItem) -> dict[str, list[str]]:
    return schema_map(gold)


def _typed_example(val: Any):
    if val is None:
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val.is_integer() and abs(val) < 1e12:
            return int(val)
        return val
    text = str(val).replace("\n", " ").strip()
    if not text:
        return None
    if len(text) > 80:
        text = text[:77] + "..."
    return text


def _format_example(val: Any) -> str:
    if isinstance(val, bool):
        return str(int(val))
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(int(val)) if val.is_integer() else str(val)
    text = str(val).replace("'", "\\'")
    return f"'{text}'"


@lru_cache(maxsize=256)
def _sqlite_examples(db_path: str) -> dict[tuple[str, str], tuple]:
    if not db_path or not Path(db_path).is_file():
        return {}
    out: dict[tuple[str, str], tuple] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
    try:
        tables = _exec_sql(conn, "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
        for (table,) in tables:
            if not table or table.lower() in _SKIP_TABLES:
                continue
            cols = [
                row[1]
                for row in _exec_sql(conn, f"PRAGMA table_info({_qident(table)})")
                if row[1]
            ]
            budget = time.monotonic() + 15.0
            for col in cols:
                if time.monotonic() >= budget:
                    break
                try:
                    # Never COUNT(*) / DISTINCT here: both can full-scan a large BIRD table.
                    remain = max(0.2, budget - time.monotonic())
                    rows = _exec_sql(
                        conn,
                        f"SELECT {_qident(col)} FROM {_qident(table)} "
                        f"WHERE {_qident(col)} IS NOT NULL LIMIT 3",
                        timeout_s=min(2.0, remain),
                    )
                except sqlite3.Error:
                    continue
                vals = tuple(v for v in (_typed_example(r[0]) for r in rows) if v is not None)
                if vals:
                    out[(table.lower(), col.lower())] = vals
    finally:
        conn.close()
    return out


@lru_cache(maxsize=64)
def _bird_descriptions(db_dir: str) -> dict[tuple[str, str], str]:
    desc_dir = Path(db_dir) / "database_description"
    if not desc_dir.is_dir():
        return {}
    out: dict[tuple[str, str], str] = {}
    for csv_path in desc_dir.glob("*.csv"):
        table = csv_path.stem.strip()
        try:
            with csv_path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    orig = (row.get("original_column_name") or "").strip()
                    alias = (row.get("column_name") or "").strip()
                    desc = (row.get("column_description") or "").strip()
                    value_desc = (row.get("value_description") or "").strip()
                    if value_desc and value_desc not in desc:
                        desc = f"{desc} ({value_desc})" if desc else value_desc
                    for col in (orig, alias):
                        if col:
                            out[(table.lower(), col.lower())] = desc
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
    return out


def _descriptions_for(gold: GoldItem) -> dict[tuple[str, str], str]:
    db_path = gold.resolved_db_path()
    if not db_path:
        return {}
    return dict(_bird_descriptions(str(Path(db_path).parent)) or {})


def _examples_for(gold: GoldItem) -> dict[tuple[str, str], tuple]:
    db_path = gold.resolved_db_path()
    if not db_path:
        return {}
    return dict(_sqlite_examples(db_path))


def schema_rich(
    gold: GoldItem,
    tables: Optional[list[str]] = None,
    with_examples: bool = True,
) -> dict[str, dict[str, dict[str, Any]]]:
    """{table: {col: {description, examples}}}。"""
    smap = schema_map(gold)
    if tables:
        allow = {t.lower() for t in tables}
        smap = {t: cols for t, cols in smap.items() if t.lower() in allow}
    descs = _descriptions_for(gold)
    examples = _examples_for(gold) if with_examples else {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for table, cols in (smap or {}).items():
        tkey = (table or "").lower()
        out[table] = {}
        for col in cols:
            ckey = (col or "").lower()
            out[table][col] = {
                "description": descs.get((tkey, ckey), ""),
                "examples": list(examples.get((tkey, ckey), ())) if with_examples else [],
            }
    return out


def schema_clear_text(schema: dict[str, list[str]]) -> str:
    lines = []
    for i, (table, cols) in enumerate((schema or {}).items(), 1):
        lines.append(f"[{i}] {table} : " + " , ".join(cols))
    return "\n".join(lines)


def _like_clause(examples: list) -> str:
    vals = [_format_example(x) for x in (examples or []) if x is not None and str(x).strip() != ""]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    return ", ".join(vals[:-1]) + f" and {vals[-1]}"


def _clear_interp_text(col: str, description: str, examples: list) -> str:
    core = " ".join((description or "").split()) or col
    core = core.rstrip(".")
    likes = _like_clause(examples)
    if likes:
        return f"{core}, like {likes}."
    return f"{core}."


def schema_numbered_rich(gold: GoldItem) -> str:
    """检出用：表列 + 列说明和取值样例。"""
    rich = schema_rich(gold, with_examples=True)
    if not rich:
        return schema_clear_text(schema_map_for_prompt(gold))
    lines = []
    for i, (table, cols) in enumerate(rich.items(), 1):
        bits = []
        for col, meta in (cols or {}).items():
            body = _clear_interp_text(
                col, (meta or {}).get("description") or "", (meta or {}).get("examples") or []
            ).rstrip(".")
            rest = body
            if body.lower().startswith(str(col).lower()):
                rest = body[len(col) :].lstrip(" .")
            bits.append(f"{col} ({rest})" if rest else col)
        lines.append(f"[{i}] {table} : " + " , ".join(bits))
    return "\n".join(lines)
