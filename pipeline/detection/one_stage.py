# SOURCE: see pipeline/SOURCE.md
"""单枪检测：一次用 `06b_ours_detect_1bc_oneprompt.md` 检出九类歧义，再按需走 06c、问询、改写和 SQL。

入口：`detect_one_stage(gold, ctx)` / `run_one_stage(gold, ctx)`
"""
from __future__ import annotations

import importlib.util as _ilu
import os
import sys
from pathlib import Path
from typing import Any

_ASK = Path(__file__).resolve().parents[2]
if str(_ASK) not in sys.path:
    sys.path.insert(0, str(_ASK))

from simulator.compose import apply_rewrite
from simulator.compose import DEFAULT_REWRITE, DetectResult
from pipeline.detection import three_stage as det
from pipeline.detection.common import gold_evidence
from utils.llm import parse_sql
from schema_text import (
    schema_clear_text,
    schema_map_for_prompt,
    schema_numbered_rich,
)
from simulator.human_simulator.standard import PickResult

_qc = _ASK / "parsers" / "qwen_coder.py"
_spec = _ilu.spec_from_file_location("ask_qwen_coder", _qc)
_mod = _ilu.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
format_parser_base = _mod.format_parser_base

PROMPTS = Path(__file__).resolve().parent / "prompts"
ONE_SHOT = "06b_ours_detect_1bc_oneprompt.md"


def _drop_table(phi: dict, span_types: dict, span_interps: dict) -> tuple[dict, dict, dict]:
    keep = {s for s, t in (span_types or {}).items() if str(t) != "Table"}
    phi2 = {s: list(c) for s, c in (phi or {}).items() if s in keep or s not in span_types}
    types2 = {s: t for s, t in (span_types or {}).items() if str(t) != "Table"}
    interps2 = {s: span_interps[s] for s in types2 if s in (span_interps or {})}
    return phi2, types2, interps2


def _fill_one_shot(**slots: str) -> str:
    text = (PROMPTS / ONE_SHOT).read_text(encoding="utf-8")
    i = text.find("### Role")
    if i < 0:
        i = text.find("# Role")
    text = text[i:] if i >= 0 else text
    for key, val in slots.items():
        text = text.replace("{" + key + "}", val)
    return text


def _cards_ask_all(
    phi: dict[str, list],
    span_types: dict[str, str],
    span_interps: dict[str, str],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for span, cands in (phi or {}).items():
        if not isinstance(cands, list) or len(cands) < 2:
            continue
        if str(span_types.get(span) or "") == "Table":
            continue
        shown = det._display_span(span)
        ambig_type = str(span_types.get(span) or "")
        detect_interp = str(span_interps.get(span) or "")
        choices = det._raw_choices(cands)
        cards.append({
            "span": shown,
            "_phi_key": span,
            "cands": cands,
            "choices": choices,
            "ambig_type": ambig_type,
            "interpretation": detect_interp,
            "batch": 0,
            "qc": {
                "clarification_question": shown,
                "choices": choices,
                "skipped_qc": True,
            },
        })
    return cards


def detect_one_stage(gold, ctx) -> DetectResult:
    """单枪九类检出 + 全问 simulator + evidence 改写。"""
    os.environ["PAPER_EXP_NO_TABLE"] = "1"
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = gold_evidence(gold) or "NULL"
    mode = getattr(ctx, "rewrite_mode", None) or DEFAULT_REWRITE.get("ours_1bc", "evidence")
    llm = ctx.llm
    q = gold.question

    raw = ctx.parse_json(llm.complete(_fill_one_shot(
        schema_content=schema_llm,
        question=q,
        evidence=ev,
    )))
    phi, span_types, span_interps = det.parse_phi(raw)
    phi, span_types, span_interps = _drop_table(phi, span_types, span_interps)
    phi = {s: list(c) for s, c in phi.items() if isinstance(c, list) and len(c) >= 2}

    use_qc = not bool(getattr(ctx, "no_qc", False))
    if use_qc:
        cards, n_qc = det._qc_cards(
            llm, q, phi, 0, healed={}, no_qc=False,
            span_types=span_types, span_interps=span_interps,
            schema_content=schema_llm, evidence=ev,
        )
    else:
        cards = _cards_ask_all(phi, span_types, span_interps)
        n_qc = 0
    tokens, clarification = det._ask_human_cards(
        gold, llm, cards, q, schema_llm, ev if ev != "NULL" else "NULL",
        span_types, span_interps,
    )
    pick = PickResult(
        simulator="one_stage_08",
        tokens=tokens,
        ambiguity_clarification=clarification,
    )
    mapping = det.phi_to_mapping(phi)
    q_out, s_out, e_out = apply_rewrite(
        mode,
        question=q,
        schema_str=schema,
        schema_map=smap,
        mapping=mapping,
        pick=pick,
        evidence="" if ev == "NULL" else ev,
        schema_formatter=schema_clear_text,
        parser=str(getattr(ctx, "parser", "base") or "base"),
    )
    return det._result(gold, mode, schema, q_out, s_out, e_out, mapping, pick, {
        "pipeline": "one_stage",
        "stages": {"s1": False, "s2": False, "s3": False, "one_shot": True},
        "checks": False,
        **det.ask_stats(tokens, cards),
        "n_healed": 0,
        "n_qc": n_qc,
        "no_qc": not use_qc,
        "phi": phi,
        "span_types": span_types,
        "span_interps": span_interps,
        "ask_cards": cards,
        "parser": "qwen_coder",
        "detect_prompt": ONE_SHOT,
        "taxonomy": "9types_no_table",
    })


def run_one_stage(gold, ctx) -> dict[str, Any]:
    det_row = detect_one_stage(gold, ctx)
    prompt = format_parser_base(
        det_row.schema_out or "",
        det_row.question_out or gold.question or "",
        det_row.evidence_out or "",
    )
    sql = parse_sql(ctx.llm.complete(prompt)) or ""
    meta = dict(det_row.meta or {})
    return {
        "id": gold.id,
        "db_id": getattr(gold, "db_id", None),
        "system": "one_stage",
        "pipeline": "one_stage",
        "parser": "qwen_coder",
        "question_out": det_row.question_out,
        "schema_out": det_row.schema_out,
        "evidence_out": det_row.evidence_out,
        "predicted_sql": sql,
        "n_asked": meta.get("n_asked", 0),
        "n_answered": meta.get("n_answered", 0),
        "n_healed": 0,
        "phi": meta.get("phi") or {},
        "ask_cards": meta.get("ask_cards") or [],
        "span_types": meta.get("span_types") or {},
        "meta": meta,
    }
