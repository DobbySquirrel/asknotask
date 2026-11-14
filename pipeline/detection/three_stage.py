# SOURCE: see pipeline/SOURCE.md
"""Ours 1-BC 完全体：三阶段检出 → QC → 改写。Check（Difference / Existence / Relevance）不在检测里跑。"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import Any, Optional

_ASK = Path(__file__).resolve().parents[2]
if str(_ASK) not in sys.path:
    sys.path.insert(0, str(_ASK))

from simulator.compose import apply_rewrite, render_mapping_snippet
from simulator.compose import DEFAULT_REWRITE, DetectResult
from schema_text import schema_clear_text, schema_map_for_prompt, schema_numbered_rich
from simulator.human_simulator.standard import PickResult, TokenPick
from simulator.human_simulator.standard import format_human_prompt, parse_simulator_response

from .common import chosen_columns, chosen_pivots, gold_evidence, interact_meta, parse_qc_json, pick_as_dict

REVIEW = Path(__file__).resolve().parent / "prompts"
STAGE_FILES = (
    "06b1_ours_detect_1bc_s1.md",
    "06b2_ours_detect_1bc_s2.md",
    "06b3_ours_detect_1bc_s3.md",
)

def _fill(name: str, folder: Path | None = None, **slots: str) -> str:
    text = ((folder or REVIEW) / name).read_text(encoding="utf-8")
    i = text.find("# Role")
    text = text[i:] if i >= 0 else text
    for key, val in slots.items():
        text = text.replace("{" + key + "}", val)
    return text

def _no_table() -> bool:
    return (os.environ.get("PAPER_EXP_NO_TABLE") or "").strip().lower() in {"1", "true", "yes"}

def _keep_both() -> bool:
    return (os.environ.get("PAPER_EXP_KEEP_BOTH") or "").strip().lower() in {"1", "true", "yes"}

def _stage1_fallback() -> str:
    """默认空类型填 Scope。PAPER_EXP_SCOPE_FALLBACK=column 时不再填 Scope。"""
    raw = (os.environ.get("PAPER_EXP_SCOPE_FALLBACK") or "").strip().lower()
    if raw in {"column", "none", "off"}:
        return "Column"
    return "Scope"

def _display_span(span: str) -> str:
    return str(span).split("\n[", 1)[0]

def _retain_both(phi_part: dict, types: dict, interps: dict, span_types: dict) -> None:
    """同一短语上后一阶段给出不同类型时，另留一张卡，不覆盖前一张。"""
    if not _keep_both():
        return
    for span, typ in list(types.items()):
        old = span_types.get(span)
        if not old or not typ or old == typ or span not in phi_part:
            continue
        key = f"{span}\n[{typ}]"
        phi_part[key] = phi_part.pop(span)
        types[key] = types.pop(span)
        if span in interps:
            interps[key] = interps.pop(span)

def _stage_files() -> tuple[str, ...]:
    files = list(STAGE_FILES)
    for i, env in enumerate(("PAPER_EXP_06B1", "PAPER_EXP_06B2", "PAPER_EXP_06B3")):
        override = (os.environ.get(env) or "").strip()
        if override:
            files[i] = override
    return tuple(files)

def _stage_fill(ctx, stage_i: int, **slots: str) -> str:
    # 选定版本不接 RAG。提示词槽保持和空检索时一样，写成 (none)。
    _ = ctx, stage_i
    slots = {**slots, "retrieved_json": "(none)"}
    return _fill(_stage_files()[stage_i], **slots)

def _canon(x: Any) -> str:
    if isinstance(x, (dict, list)):
        return json.dumps(x, sort_keys=True, ensure_ascii=False)
    return str(x)

_CAND_META = {
    "attached_evidence", "evidence_id", "support_rationale", "source_snippet",
    "history", "fact_id", "score", "query_span", "supports",
}

def _bare_candidate(c: Any) -> Any:
    """08 只用 mapping；挂在候选上的 attached_evidence 不进改写。"""
    if not isinstance(c, dict):
        return c
    if "gold_mapping" in c:
        return c.get("gold_mapping")
    stripped = {k: v for k, v in c.items() if k not in _CAND_META}
    return stripped if stripped else c

def parse_phi(raw: Any) -> tuple[dict[str, list], dict[str, str], dict[str, str]]:
    """span → candidates，外加可选 type / interpretation。兼容旧 `{span: [cands]}`。"""
    if isinstance(raw, list):
        folded: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict) and item.get("nl_span"):
                folded[str(item["nl_span"])] = item
        raw = folded
    if not isinstance(raw, dict):
        return {}, {}, {}
    phi: dict[str, list] = {}
    types: dict[str, str] = {}
    interps: dict[str, str] = {}
    for k, v in raw.items():
        span = str(k)
        ambig_type = ""
        interp = ""
        cands = None
        if isinstance(v, dict) and ("candidates" in v or "options" in v):
            ambig_type = str(v.get("type") or v.get("ambig_type") or "").strip()
            interp = str(v.get("interpretation") or "").strip()
            cands = v.get("candidates")
            if cands is None:
                cands = v.get("options")
        elif isinstance(v, list):
            cands = v
        elif v is not None:
            cands = [v]
        if cands is None:
            continue
        if not isinstance(cands, list):
            cands = [cands]
        phi[span] = [_bare_candidate(c) for c in cands]
        if ambig_type == "Table" and _no_table():
            ambig_type = "Column"
        if ambig_type:
            types[span] = ambig_type
        if interp:
            interps[span] = interp
    return phi, types, interps

CLASSIFY_TO_TAXONOMY = {
    "s1": "Scope",
    "schema": "Column",
    "value": "Value",
    "null": "NULL",
    "tie": "Tie",
    "agg_project": "Aggregate",
}

def infer_missing_types(
    phi: dict,
    types: dict[str, str],
    phi1: dict,
    phi2: dict,
    phi3: dict,
    smap: dict,
    fallback: str = "",
) -> dict[str, str]:
    for span, cands in (phi or {}).items():
        if str(types.get(span) or "").strip():
            continue
        kind = classify_span(span, cands, phi1, phi2, phi3, smap)
        types[span] = CLASSIFY_TO_TAXONOMY.get(kind) or fallback or "Column"
    return types

def phi_with_types(
    phi: dict,
    types: dict[str, str],
    interps: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    interps = interps or {}
    out: dict[str, Any] = {}
    for span, cands in (phi or {}).items():
        rec: dict[str, Any] = {"candidates": list(cands)}
        if types.get(span):
            rec["type"] = types[span]
        if interps.get(span):
            rec["interpretation"] = interps[span]
        out[span] = rec
    return out

def union_phi(*parts: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for part in parts:
        for k, v in (part or {}).items():
            if k not in out:
                out[k] = list(v)
    return out

def _merge_earliest(dst: dict, src: dict) -> None:
    """同一短语已经有类型或解释时，保留较早阶段的，不让后一阶段覆盖。"""
    for key, value in (src or {}).items():
        if key not in dst and value:
            dst[key] = value

_SCOPE_XY = """找出问题里的范围短语。短语必须是 each、every、all、for each、for every 后面跟着实体 X。Y 是问题在问的、和 X 相关的那个东西，只能从问题原文里抄，不要用别的来源。
没有这种短语就让三个字段都空。只返回 JSON。
问题：{question}
{{"span": "", "x": "", "y": ""}}"""
_SCOPE_RE = re.compile(
    r"\b(?:for each|for every|each|every|all)\b\s+((?:[A-Za-z0-9_'-]+\s+){0,3}[A-Za-z0-9_'-]+)",
    re.I,
)

def _scope_xy(llm, question: str) -> dict:
    from utils.llm import parse_json_obj

    raw = llm.complete(_SCOPE_XY.format(question=question))
    obj = parse_json_obj(raw) or {}
    x = str(obj.get("x") or "").strip()
    y = str(obj.get("y") or "").strip()
    span = str(obj.get("span") or "").strip()
    if not x:
        match = _SCOPE_RE.search(question or "")
        if match:
            span = span or match.group(0)
            x = match.group(1)
    return {"span": span, "x": x, "y": y}

def _apply_scope_templates(llm, question: str, phi1: dict, span_types: dict) -> set[str]:
    """有 Scope 卡且抽得出 X 时，换成三条共用读法。抽不出 X 则保留原候选。"""
    locked = set()
    for span in list(phi1):
        if str(span_types.get(span) or "") != "Scope":
            continue
        found = _scope_xy(llm, question)
        if not found.get("x"):
            continue
        x = found["x"]
        y = found.get("y") or "result"
        plural = x if x.lower().endswith("s") else x + "s"
        phi1[span] = [
            f'For "{span}" in the question: for each {x}, list its own {y}.',
            f'For "{span}" in the question: for each {y}, count the distinct {plural} related to it, and keep the {y} only if this count equals the total number of {plural}.',
            f'For "{span}" in the question: list the {y} of all {plural} together.',
        ]
        locked.add(span)
    return locked

def phi_to_mapping(phi: dict[str, list]) -> dict[str, dict]:
    query: dict[str, list] = {}
    match: dict[str, list] = {}
    for span, cands in (phi or {}).items():
        if cands and all(isinstance(c, str) for c in cands):
            query[span] = list(cands)
        else:
            match[span] = list(cands)
    return {"query": query, "match": match}

def _kind(cands: list) -> str:
    return "nl" if cands and all(isinstance(c, str) for c in cands) else "schema"

def _looks_like_expr(val: str) -> bool:
    s = str(val or "")
    return any(tok in s for tok in ("<", ">", "*", "/", "+", "COUNT", "CAST", " = ", "<=", ">="))

def _resolve_table(name: str, smap: dict[str, list[str]]) -> Optional[str]:
    key = (name or "").strip().lower()
    for t in smap or {}:
        if t.lower() == key:
            return t
    return None

def _resolve_col(table: str, col: str, smap: dict[str, list[str]]) -> Optional[str]:
    key = (col or "").strip().lower()
    for c in smap.get(table) or []:
        if c.lower() == key:
            return c
    return None

def _split_table_col(key: str, smap: dict[str, list[str]]) -> tuple[Optional[str], Optional[str]]:
    raw = (key or "").strip()
    if not raw:
        return None, None
    hit = _resolve_table(raw, smap)
    if hit:
        return hit, None
    best: Optional[tuple[str, str]] = None
    for table in smap or {}:
        prefix = table + "."
        if raw.lower().startswith(prefix.lower()):
            rest = raw[len(table) + 1 :]
            if best is None or len(table) > len(best[0]):
                best = (table, rest)
    if not best:
        return None, None
    table, rest = best
    return table, _resolve_col(table, rest, smap)

NULL_LITS = {"EXCLUDE_NULL", "KEEP_NULL"}

def _is_tie_lit(val: Any) -> bool:
    s = str(val or "").strip().upper()
    return s == "MAX" or s.startswith("LIMIT")

def _is_instance_literal(
    table: Optional[str],
    col: Optional[str],
    val: Any,
    smap: dict[str, list[str]],
) -> bool:
    """Value 字面量：单元格取值。列名、公式不算。"""
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s or s in NULL_LITS or _is_tie_lit(s) or _looks_like_expr(s):
        return False
    if col and s.lower() == str(col).lower():
        return False
    for c in smap.get(table) or []:
        if s.lower() == c.lower():
            return False
    return True

def classify_span(
    span: str,
    cands: list,
    phi1: dict,
    phi2: dict,
    phi3: dict,
    smap: dict[str, list[str]],
) -> str:
    in1, in2, in3 = span in phi1, span in phi2, span in phi3
    nullish = tieish = valuish = False
    for cand in cands or []:
        if not isinstance(cand, dict):
            continue
        for k, v in cand.items():
            table, col = _split_table_col(str(k), smap)
            if isinstance(v, str):
                if v in NULL_LITS:
                    nullish = True
                elif _is_tie_lit(v):
                    tieish = True
                elif _is_instance_literal(table, col, v, smap):
                    valuish = True
    if tieish:
        return "tie"
    # S3 是 Aggregate/Project/Tie；公式写成 {table.col:"colname"} 也不能当 Value
    if in3:
        return "agg_project"
    if nullish:
        return "null"
    if valuish:
        return "value"
    if in1 and not in2 and not in3:
        return "s1"
    return "schema"

def _raw_choices(cands: list) -> list[dict]:
    return [{"desc": str(c), "elements": [c]} for c in cands]

def _interp_for_choice(card: dict, selected: Any, chosen: Any) -> str:
    sel = selected if isinstance(selected, list) else [selected]
    for i, choice in enumerate(card.get("choices") or []):
        if not isinstance(choice, dict):
            continue
        raw_id = card["cands"][i] if i < len(card.get("cands") or []) else choice.get("elements")
        if any(_canon(raw_id) == _canon(s) for s in sel if s is not None):
            return str(choice.get("interpretation") or choice.get("desc") or "")
    detect_interp = str(card.get("interpretation") or "")
    if detect_interp:
        return detect_interp
    ambig_type = str(card.get("ambig_type") or "")
    snippet = render_mapping_snippet(ambig_type, chosen)
    if ambig_type:
        return f"Confirmed {ambig_type} mapping: {snippet}"
    return str(snippet)

def _mk_token(
    span: str,
    cands: list,
    pick_type: int,
    chosen: Any,
    abstain: bool,
    source: str,
    *,
    card: Optional[dict] = None,
    span_types: Optional[dict[str, str]] = None,
    span_interps: Optional[dict[str, str]] = None,
    selected: Any = None,
) -> TokenPick:
    types = span_types or {}
    interps = span_interps or {}
    ambig_type = str((card or {}).get("ambig_type") or types.get(span) or "")
    detect_interp = str((card or {}).get("interpretation") or interps.get(span) or "")
    interp = ""
    if not abstain:
        if card:
            interp = _interp_for_choice(card, selected, chosen) or detect_interp
        else:
            snippet = render_mapping_snippet(ambig_type, chosen)
            interp = detect_interp or (
                f"Confirmed {ambig_type} mapping: {snippet}" if ambig_type else f"Confirmed mapping: {snippet}"
            )
    qc = (card or {}).get("qc") if isinstance((card or {}).get("qc"), dict) else {}
    q = str((qc or {}).get("clarification_question") or (card or {}).get("clarification_question") or "")
    return TokenPick(
        span, _kind(cands if isinstance(cands, list) else [cands]),
        pick_type, chosen, abstain, source,
        ambig_type=ambig_type, interpretation=interp,
        clarification_question=q,
    )

def _qc_cards(
    llm, q: str, phi_part: dict, batch_id: int, healed: dict,
    no_qc: bool = False, span_types: Optional[dict[str, str]] = None,
    span_interps: Optional[dict[str, str]] = None,
    locked: Optional[set[str]] = None,
    schema_content: str = "",
    evidence: str = "",
) -> tuple[list[dict], int]:
    cards: list[dict[str, Any]] = []
    n_qc = 0
    span_types = span_types or {}
    span_interps = span_interps or {}
    for span, cands in (phi_part or {}).items():
        if span in healed or len(cands) < 2:
            continue
        shown = _display_span(span)
        ambig_type = str(span_types.get(span) or "")
        detect_interp = str(span_interps.get(span) or "")
        if no_qc or span in (locked or set()):
            choices = _raw_choices(cands)
            qc = {"clarification_question": span, "choices": choices, "skipped_qc": True}
        else:
            # 06c 失败时回退 raw choices，禁止静默丢卡（否则 Forward 全问 / checks 丢卡 → EX 反号）
            qc = None
            choices: list = []
            try:
                qc = parse_qc_json(llm.complete(_fill(
                    "06c_ours_qc_1bc.md",
                    schema_content=schema_content or "(none)",
                    question=q,
                    evidence=evidence or "NULL",
                    span=shown,
                    ambig_type=ambig_type or "unknown",
                    detect_interpretation=detect_interp or "(none)",
                    surviving_candidates_json=json.dumps(cands, ensure_ascii=False, indent=2),
                )))
                choices = [c for c in (qc.get("choices") or []) if isinstance(c, dict)]
            except (ValueError, json.JSONDecodeError, TypeError, AttributeError):
                choices = []
            if len(choices) < 2:
                choices = _raw_choices(cands)
                qc = {
                    "clarification_question": shown,
                    "choices": choices,
                    "skipped_qc": True,
                    "qc_fallback": "raw_after_06c_fail",
                }
            else:
                n_qc += 1
        qc_interp = str((qc or {}).get("interpretation") or detect_interp)
        cards.append({
            "span": shown,
            "_phi_key": span,
            "cands": cands,
            "qc": qc,
            "choices": choices,
            "batch": batch_id,
            "ambig_type": ambig_type,
            "interpretation": qc_interp,
        })
    return cards, n_qc

def _exec_preview(sql: str, db: str) -> tuple[str, str]:
    """返回 (预览, 错误)。超时不算错误。"""
    if not sql or not db:
        return "没有返回结果", ""
    import sqlite3
    import time
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    conn.execute("PRAGMA query_only=ON")
    deadline = time.time() + 15
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10_000)
    timed_out = False
    try:
        cur = conn.execute(sql)
        rows = cur.fetchall()
    except Exception as exc:
        if "interrupted" in str(exc).lower() or time.time() > deadline:
            timed_out = True
            rows = []
        else:
            return "没有返回结果", str(exc)
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()
    if timed_out:
        return "返回很多行", ""
    vals, seen = [], set()
    for row in rows:
        if not row or row[0] is None:
            continue
        text = str(row[0])
        if text in seen:
            continue
        seen.add(text)
        vals.append(text)
        if len(vals) == 3:
            break
    if not vals:
        return f"返回 {len(rows)} 行", ""
    return f"返回 {len(rows)} 行，例如 {'、'.join(vals)}", ""

def _repair_sql_once(llm, schema: str, sql: str, error: str) -> str:
    """执行失败时把报错、SQL 和 schema_numbered_rich 交回模型，只改一次。"""
    from utils.llm import parse_sql

    prompt = (
        "The SQL failed to execute. Fix it once using only tables and columns from the schema.\n"
        "Reply with only the corrected SQL.\n\n"
        f"Schema:\n{schema}\n\n"
        f"SQL:\n{sql}\n\n"
        f"Error:\n{error}\n"
    )
    return parse_sql(llm.complete(prompt)) or ""

def _scope_user_options(llm, gold, evidence: str, raw_opts: list[dict], ambig_type: str) -> list[dict]:
    """Scope 的执行预览只出现在模拟用户看到的选项里。raw_id 仍是原读法。"""
    if ambig_type != "Scope":
        return raw_opts
    from utils.llm import parse_sql
    from parsers.sql_parser_base import format_parser_base

    schema = schema_numbered_rich(gold)
    ev = "" if not evidence or evidence == "NULL" else evidence
    db = gold.db_path or ""
    out = []
    for opt in raw_opts:
        text = str(opt.get("text") or "")
        body = "User clarification:\n" + text
        clar = f"{ev}\n{body}" if ev else body
        sql = parse_sql(llm.complete(format_parser_base(schema, gold.question, clar))) or ""
        preview, err = _exec_preview(sql, db)
        if err:
            fixed = _repair_sql_once(llm, schema, sql, err)
            if fixed and fixed.strip() != sql.strip():
                preview, _err2 = _exec_preview(fixed, db)
        out.append({**opt, "text": f"{text}。{preview}"})
    return out


def ask_stats(tokens, cards=None) -> dict[str, Any]:
    """Q 只计实际问人的卡；Auto 计入 n_auto。"""
    asked = [t for t in tokens if getattr(t, "source", "") == "human_08"]
    auto = [t for t in tokens if getattr(t, "source", "") == "scorer"]
    scored = bool(cards) and any(isinstance((c or {}).get("scorer"), dict) for c in cards)
    out: dict[str, Any] = {
        "n_asked": len(asked),
        "n_answered": sum(1 for t in asked if not getattr(t, "abstain", False)),
        "n_auto": len(auto),
        "scorer": scored,
    }
    if scored:
        thetas = [
            (c.get("scorer") or {}).get("theta")
            for c in (cards or [])
            if isinstance((c or {}).get("scorer"), dict)
        ]
        if thetas and thetas[0] is not None:
            out["theta_star"] = thetas[0]
    return out


def _ask_human_cards(
    gold, llm, cards: list[dict], q: str, schema_llm: str, ev: str,
    span_types: Optional[dict[str, str]] = None,
    span_interps: Optional[dict[str, str]] = None,
) -> tuple[list, dict]:
    """共用提问入口：可选 Auto/Ask，再走 08 模拟人。返回 (tokens, clarification)。"""
    from simulator.human_simulator.standard import _merge_chosen

    tokens: list[TokenPick] = []
    clarification: dict[str, Any] = {}
    gold_sql = gold.gold_sql or (gold.all_gold_sqls()[0] if gold.all_gold_sqls() else "NULL")
    auto_idx: set[int] = set()

    from pipeline.scorer.decide import enabled as _scorer_on
    if cards and _scorer_on():
        from pipeline.scorer.decide import apply_to_cards
        apply_to_cards(gold, cards, ev if ev != "NULL" else "")
        for i, card in enumerate(cards):
            info = card.get("scorer") or {}
            if not info.get("auto"):
                continue
            cands = list(card.get("cands") or [])
            top = int(info.get("top1") or 0)
            if not cands or not (0 <= top < len(cands)):
                choices = list(card.get("choices") or [])
                if not (0 <= top < len(choices)):
                    continue
                raw_id = choices[top].get("elements") if isinstance(choices[top], dict) else choices[top]
            else:
                raw_id = cands[top]
            selected = [raw_id]
            chosen = _merge_chosen(selected)
            tokens.append(_mk_token(
                card["span"], card["cands"], 0, chosen, False, "scorer",
                card=card, span_types=span_types, span_interps=span_interps, selected=selected,
            ))
            clarification[card["span"]] = chosen
            auto_idx.add(i)

    for i, card in enumerate(cards):
        if i in auto_idx:
            continue
        span = card["span"]
        raw_opts = []
        for j, choice in enumerate(card["choices"]):
            raw_id = card["cands"][j] if j < len(card["cands"]) else choice.get("elements")
            raw_opts.append({"text": choice.get("desc") or str(raw_id), "raw_id": raw_id})
        raw_opts = _scope_user_options(llm, gold, ev, raw_opts, str(card.get("ambig_type") or ""))
        prompt, index_map = format_human_prompt(
            question=q,
            schema=schema_llm,
            gold_sql=gold_sql or "NULL",
            evidence=ev,
            raw_options=raw_opts,
        )
        selected = parse_simulator_response(llm.complete(prompt), index_map, "ours")
        if selected == "Others" or selected == ["Others"]:
            tokens.append(_mk_token(
                span, card["cands"], 2, None, True, "human_08",
                card=card, span_types=span_types, span_interps=span_interps,
            ))
            continue
        chosen = _merge_chosen(selected)
        tokens.append(_mk_token(
            span, card["cands"], 0, chosen, False, "human_08",
            card=card, span_types=span_types, span_interps=span_interps, selected=selected,
        ))
        clarification[span] = chosen
    return tokens, clarification

def _heal_unary(phi_part: dict, healed: dict) -> int:
    n = 0
    for span, cands in (phi_part or {}).items():
        if span not in healed and len(cands) == 1:
            healed[span] = cands[0]
            n += 1
    return n

def detect_ours_1bc(gold, ctx) -> DetectResult:
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = gold_evidence(gold) or "NULL"

    phi1: dict[str, list] = {}
    phi2: dict[str, list] = {}
    phi3: dict[str, list] = {}
    phi: dict[str, list] = {}
    scope_locked: set[str] = set()
    phi_prime: dict[str, list] = {}
    span_types: dict[str, str] = {}
    span_interps: dict[str, str] = {}
    n_healed = 0
    n_qc = 0

    llm = ctx.llm
    q = gold.question
    phi1, t1, i1 = parse_phi(ctx.parse_json(llm.complete(_stage_fill(
        ctx, 0,
        schema_content=schema_llm,
        question=q,
        evidence=ev,
    ))))
    span_types.update(t1)
    span_interps.update(i1)
    infer_missing_types(phi1, span_types, phi1, {}, {}, smap, fallback=_stage1_fallback())
    scope_locked = _apply_scope_templates(llm, q, phi1, span_types)
    prior_s1 = json.dumps(phi_with_types(phi1, span_types, span_interps), ensure_ascii=False, indent=2)
    phi2, t2, i2 = parse_phi(ctx.parse_json(llm.complete(_stage_fill(
        ctx, 1,
        schema_content=schema_llm,
        question=q,
        evidence=ev,
        prior_ambiguities_json=prior_s1,
        stage1_ambiguities_json=prior_s1,
    ))))
    _retain_both(phi2, t2, i2, span_types)
    _merge_earliest(span_types, t2)
    _merge_earliest(span_interps, i2)
    infer_missing_types(phi2, span_types, phi1, phi2, {}, smap, fallback="Column")
    prior = union_phi(phi1, phi2)
    phi3, t3, i3 = parse_phi(ctx.parse_json(llm.complete(_stage_fill(
        ctx, 2,
        schema_content=schema_llm,
        question=q,
        evidence=ev,
        prior_ambiguities_json=json.dumps(phi_with_types(prior, span_types, span_interps), ensure_ascii=False, indent=2),
    ))))
    _retain_both(phi3, t3, i3, span_types)
    _merge_earliest(span_types, t3)
    _merge_earliest(span_interps, i3)
    infer_missing_types(phi3, span_types, phi1, phi2, phi3, smap, fallback="Aggregate")
    phi = union_phi(phi1, phi2, phi3)
    phi_prime = {k: list(v) for k, v in phi.items()}
    healed: dict[str, Any] = {}
    if phi:
        infer_missing_types(phi_prime, span_types, phi1, phi2, phi3, smap)
        n_healed += _heal_unary(phi_prime, healed)

    no_qc = bool(getattr(ctx, "no_qc", False))
    infer_missing_types(phi_prime, span_types, phi1, phi2, phi3, smap)
    cards, n_more = _qc_cards(
        llm, q, phi_prime, 0, healed, no_qc=no_qc,
        span_types=span_types, span_interps=span_interps,
        locked=scope_locked,
        schema_content=schema_llm, evidence=ev,
    )
    n_qc += n_more
    for card in cards:
        card["batch"] = _batch_of(card["span"], phi1, phi2, phi3)

    return _ask_emit(gold, ctx, {
        "ask_cards": cards,
        "healed": healed,
        "n_qc": n_qc,
        "n_healed": n_healed,
        "qc_question": q,
        "phi": phi,
        "phi_prime": phi_prime,
        "span_types": span_types,
        "span_interps": span_interps,
        "batches": {"s1": phi1, "s2": phi2, "s3": phi3},
    })

def _ask_emit(gold, ctx, snap: dict[str, Any]) -> DetectResult:
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = gold_evidence(gold) or "NULL"
    mode = ctx.rewrite_mode or DEFAULT_REWRITE["ours_1bc"]
    llm = ctx.llm
    q = snap.get("qc_question") or gold.question
    cards = list(snap.get("ask_cards") or [])
    healed = dict(snap.get("healed") or {})
    n_qc = int(snap.get("n_qc") or 0)
    n_healed = int(snap.get("n_healed") or 0)
    phi = snap.get("phi") or {}
    phi_prime = snap.get("phi_prime") or {}
    span_types = dict(snap.get("span_types") or {})
    span_interps = dict(snap.get("span_interps") or {})
    batches = snap.get("batches") or {}

    ask: list[dict[str, Any]] = []
    for batch_id in (1, 2, 3):
        pool = [c for c in cards if c["batch"] == batch_id]
        if pool:
            ask.extend(pool)

    tokens: list[TokenPick] = []
    clarification: dict[str, Any] = {}
    for card in cards:
        if card.get("ambig_type"):
            span_types.setdefault(card["span"], card["ambig_type"])
        if card.get("interpretation"):
            span_interps.setdefault(card["span"], card["interpretation"])
    for span, cand in healed.items():
        tokens.append(_mk_token(
            span, [cand], 0, cand, False, "self_heal",
            span_types=span_types, span_interps=span_interps,
        ))
        clarification[span] = cand

    tokens_ask, clarification_ask = _ask_human_cards(
        gold, llm, ask, q, schema_llm, ev, span_types, span_interps,
    )
    tokens.extend(tokens_ask)
    clarification.update(clarification_ask)

    pick = PickResult(simulator="ours_1bc_08", tokens=tokens, ambiguity_clarification=clarification)
    mapping = phi_to_mapping(phi_prime)
    ev_for_parser = "" if ev == "NULL" else ev
    q_out, s_out, e_out = apply_rewrite(
        mode,
        question=q,
        schema_str=schema,
        schema_map=smap,
        mapping=mapping,
        pick=pick,
        evidence=ev_for_parser,
        schema_formatter=schema_clear_text,
        parser=str(getattr(ctx, "parser", "base") or "base"),
    )
    return _result(gold, mode, schema, q_out, s_out, e_out, mapping, pick, {
        "pipeline": "ours_1bc",
        "no_qc": bool(getattr(ctx, "no_qc", False)),
        "stages": {"s1": True, "s2": True, "s3": True},
        "n_committed": len(clarification),
        "n_healed": n_healed,
        "n_qc": n_qc,
        "n_asked_budget": len(ask),
        "ask_cards": cards,
        "healed": healed,
        "qc_question": q,
        "batches": batches,
        "span_types": span_types,
        "span_interps": span_interps,
        "phi": phi,
        "phi_prime": phi_prime,
        **interact_meta(PickResult(
            simulator="ours_1bc_08",
            tokens=[t for t in tokens if t.source == "human_08"],
        )),
        **ask_stats(tokens, ask),
    })

def _batch_of(span: str, a: dict, b: dict, c: dict) -> int:
    if span in a:
        return 1
    if span in b:
        return 2
    if span in c:
        return 3
    return 3

def _result(gold, mode, schema, q_out, s_out, e_out, mapping, pick, extra: dict) -> DetectResult:
    return DetectResult(
        id=gold.id,
        system="ours_1bc",
        rewrite_mode=mode,
        question_in=gold.question,
        schema_in=schema,
        question_out=q_out,
        schema_out=s_out,
        evidence_out=e_out,
        clarification=str(pick.chosen_map()) if pick else "",
        ambiguity_mapping=mapping,
        pick=pick_as_dict(pick),
        pivots=chosen_pivots(pick),
        columns=chosen_columns(pick),
        meta={"dataset": gold.dataset, "db_id": gold.db_id, **extra},
    )
