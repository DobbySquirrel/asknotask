"""--parser {base,deepeye}：同一 DetectResult，只换生成 prompt。"""
from __future__ import annotations

from .contract import DetectResult
from utils.llm import parse_sql
from .sql_parser_base import format_parser_base
from .sql_parser_deepeye import format_parser_deepeye, merge_deepeye_hint


def build_parser_prompt(kind: str, det: DetectResult) -> str:
    kind = (kind or "base").strip().lower()
    if kind == "base":
        return format_parser_base(det.schema_out, det.question_out, det.evidence_out)
    if kind == "deepeye":
        hint = merge_deepeye_hint(det.evidence_out, det.clarification)
        return format_parser_deepeye(det.schema_out, det.question_out, hint)
    raise ValueError(f"unknown parser {kind!r}; use base|deepeye")


def run_parser(kind: str, det: DetectResult, llm) -> str:
    return parse_sql(llm.complete(build_parser_prompt(kind, det)))
