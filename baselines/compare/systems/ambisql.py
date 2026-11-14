"""AmbiSQL：官方检测 prompt + 我们的 Human + 改写。

默认一轮：检出 → Human → QA 进 evidence。
--ambisql-full：CQ + 本题 Preference 树 + type=2/Others 再检。
树每题新建、不跨题；跨题才是记忆库实验。
不改 baselines/ambisql 里的上游快照。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..contract import DEFAULT_REWRITE, DetectResult
from ..rewrite import apply_rewrite, merge_evidence
from ..schema_text import detect_schema_opts, schema_clear_text, schema_map_for_prompt, schema_rich
from .ambisql_post import (
    PreferenceTree,
    question_set_to_mapping,
    refine_question,
    rewrite_choices,
)
from ..human_simulator.standard import pick_mapping_08
from .common import (
    chosen_columns,
    chosen_pivots,
    ctx_evidence,
    frozen_mapping,
    interact_meta,
    round_record,
    nl_with_evidence,
    parse_mapping,
    pick_as_dict,
    reset_ask_budget,
)

_AMBI = Path(__file__).resolve().parents[2] / "ambisql"
if str(_AMBI) not in sys.path:
    sys.path.insert(0, str(_AMBI))


def _prompt_mod():
    from ambisql.prompts.ambiguity_detection_prompt import (
        AmbiguityDetection_examples,
        AmbiguityDetection_prompt,
    )

    return AmbiguityDetection_prompt, AmbiguityDetection_examples


def _detect_raw(gold, ctx, question: str, evidence: str | None) -> dict:
    tmpl, examples = _prompt_mod()
    tabs, with_ex = detect_schema_opts(gold)
    prompt = tmpl.format(
        question=nl_with_evidence(question, ctx_evidence(gold, ctx)),
        schema=json.dumps(
            schema_rich(gold, tables=tabs, with_examples=with_ex),
            ensure_ascii=False,
        ),
        evidence=evidence if evidence else None,
        examples=examples,
    )
    fn = getattr(ctx, "complete_json", None)
    if callable(fn):
        return fn(prompt)
    return ctx.parse_json(ctx.llm.complete(prompt))


def _others_text(pick) -> str:
    if not pick:
        return ""
    bits = []
    for tok in pick.tokens:
        if tok.abstain:
            continue
        text = str(tok.chosen or "")
        if text.strip().lower() == "others" or text.lower().startswith("others"):
            bits.append(text)
    return "\n".join(bits)


def detect_ambisql(gold, ctx) -> DetectResult:
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    ev = ctx_evidence(gold, ctx)
    mode = ctx.rewrite_mode or DEFAULT_REWRITE["ambisql"]
    full = bool(getattr(ctx, "ambisql_full", False))
    q_set: list = []
    question = gold.question
    pref = PreferenceTree() if full else None
    n_cq = 0
    revised = False
    n_merge = 0
    reset_ask_budget(ctx)
    replayed = frozen_mapping(ctx, gold)

    if replayed is not None:
        mapping = replayed
    elif ctx.oracle_detect or ctx.dry_run:
        mapping = parse_mapping((gold.meta or {}).get("gold_ambiguity"))
    else:
        parsed = _detect_raw(gold, ctx, question, None)
        q_set = parsed.get("question_set") or []
        if full and q_set:
            q_set = rewrite_choices(ctx.llm, ctx.parse_json, q_set)
            n_cq = sum(1 for x in q_set if x.get("choices"))
        mapping = (
            question_set_to_mapping(q_set, smap)
            if parsed.get("has_ambiguity")
            else {"query": {}, "match": {}}
        )

    pick = pick_mapping_08(gold, mapping, ctx)
    round_metas = [interact_meta(pick)]
    rounds = [round_record(pick, gold.question)]
    if replayed is None and full and pref is not None and not (ctx.oracle_detect or ctx.dry_run):
        pref.ingest_pick(q_set, pick, ctx.llm, ctx.parse_json)
        n_merge = max(0, sum(1 for v in pref.leaves.values() if len(v) > 1))
        extra = _others_text(pick)
        need_again = extra.strip() or any(t.abstain for t in pick.tokens)
        if need_again:
            if extra.strip():
                question = refine_question(ctx.llm, question, extra)
            parsed = _detect_raw(gold, ctx, question, pref.traverse() or None)
            q_set = parsed.get("question_set") or []
            if q_set:
                q_set = rewrite_choices(ctx.llm, ctx.parse_json, q_set)
                n_cq += sum(1 for x in q_set if x.get("choices"))
            mapping = (
                question_set_to_mapping(q_set, smap)
                if parsed.get("has_ambiguity")
                else {"query": {}, "match": {}}
            )
            pick = pick_mapping_08(gold, mapping, ctx)
            round_metas.append(interact_meta(pick))
            rounds.append(round_record(pick, question))
            pref.ingest_pick(q_set, pick, ctx.llm, ctx.parse_json)
            n_merge = max(0, sum(1 for v in pref.leaves.values() if len(v) > 1))
            revised = True

    q_out, s_out, e_out = apply_rewrite(
        mode,
        question=question,
        schema_str=schema,
        schema_map=smap,
        mapping=mapping,
        pick=pick,
        evidence=ev,
        schema_formatter=schema_clear_text,
        parser=str(getattr(ctx, "parser", "base") or "base"),
    )
    if full and pref is not None:
        tree = pref.traverse()
        # replay 时树是空的，不能盖掉 apply_rewrite 已经写进 evidence 的 08 答案
        if tree:
            e_out = merge_evidence(ev, tree)
    return DetectResult(
        id=gold.id,
        system="ambisql_full" if full else "ambisql",
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
        meta={
            "dataset": gold.dataset,
            "db_id": gold.db_id,
            "n_cq": len(q_set),
            "n_cq_rewrite": n_cq,
            "ambisql_full": full,
            "redetect": revised,
            "n_rounds": len(round_metas),
            "round_asks": [m["n_asked"] for m in round_metas],
            "rounds": rounds,
            "preference_n_leaf": sum(len(v) for v in pref.leaves.values()) if pref else 0,
            "preference_merge": n_merge,
            "oracle_detect": bool(ctx.oracle_detect or ctx.dry_run),
            "human": "08",
            **{
                "n_asked": sum(m["n_asked"] for m in round_metas),
                "n_answered": sum(m["n_answered"] for m in round_metas),
                "intervened": any(m["intervened"] for m in round_metas),
                "turns": sum(m["n_asked"] for m in round_metas),
            },
        },
    )
