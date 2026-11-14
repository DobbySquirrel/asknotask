"""AmbiSQL 检出后：CQ 选项改写、Preference 树、type-2 再检。不改 repos/AmbiSQL。"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

_AMBI = Path(__file__).resolve().parents[2] / "repos" / "AmbiSQL"
if str(_AMBI) not in sys.path:
    sys.path.insert(0, str(_AMBI))


def parse_json_list(text: str) -> list:
    raw = text or ""
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    match = re.search(r"\[.*\]", raw, flags=re.S)
    if not match:
        return []
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return obj if isinstance(obj, list) else []


def parse_table_col(text: str, schema_map: Optional[dict[str, list[str]]] = None) -> Optional[dict]:
    """Detect 示例是 column::table；instruction 写 table::column。对照 schema 二选一。"""
    s = (text or "").strip()
    if not s:
        return None
    head = s.split(",", 1)[0].split(" representing", 1)[0].strip()
    m = re.search(r"([A-Za-z_][\w]*)::([A-Za-z_][\w]*)", head)
    if not m:
        m = re.search(r"([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)", head)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    smap = schema_map or {}
    if a in smap and b in (smap.get(a) or []):
        return {a: [b]}
    if b in smap and a in (smap.get(b) or []):
        return {b: [a]}
    if a in smap:
        return {a: [b]}
    if b in smap:
        return {b: [a]}
    return {a: [b]}


def item_options(item: dict) -> list[str]:
    if not isinstance(item, dict):
        return []
    choices = item.get("choices")
    if isinstance(choices, list) and choices:
        return [str(x) for x in choices]
    desc = item.get("description")
    if isinstance(desc, dict):
        return [str(x) for x in (desc.get("options") or [])]
    if isinstance(desc, list):
        return [str(x) for x in desc]
    if isinstance(desc, str) and desc.strip():
        return [desc]
    return []


def question_set_to_mapping(q_set: list, schema_map: Optional[dict[str, list[str]]] = None) -> dict[str, Any]:
    query: dict[str, list] = {}
    match: dict[str, list] = {}
    for i, item in enumerate(q_set or []):
        if not isinstance(item, dict):
            continue
        token = str(item.get("question") or item.get("level_2_label") or f"cq_{i}")
        schema_opts, nl_opts = [], []
        for opt in item_options(item):
            if str(opt).strip().lower() in {"abstain", "others"}:
                nl_opts.append(opt)
                continue
            td = parse_table_col(opt, schema_map)
            if td:
                schema_opts.append(td)
            else:
                nl_opts.append(opt)
        if schema_opts:
            match[token] = schema_opts
        if nl_opts:
            query[token] = nl_opts
    return {"query": query, "match": match}


def rewrite_choices(llm, parse_json, q_set: list) -> list:
    from ambisql.prompts.cq_generation_prompt import CQ_Generation_prompt, CQ_Template_prompt

    out = []
    for item in q_set or []:
        rec = dict(item) if isinstance(item, dict) else {}
        desc = rec.get("description")
        if isinstance(desc, dict):
            desc_str = json.dumps(desc, ensure_ascii=False, indent=2)
        elif desc is None:
            desc_str = ""
        else:
            desc_str = str(desc)
        prompt = CQ_Generation_prompt.format(
            question=rec.get("question") or "",
            description=desc_str,
            templates=CQ_Template_prompt,
        )
        parsed = parse_json(llm.complete(prompt)) if llm is not None else {}
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        rec["choices"] = [str(c) for c in choices] if isinstance(choices, list) else []
        out.append(rec)
    return out


def answer_of(tok) -> str:
    if getattr(tok, "abstain", False):
        return "Abstain"
    chosen = getattr(tok, "chosen", None)
    if isinstance(chosen, dict):
        parts = []
        for table, cols in chosen.items():
            if isinstance(cols, str):
                cols = [cols]
            for c in cols or []:
                parts.append(f"{table}.{c}")
        return " and ".join(parts) if parts else json.dumps(chosen, ensure_ascii=False)
    return str(chosen) if chosen is not None else "Abstain"


class PreferenceTree:
    def __init__(self) -> None:
        self.leaves: dict[tuple[str, str], list[dict]] = defaultdict(list)

    def add(self, level1: str, level2: str, question: str, answer: str, llm, parse_json) -> None:
        key = (str(level1 or ""), str(level2 or ""))
        pair = {"question": question, "answer": answer}
        if not self.leaves[key]:
            self.leaves[key].append(pair)
            return
        from ambisql.prompts.preference_tree_prompt import NodeMerge_prompt

        prompt = NodeMerge_prompt.format(
            old_list=json.dumps(self.leaves[key], ensure_ascii=False, indent=2),
            new_pair=json.dumps(pair, ensure_ascii=False, indent=2),
        )
        merged = parse_json_list(llm.complete(prompt)) if llm is not None else []
        if merged and all(isinstance(x, dict) for x in merged):
            self.leaves[key] = merged
        else:
            self.leaves[key].append(pair)

    def ingest_pick(self, q_set: list, pick, llm, parse_json) -> None:
        if not pick:
            return
        by_q = {str(it.get("question") or ""): it for it in (q_set or []) if isinstance(it, dict)}
        for tok in pick.tokens:
            item = by_q.get(tok.token) or {}
            self.add(
                item.get("level_1_label") or "Database-sourced ambiguity",
                item.get("level_2_label") or "AmbiSchema",
                tok.token,
                answer_of(tok),
                llm,
                parse_json,
            )

    def traverse(self) -> str:
        if not self.leaves:
            return ""
        lines = ["root"]
        grouped: dict[str, dict[str, list]] = {}
        for (l1, l2), qas in self.leaves.items():
            grouped.setdefault(l1, {})[l2] = qas
        for l1, kids in grouped.items():
            lines.append(f"  {l1}")
            for l2, qas in kids.items():
                lines.append(f"    {l2}")
                for qa in qas:
                    lines.append(f"      Q: {qa.get('question')} | A: {qa.get('answer')}")
        return "\n".join(lines)


def refine_question(llm, question: str, additional_info: str) -> str:
    from ambisql.prompts.ambiguity_detection_prompt import QuestionRefine_prompt

    if not additional_info or not str(additional_info).strip() or llm is None:
        return question
    prompt = QuestionRefine_prompt.format(question=question, additional_info=additional_info)
    return (llm.complete(prompt) or question).strip() or question
