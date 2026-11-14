"""Official target gold SQL for one question id."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


def gold_choice_paths() -> list[Path]:
    """仓库内的官方目标 SQL 表。若设置了 GOLD_CHOICE，只读这一份。"""
    env = _env_path("GOLD_CHOICE")
    if env:
        return [env]
    candidates = (
        REPO / "dataset" / "birdtrain" / "gold_choice.jsonl",
        REPO / "dataset" / "clambsql" / "gold_choice.jsonl",
    )
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


@lru_cache(maxsize=1)
def _choice_table() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in gold_choice_paths():
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("id") or row.get("qid") or "")
            if qid:
                out[qid] = row
    return out


@lru_cache(maxsize=1)
def _repo_golds() -> dict[str, object]:
    from pipeline.checks.runtime import load_golds
    out = {}
    for ds in ("birdtrain", "bird_arcwise", "ambrosia", "clambsql"):
        try:
            golds = load_golds(ds)
        except SystemExit:
            continue
        for gold in golds:
            out.setdefault(gold.id, gold)
    return out


def get_target_gold(qid: str) -> str:
    """Return the official gold SQL for this question id, or empty string."""
    row = _choice_table().get(qid) or {}
    sql = str(row.get("sql") or "")
    if sql:
        return sql
    gold = _repo_golds().get(qid)
    if gold is None:
        return ""
    sqls = [s for s in (getattr(gold, "gold_sqls", None) or []) if s]
    intended = (getattr(gold, "meta", None) or {}).get("intended")
    if intended is not None and sqls:
        try:
            idx = int(intended)
        except (TypeError, ValueError):
            idx = 0
        if 0 <= idx < len(sqls):
            return str(sqls[idx] or "")
    return str(getattr(gold, "gold_sql", None) or (sqls[0] if sqls else "") or "")
