"""gpt-5.6-terra 解析：PROMPT_BASE + 证据中的中文 soft NOTE。

NOTE / insert_note 原样来自
`runs/exp/20261030_jev_abc/deepeye_official_soft/insert_note.py`
（terra_bird/*_soft_run、gate_soft_run、train1_other_run 同句）。
prompt 本体仍走 sql_parser_base / qwen_coder 的 format_parser_base。
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from qwen_coder import PROMPT_BASE, format_parser_base  # noqa: E402

NOTE = (
    "下面是用户的问题澄清（可能会模糊）。"
    "NL 和 evidence 是用户的事实（非常确定），"
    "evidence_out 是用户的交互结果（可能会模糊）。"
)


def insert_note(text: str) -> str:
    text = text or ""
    if "User clarification:" not in text or NOTE in text:
        return text
    fact, clar = text.split("User clarification:", 1)
    parts = [p for p in (fact.strip(), NOTE, "User clarification:" + clar) if p]
    return "\n".join(parts)


def format_parser_terra(schema_with_content: str, question: str, evidence: str = "") -> str:
    """与 ABC terra soft 一致：先插 NOTE，再套 PROMPT_BASE。"""
    return format_parser_base(schema_with_content, question, insert_note(evidence))


format_parser_gpt56 = format_parser_terra

__all__ = [
    "NOTE",
    "PROMPT_BASE",
    "insert_note",
    "format_parser_base",
    "format_parser_terra",
    "format_parser_gpt56",
]
