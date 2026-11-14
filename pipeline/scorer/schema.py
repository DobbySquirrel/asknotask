"""把选项里提到的表列收成打分提示里的 schema 文本，过长时逐步丢掉例子和未绑定列。"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MAX_LEN = 8192
QUAL = re.compile(
    r'"([^"]+)"\s*\.\s*"([^"]+)"|([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)'
)


def column_types(path: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    if not path or not Path(path).is_file():
        return out
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            for col in con.execute(f'PRAGMA table_info("{table}")'):
                out[(table.lower(), str(col[1]).lower())] = str(col[2] or "")
    finally:
        con.close()
    return out


def tables_in(options: list[str], choices: list) -> set[str]:
    found: set[str] = set()
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for element in choice.get("elements") or []:
            text = str(element)
            if "." in text:
                found.add(text.split(".", 1)[0].strip().strip('"').lower())
    for option in options:
        for match in QUAL.finditer(option or ""):
            name = match.group(1) or match.group(3)
            if name:
                found.add(name.strip().lower())
    return found


def schema_rows(rich: dict, types: dict[tuple[str, str], str], wanted: set[str]) -> list[dict]:
    rows = []
    for table, cols in (rich or {}).items():
        if wanted and table.lower() not in wanted:
            continue
        for col, meta in (cols or {}).items():
            rows.append({
                "table": table,
                "column": col,
                "type": types.get((table.lower(), str(col).lower()), ""),
                "description": str((meta or {}).get("description") or ""),
                "examples": list((meta or {}).get("examples") or [])[:3],
                "bound": False,
            })
    return rows


def mark_bound(rows: list[dict], choices: list) -> None:
    bound: set[tuple[str, str]] = set()
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for element in choice.get("elements") or []:
            text = str(element).strip().strip('"')
            if "." in text:
                table, col = text.split(".", 1)
                bound.add((table.lower(), col.strip().strip('"').lower()))
    for row in rows:
        row["bound"] = (row["table"].lower(), row["column"].lower()) in bound


def render_rows(rows: list[dict], drop_examples: bool, drop_unbound_desc: bool, drop_unbound: bool) -> str:
    lines = []
    for row in rows:
        if drop_unbound and not row["bound"]:
            continue
        desc = "" if drop_unbound_desc and not row["bound"] else row["description"]
        examples = [] if drop_examples else row["examples"]
        extra = f"; examples: {', '.join(str(v) for v in examples)}" if examples else ""
        lines.append(f"{row['table']}.{row['column']} {row['type']} -- {desc}{extra}".rstrip())
    return "\n".join(lines)


def fit_schema(rows: list[dict], count, max_len: int = MAX_LEN) -> tuple[str, bool]:
    last = ""
    for drop_examples, drop_desc, drop_cols in (
        (False, False, False),
        (True, False, False),
        (True, True, False),
        (True, True, True),
    ):
        last = render_rows(rows, drop_examples, drop_desc, drop_cols)
        if count(last) <= max_len:
            return last, False
    return last, True
