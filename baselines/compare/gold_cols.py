"""读 raw/<dataset>/extracted/gold_table_columns.jsonl，给 Hybrid Human 当 gold keys。"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

# Official CLEAR/AmbiSQL runs use pick_mapping_08, not Hybrid gold keys.
# Keep the loader so common.py can import keys_for; missing files yield {}.
RAW = Path(__file__).resolve().parents[2] / "dataset"

_ALIAS = {
    "bird": "bird_arcwise",
    "bird_arcwise": "bird_arcwise",
    "bird1534": "bird_arcwise",
    "clambsql": "clambsql",
    "ambrosia": "ambrosia",
    "electricity": "electricity",
}


@lru_cache(maxsize=8)
def load_gold_table_columns(dataset: str) -> dict[str, set[str]]:
    folder = _ALIAS.get(dataset, dataset)
    path = RAW / folder / "extracted" / "gold_table_columns.jsonl"
    out: dict[str, set[str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        keys = rec.get("keys_all_sqls") or rec.get("keys") or []
        out[str(rec.get("id"))] = {str(k).strip().lower() for k in keys if k and "." in str(k)}
    return out


def keys_for(dataset: str, item_id: str) -> set[str]:
    return set(load_gold_table_columns(dataset).get(item_id) or [])
