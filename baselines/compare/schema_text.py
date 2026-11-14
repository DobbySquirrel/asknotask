"""从 GoldItem 取出 {table: [cols]} 和 parser/检测用的 schema 字符串。"""
from __future__ import annotations

import csv
import re
import sqlite3
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

# Use this repository's GoldItem and SQLite schema loader, not paper_exp/eval.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
import schema_text as _repo_schema  # noqa: E402

GoldItem = _repo_schema.GoldItem

def schema_for_gold(gold: GoldItem) -> dict[str, list[str]]:
    return dict(_repo_schema.schema_map(gold) or {})

_SKIP_TABLES = {"sqlite_sequence", "sqlite_master", "sqlite_stat1", "sqlite_stat4"}


def schema_map(gold: GoldItem) -> dict[str, list[str]]:
    return dict(schema_for_gold(gold) or {})


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _typed_example(val: Any):
    """保留 sqlite 原类型：int/float 原样，文本仍是 str。"""
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


def format_example(val: Any) -> str:
    """CLEAR like 子句：int/float 不加引号，string 加单引号。"""
    if isinstance(val, bool):
        return str(int(val))
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        return str(int(val)) if val.is_integer() else str(val)
    text = str(val).replace("'", "\\'")
    return f"'{text}'"


@lru_cache(maxsize=256)
def _sqlite_examples(db_path: str) -> dict[tuple[str, str], tuple[str, ...]]:
    path = Path(db_path)
    if not db_path or not path.exists():
        return {}
    out: dict[tuple[str, str], tuple[str, ...]] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
        for (table,) in tables:
            if not table or table.lower() in _SKIP_TABLES:
                continue
            cols = [
                row[1]
                for row in conn.execute(f"PRAGMA table_info({_qident(table)})").fetchall()
                if row[1]
            ]
            n_rows = 0
            try:
                n_rows = int(conn.execute(f"SELECT COUNT(*) FROM {_qident(table)}").fetchone()[0] or 0)
            except sqlite3.Error:
                n_rows = 0
            for col in cols:
                try:
                    if n_rows > 20000:
                        rows = conn.execute(
                            f"SELECT {_qident(col)} FROM {_qident(table)} "
                            f"WHERE {_qident(col)} IS NOT NULL LIMIT 3"
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} "
                            f"WHERE {_qident(col)} IS NOT NULL LIMIT 3"
                        ).fetchall()
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
    dataset = gold.dataset or ""
    if dataset in {"electricity", "electricity_xlsx"}:
        from adapters.electricity import load_electricity_col_meta

        return dict(load_electricity_col_meta())
    db_path = gold.db_path or ""
    if db_path:
        found = _bird_descriptions(str(Path(db_path).parent))
        if found:
            return found
    return {}


def _examples_for(gold: GoldItem) -> dict[tuple[str, str], tuple]:
    dataset = gold.dataset or ""
    if dataset in {"electricity", "electricity_xlsx"}:
        from adapters.electricity import load_electricity_col_examples

        return dict(load_electricity_col_examples())
    if gold.db_path:
        return dict(_sqlite_examples(gold.db_path))
    return {}


_IDENT = re.compile(r"[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff]*")


def relevant_tables(gold: GoldItem, smap: Optional[dict[str, list[str]]] = None) -> list[str]:
    """Gold SQL 里出现的表 + 问句/Evidence 能对上的表名。用于电力裁 01。"""
    smap = smap if smap is not None else schema_map(gold)
    low = {str(t).lower(): t for t in (smap or {})}
    hits: list[str] = []

    def _add(name: str) -> None:
        real = low.get(str(name or "").lower())
        if real and real not in hits:
            hits.append(real)

    for tok in _IDENT.findall(gold.gold_sql or ""):
        _add(tok)
    blob = f"{gold.question or ''} {(gold.meta or {}).get('evidence') or ''}".lower()
    for t in smap or {}:
        key = t.lower()
        if key in blob or key.replace("_", " ") in blob:
            _add(t)
    for t in (gold.meta or {}).get("tables") or []:
        _add(t)
    return hits


