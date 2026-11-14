"""三系统选项 → 统一 [1]/[2]/[Others]；解析后再还原原生标记。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
_LABEL = re.compile(r"\[\d+\]|\[Others\]|Others")

PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "prompts_review" / "08_human_agent.txt"
)


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


def _opt_text(opt: Any) -> str:
    if isinstance(opt, dict) and "text" in opt:
        return str(opt["text"])
    if isinstance(opt, (dict, list)):
        return json.dumps(opt, ensure_ascii=False)
    return str(opt)


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


def pick_mapping_08(gold, mapping: dict, ctx) -> "PickResult":
    """CLEAR/AmbiSQL mapping → 08 标准化点选。"""
    from .official_clear import PickResult, TokenPick, as_query_match
    from ..schema_text import schema_clear_text, schema_map_for_prompt

    query, match = as_query_match(mapping)
    schema = schema_clear_text(schema_map_for_prompt(gold))
    gold_sql = gold.gold_sql or (gold.all_gold_sqls()[0] if gold.all_gold_sqls() else "NULL")
    ev = str((gold.meta or {}).get("evidence") or "") or "NULL"
    tokens: list = []
    clarification: dict = {}
    asks: list = []
    llm = getattr(ctx, "llm", None)
    leftover = getattr(ctx, "_ask_leftover", None)
    if leftover is None:
        leftover = getattr(ctx, "budget_k", None)
        if leftover is not None:
            leftover = max(0, int(leftover))
    if llm is None or getattr(ctx, "dry_run", False):
        return PickResult(simulator="human_08")
    for token, options, kind in (
        *[(t, opts, "nl") for t, opts in (query or {}).items()],
        *[(t, opts, "schema") for t, opts in (match or {}).items()],
    ):
        opts = list(options or [])
        if not opts:
            continue
        if leftover is not None and int(leftover) <= 0:
            break
        raw_opts = [{"text": _opt_text(o), "raw_id": o} for o in opts]
        prompt, index_map = format_human_prompt(
            question=gold.question,
            schema=schema,
            gold_sql=gold_sql or "NULL",
            evidence=ev,
            raw_options=raw_opts,
        )
        selected = parse_simulator_response(llm.complete(prompt), index_map, "ours")
        if selected in ("Others", "[Others]") or selected == ["Others"]:
            tokens.append(TokenPick(token, kind, 2, None, True, "human_08"))
            asks.append({
                "span": token,
                "kind": kind,
                "question": token,
                "options": opts,
                "chosen": None,
                "abstain": True,
                "pick_type": 2,
            })
        else:
            chosen = _merge_chosen(selected)
            tokens.append(TokenPick(token, kind, 0, chosen, False, "human_08"))
            clarification[token] = chosen
            asks.append({
                "span": token,
                "kind": kind,
                "question": token,
                "options": opts,
                "chosen": chosen,
                "abstain": False,
                "pick_type": 0,
            })
        if leftover is not None:
            leftover = int(leftover) - 1
    if leftover is not None:
        ctx._ask_leftover = leftover
    return PickResult(
        simulator="human_08", tokens=tokens, ambiguity_clarification=clarification, asks=asks,
    )
