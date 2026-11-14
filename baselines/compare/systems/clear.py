"""CLEAR：官方 mapping prompt + 规则 + Vagueness + Human。

默认一轮 Human（--system clear）。
--clear-revision：type=2 时重检 Match 再问第二次（tag=clear_revision）。
不改 baselines/clear 里的上游快照。
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..contract import DEFAULT_REWRITE, DetectResult
from ..rewrite import apply_rewrite
from ..schema_text import (
    detect_schema_opts,
    interp_lookup_rich,
    interpretations,
    schema_clear_text,
    schema_map_for_prompt,
)
from .clear_retrieve import query_gate_keywords, retrieve_interpretations
from .clear_post import postprocess_mapping, revision_notes
from ..human_simulator.official_clear import pick_clambsql_official
from ..human_simulator.standard import pick_mapping_08
from .common import (
    chosen_columns,
    chosen_pivots,
    ctx_evidence,
    frozen_mapping,
    interact_meta,
    round_record,
    parse_mapping,
    pick_as_dict,
    reset_ask_budget,
)

_CLEAR = Path(__file__).resolve().parents[2] / "clear"
if str(_CLEAR) not in sys.path:
    sys.path.insert(0, str(_CLEAR))


def _prompts():
    from src.prompt_tool import get_prompt_ambiguity_map, get_prompt_query_ambiguity

    return get_prompt_ambiguity_map, get_prompt_query_ambiguity


def _gold_mapping(gold) -> dict:
    raw = (gold.meta or {}).get("gold_ambiguity")
    if raw:
        return parse_mapping(raw)
    return {"query": {}, "match": {}}


def _label(x) -> str:
    if x is None:
        return "ABSTAIN"
    if isinstance(x, (dict, list)):
        import json

        return json.dumps(x, ensure_ascii=False, sort_keys=True)
    return str(x).strip()


def _agree_08_official(sim, official) -> dict:
    if not official or not official.tokens:
        return {"n": 0, "agreement": None}
    keys = sorted({t.token for t in official.tokens} | {t.token for t in (sim.tokens if sim else [])})
    a = [_label((sim.chosen_map() if sim else {}).get(k)) for k in keys]
    if sim:
        for t in sim.tokens:
            if t.abstain and t.token in keys:
                a[keys.index(t.token)] = "ABSTAIN"
    b = [_label(official.chosen_map().get(k)) for k in keys]
    for t in official.tokens:
        if t.abstain and t.token in keys:
            b[keys.index(t.token)] = "ABSTAIN"
    n = len(keys)
    hit = sum(1 for x, y in zip(a, b) if x == y) if n else 0
    return {"n": n, "agreement": (hit / n) if n else None, "tokens": keys}


def _complete_json(ctx, prompt: str) -> dict:
    fn = getattr(ctx, "complete_json", None)
    if callable(fn):
        return fn(prompt)
    return ctx.parse_json(ctx.llm.complete(prompt))


def _vague_n(ctx) -> int:
    return max(1, int(getattr(ctx, "vague_n", 1) or 1))


def _faithful(ctx) -> str:
    mode = str(getattr(ctx, "clear_faithful", "off") or "off").lower()
    return mode if mode in {"k", "f"} else "off"


def _query_gate(gold, ctx) -> bool:
    if ctx.force_query:
        return True
    if _faithful(ctx) in {"k", "f"}:
        return query_gate_keywords(gold.question)
    return (gold.ambig_type or "") in {"scope", "attachment"}


def _want_match_retrieve(gold, ctx) -> bool:
    flag = getattr(ctx, "clear_match_retrieve", None)
    if flag is True:
        return True
    if flag is False:
        return False
    if _faithful(ctx) == "f":
        return True
    return False


def _match_interps(gold, ctx, tables, with_ex) -> tuple[list[str], dict]:
    interps = interpretations(gold, tables=tables, with_examples=with_ex)
    meta = {"n_all": len(interps), "n_used": len(interps), "k": len(interps), "backend": "full"}
    if interps and _want_match_retrieve(gold, ctx):
        interps, meta = retrieve_interpretations(gold.question, interps)
    return interps, meta


def _detect_match(gold, ctx, note: str) -> dict:
    get_match, _ = _prompts()
    tables, with_ex = detect_schema_opts(gold)
    interps, _ = _match_interps(gold, ctx, tables, with_ex)
    if not interps:
        return {}
    parsed = _complete_json(ctx, get_match(gold.question, interps, note or "NULL"))
    return parse_mapping(parsed).get("match") or parsed


def detect_clear_mapping(gold, ctx) -> dict:
    """CLEAR 检出 + 规则 + Vagueness，停在 Human 之前。官方 Human 与 Hybrid 必须吃这份 mapping。"""
    if ctx.oracle_detect or ctx.dry_run:
        return _gold_mapping(gold)
    smap = schema_map_for_prompt(gold)
    ev = ctx_evidence(gold, ctx)
    get_match, get_query = _prompts()
    mapping = {"query": {}, "match": {}}
    note = ev if ev else "NULL"
    tables, with_ex = detect_schema_opts(gold)
    interps, ret_meta = _match_interps(gold, ctx, tables, with_ex)
    if interps:
        parsed = _complete_json(ctx, get_match(gold.question, interps, note))
        mapping["match"] = parse_mapping(parsed).get("match") or parsed
    query_on = _query_gate(gold, ctx)
    if query_on:
        parsed_q = _complete_json(ctx, get_query(gold.question))
        mapping["query"] = parse_mapping(parsed_q).get("query") or parsed_q
    ctx.clear_last_detect = {
        "clear_faithful": _faithful(ctx),
        "query_gate": query_on,
        **ret_meta,
    }
    return postprocess_mapping(
        gold.question,
        parse_mapping(mapping),
        smap,
        db_path=gold.db_path or "",
        llm=ctx.llm,
        parse_json=ctx.parse_json,
        n_vote=_vague_n(ctx),
        do_vague=True,
        interps=interp_lookup_rich(gold, tables=tables, with_examples=with_ex),
    )


def detect_clear(gold, ctx) -> DetectResult:
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    tables, with_ex = detect_schema_opts(gold)
    ev = ctx_evidence(gold, ctx)
    mode = ctx.rewrite_mode or DEFAULT_REWRITE["clear"]
    reset_ask_budget(ctx)
    replayed = frozen_mapping(ctx, gold)
    mapping = replayed if replayed is not None else detect_clear_mapping(gold, ctx)
    pick = pick_mapping_08(gold, mapping, ctx)
    round_metas = [interact_meta(pick)]
    rounds = [round_record(pick, gold.question)]
    revised = False
    if (
        replayed is None
        and getattr(ctx, "clear_revision", False)
        and not (ctx.oracle_detect or ctx.dry_run)
        and (gold.ambig_type or "") not in {"scope", "attachment"}
    ):
        notes = revision_notes(pick, mapping.get("match") or {})
        if notes:
            mapping["match"] = _detect_match(gold, ctx, " ".join(notes))
            mapping = postprocess_mapping(
                gold.question,
                mapping,
                smap,
                db_path=gold.db_path or "",
                llm=ctx.llm,
                parse_json=ctx.parse_json,
                n_vote=_vague_n(ctx),
                do_vague=True,
                interps=interp_lookup_rich(gold, tables=tables, with_examples=with_ex),
            )
            pick = pick_mapping_08(gold, mapping, ctx)
            round_metas.append(interact_meta(pick))
            rounds.append(round_record(pick, gold.question))
            revised = True
    official = pick_clambsql_official((gold.meta or {}).get("clear_ambiguity"), mapping)
    q_out, s_out, e_out = apply_rewrite(
        mode,
        question=gold.question,
        schema_str=schema,
        schema_map=smap,
        mapping=mapping,
        pick=pick,
        evidence=ev,
        schema_formatter=schema_clear_text,
        parser=str(getattr(ctx, "parser", "base") or "base"),
    )
    return DetectResult(
        id=gold.id,
        system="clear",
        rewrite_mode=mode,
        question_in=gold.question,
        schema_in=schema,
        question_out=q_out,
        schema_out=s_out,
        evidence_out=e_out,
        clarification=pick_as_dict(pick) and str(pick.chosen_map()) or "",
        ambiguity_mapping=mapping,
        pick=pick_as_dict(pick),
        pivots=chosen_pivots(pick),
        columns=chosen_columns(pick),
        meta={
            "dataset": gold.dataset,
            "db_id": gold.db_id,
            "oracle_detect": bool(ctx.oracle_detect or ctx.dry_run),
            "clear_revision": bool(getattr(ctx, "clear_revision", False)),
            "clear_faithful": _faithful(ctx),
            "mapping_revision": revised,
            "n_rounds": len(round_metas),
            "round_asks": [m["n_asked"] for m in round_metas],
            "rounds": rounds,
            "human": "08",
            **(getattr(ctx, "clear_last_detect", None) or {}),
            "official_pick": pick_as_dict(official) if official.tokens else None,
            "agree_08_official": _agree_08_official(pick, official),
            **{
                "n_asked": sum(m["n_asked"] for m in round_metas),
                "n_answered": sum(m["n_answered"] for m in round_metas),
                "intervened": any(m["intervened"] for m in round_metas),
                "turns": sum(m["n_asked"] for m in round_metas),
            },
        },
    )