def detect_schema_opts(gold: GoldItem) -> tuple[Optional[list[str]], bool]:
    """电力检出：不放 example，只送相关表。其它数据集保持全库 + example。"""
    if (gold.dataset or "") not in {"electricity", "electricity_xlsx"}:
        return None, True
    tabs = relevant_tables(gold)
    return (tabs or None), False


def schema_map_for_prompt(gold: GoldItem) -> dict[str, list[str]]:
    smap = schema_map(gold)
    tables, _ = detect_schema_opts(gold)
    if not tables:
        return smap
    allow = {t.lower() for t in tables}
    return {t: cols for t, cols in smap.items() if t.lower() in allow}


def schema_rich(
    gold: GoldItem,
    tables: Optional[list[str]] = None,
    with_examples: bool = True,
) -> dict[str, dict[str, dict[str, Any]]]:
    """四个数据集统一：{table: {col: {description, examples}}}。"""
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


def schema_numbered_rich(gold: GoldItem) -> str:
    """1-BC 检出用：与 CLEAR/AmbiSQL 同一套 description + examples。"""
    tables, with_ex = detect_schema_opts(gold)
    rich = schema_rich(gold, tables=tables, with_examples=with_ex)
    if not rich:
        return schema_clear_text(schema_map_for_prompt(gold))
    lines = []
    for i, (table, cols) in enumerate(rich.items(), 1):
        bits = []
        for col, meta in (cols or {}).items():
            body = clear_interp_text(
                col, (meta or {}).get("description") or "", (meta or {}).get("examples") or []
            ).rstrip(".")
            rest = body
            if body.lower().startswith(str(col).lower()):
                rest = body[len(col) :].lstrip(" .")
            bits.append(f"{col} ({rest})" if rest else col)
        lines.append(f"[{i}] {table} : " + " , ".join(bits))
    return "\n".join(lines)


def schema_ddl_text(schema: dict[str, list[str]]) -> str:
    parts = []
    for table, cols in (schema or {}).items():
        inner = ", ".join(f'"{c}" TEXT' for c in cols)
        parts.append(f'CREATE TABLE "{table}" ({inner});')
    return "\n".join(parts)


def schema_json(schema: dict[str, list[str]]) -> dict[str, Any]:
    return {t: list(cols) for t, cols in (schema or {}).items()}


def _like_clause(examples: list) -> str:
    vals = [format_example(x) for x in (examples or []) if x is not None and str(x).strip() != ""]
    if not vals:
        return ""
    if len(vals) == 1:
        return vals[0]
    return ", ".join(vals[:-1]) + f" and {vals[-1]}"


def clear_interp_text(col: str, description: str, examples: list) -> str:
    """CLEAR：value 写进释义，不另开 examples 字段。"""
    core = " ".join((description or "").split()) or col
    core = core.rstrip(".")
    likes = _like_clause(examples)
    if likes:
        return f"{core}, like {likes}."
    return f"{core}."


def _interp_line(table: str, col: str, description: str, examples: list) -> str:
    return f'{col}: In table "{table}". {clear_interp_text(col, description, examples)}'


def interp_lookup_rich(
    gold: GoldItem,
    tables: Optional[list[str]] = None,
    with_examples: bool = True,
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for table, cols in schema_rich(gold, tables=tables, with_examples=with_examples).items():
        out[table] = {}
        for col, meta in cols.items():
            out[table][col] = _interp_line(
                table, col, meta.get("description") or "", meta.get("examples") or []
            )
    return out


def interpretations(
    gold_or_schema,
    tables: Optional[list[str]] = None,
    with_examples: bool = True,
) -> list[str]:
    """CLEAR 01 行：`col: In table \"t\". desc, like v1, v2 and v3.`"""
    if hasattr(gold_or_schema, "dataset"):
        if tables is None and with_examples:
            tables, with_examples = detect_schema_opts(gold_or_schema)
        rows = []
        for table, cols in interp_lookup_rich(
            gold_or_schema, tables=tables, with_examples=with_examples
        ).items():
            rows.extend(cols.values())
        return rows
    rows = []
    for table, cols in (gold_or_schema or {}).items():
        for col in cols:
            rows.append(_interp_line(table, col, col, []))
    return rows
