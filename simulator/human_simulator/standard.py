"""08 人模拟：选项标准化、解析，以及人选结果结构（PickResult / TokenPick）。"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_LABEL = re.compile(r"\[\d+\]|\[Others\]|Others")

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "08_human_agent.txt"


@dataclass
class TokenPick:
    token: str
    kind: str  # schema | nl
    pick_type: int  # 0 hit, 1 merge, 2 abstain
    chosen: Any = None
    abstain: bool = False
    source: str = ""
    ambig_type: str = ""
    interpretation: str = ""
    clarification_question: str = ""


@dataclass
class PickResult:
    simulator: str
    tokens: list[TokenPick] = field(default_factory=list)
    ambiguity_clarification: dict[str, Any] = field(default_factory=dict)
    msg: dict[str, Any] = field(default_factory=dict)
    asks: list = field(default_factory=list)

    def chosen_map(self) -> dict[str, Any]:
        return dict(self.ambiguity_clarification)


def parse_ambiguity_map(raw: Any) -> Any:
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = raw.strip()
        return json.loads(raw) if raw else {}
    if isinstance(raw, dict) and "query" in raw and "match" in raw:
        q, m = raw["query"], raw["match"]
        return {
            "query": json.loads(q) if isinstance(q, str) else (q or {}),
            "match": json.loads(m) if isinstance(m, str) else (m or {}),
        }
    return raw


def as_query_match(mapping: Any) -> tuple[dict, dict]:
    parsed = parse_ambiguity_map(mapping)
    if not isinstance(parsed, dict):
        return {}, {}
    if "query" in parsed or "match" in parsed:
        q, m = parsed.get("query") or {}, parsed.get("match") or {}
        if isinstance(q, str):
            q = parse_ambiguity_map(q)
        if isinstance(m, str):
            m = parse_ambiguity_map(m)
        return q or {}, m or {}
    return {}, parsed


def _active_prompt_path() -> Path:
    env = (os.environ.get("PAPER_EXP_08_PROMPT") or "").strip()
    return Path(env) if env else PROMPT_PATH


def _active_include_others(override: Optional[bool]) -> bool:
    if override is not None:
        return override
    return os.environ.get("PAPER_EXP_08_OTHERS", "1") != "0"


def format_options_to_standard(raw_options: list, include_others: bool = True) -> tuple[str, dict]:
    """任意系统选项铺成 [1] ...；默认再加 [Others]。"""
    formatted_lines: list[str] = []
    index_map: dict[str, Any] = {}
    for i, opt in enumerate(raw_options or [], start=1):
        key = f"[{i}]"
        if isinstance(opt, dict):
            text = opt.get("text", opt.get("desc", str(opt)))
            raw_id = opt.get("raw_id", opt.get("option_id", key))
        else:
            text = str(opt)
            raw_id = key
        formatted_lines.append(f"{key} {text}")
        index_map[key] = raw_id
    if include_others:
        formatted_lines.append("[Others] None of the above")
        index_map["Others"] = "Others"
        index_map["[Others]"] = "Others"
    return "\n".join(formatted_lines), index_map


def _load_selected(llm_output: str) -> str:
    text = (llm_output or "").strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(data, dict):
        return str(data.get("selected_labels", "Others")).strip()
    return "Others"


def parse_simulator_response(llm_output: str, index_map: dict, system_name: str):
    """解析 selected_labels，映射回 CLEAR / AmbiSQL / Ours 原生格式。"""
    selected_str = _load_selected(llm_output)
    matched_keys = _LABEL.findall(selected_str)
    hit_others = any(k in ("Others", "[Others]") for k in matched_keys)
    if not matched_keys or hit_others:
        return "Others" if system_name != "clear" else "[Others]"
    if system_name == "clear":
        return selected_str
    if system_name == "ambisql":
        return [str(re.search(r"\d+", k).group()) for k in matched_keys]
    return [index_map[k] for k in matched_keys if k in index_map]


def format_human_prompt(
    *,
    question: str,
    schema: str,
    gold_sql: str,
    evidence: str,
    raw_options: list,
    include_others: Optional[bool] = None,
    prompt_path: Path | None = None,
) -> tuple[str, dict]:
    options_text, index_map = format_options_to_standard(
        raw_options, include_others=_active_include_others(include_others)
    )
    body = (prompt_path or _active_prompt_path()).read_text(encoding="utf-8")
    i = body.find("# Role")
    body = body[i:].strip() if i >= 0 else body.strip()
    slots = {
        "question": question or "",
        "schema": schema or "NULL",
        "gold_sql": gold_sql or "NULL",
        "evidence": evidence or "NULL",
        "standardized_options": options_text,
    }
    for key, val in slots.items():
        body = body.replace("{" + key + "}", str(val))
    return body, index_map


def _merge_chosen(selected: Any) -> Any:
    if not isinstance(selected, list):
        return selected
    if len(selected) == 1:
        return selected[0]
    if selected and all(isinstance(x, dict) for x in selected):
        out: dict[str, list] = {}
        for d in selected:
            for table, cols in d.items():
                bucket = out.setdefault(str(table), [])
                if isinstance(cols, list):
                    seq = cols
                elif cols is None:
                    seq = []
                else:
                    seq = [cols]
                for col in seq:
                    if col not in bucket:
                        bucket.append(col)
        return out
    return selected
