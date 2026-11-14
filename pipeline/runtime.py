"""检出运行上下文（不依赖外部 compare.runner）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from utils.llm import parse_json_obj


@dataclass
class RunContext:
    llm: Any
    rewrite_mode: Optional[str]
    no_qc: bool = False
    parser: str = "base"

    def parse_json(self, text: str) -> dict:
        return parse_json_obj(text)


def pred_row(gold, det, sql: Optional[str], parser: str) -> dict[str, Any]:
    row = det.to_pred_fields()
    row["predicted_sql"] = sql
    row["parser"] = parser
    row["db_id"] = gold.db_id
    return row
