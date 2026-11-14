"""卡片 ID：题号、该题 asks 列表中的下标、类型、span。

asks 里检测器自动写入的卡也占下标。若仍重复，unique_ids 在末尾加 #序号。
"""
from __future__ import annotations


def card_id(qid: str, ask_index: int, kind: str, span: str) -> str:
    return f"{qid}|{ask_index}|{kind}|{span}"


def unique_ids(raw_ids: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for raw in raw_ids:
        n = seen.get(raw, 0)
        seen[raw] = n + 1
        out.append(raw if n == 0 else f"{raw}#{n}")
    return out
