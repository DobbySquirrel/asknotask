"""Human pick、mapping 解析、人选列 → DetectResult 字段。"""
from __future__ import annotations

from typing import Any, Optional

from ..gold_cols import keys_for
from ..human_simulator import pick as pick_human
from ..human_simulator.official_clear import PickResult, as_query_match
from ..rewrite import _table_col_keys


def parse_mapping(raw: Any) -> dict[str, Any]:
    q, m = as_query_match(raw)
    return {"query": q or {}, "match": m or {}}


def reset_ask_budget(ctx) -> None:
    k = getattr(ctx, "budget_k", None)
    ctx._ask_leftover = None if k is None else max(0, int(k))


def frozen_mapping(ctx, gold) -> Optional[dict[str, Any]]:
    rec = (getattr(ctx, "replay_frozen", None) or {}).get(getattr(gold, "id", None))
    if not rec:
        return None
    raw = rec.get("ambiguity_mapping")
    if raw is None:
        return None
    return parse_mapping(raw)


def run_pick(gold, mapping: Any, ctx) -> PickResult:
    agent = None if ctx.dry_run else ctx.agent_fn
    return pick_human(
        gold.dataset,
        clear_ambiguity=(gold.meta or {}).get("clear_ambiguity"),
        ambiguity_mapping=mapping,
        gold_table_columns=keys_for(gold.dataset, gold.id),
        question=gold.question,
        agent_fn=agent,
    )


def chosen_columns(pick: Optional[PickResult]) -> list[str]:
    if not pick:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for tok in pick.tokens:
        if tok.abstain:
            continue
        for key in _table_col_keys(tok.chosen):
            k = key.lower()
            if k not in seen:
                seen.add(k)
                out.append(key)
    return out


def chosen_pivots(pick: Optional[PickResult]) -> list[str]:
    if not pick:
        return []
    return [t.token for t in pick.tokens if not t.abstain]


def ctx_evidence(gold, ctx, *, include_rag: bool = True) -> str:
    """Detect 可看 RAG。08 / parser 默认应关掉：当年 1-B 的 Evidence 不含检索包。"""
    base = str((gold.meta or {}).get("evidence") or "")
    extra = (getattr(ctx, "rag_text", "") or "") if include_rag else ""
    return "\n".join(p for p in (base, extra) if p and str(p).strip())


def nl_with_evidence(question: str, evidence: str) -> str:
    """数据集 Evidence 拼进 NL；AmbiSQL 模板自己的 Evidence 槽留给澄清树。"""
    q = (question or "").rstrip()
    ev = (evidence or "").strip()
    if not ev or "\nEvidence:" in f"\n{q}":
        return q
    return f"{q}\nEvidence: {ev}"


def round_record(pick: Optional[PickResult], question: str) -> dict[str, Any]:
    """一轮澄清的全文。问题、每个选项、被选中的项都不截断。"""
    asks = list(getattr(pick, "asks", None) or [])
    return {
        "question": question or "",
        "n_asked": len(asks),
        "asks": asks,
    }


def interact_meta(pick: Optional[PickResult]) -> dict[str, Any]:
    tokens = list(pick.tokens) if pick else []
    n_asked = len(tokens)
    return {
        "n_asked": n_asked,
        "n_answered": sum(1 for t in tokens if not t.abstain),
        "intervened": n_asked > 0,
        "turns": n_asked,
    }


def pick_as_dict(pick: Optional[PickResult]) -> Optional[dict[str, Any]]:
    if not pick:
        return None
    return {
        "simulator": pick.simulator,
        "ambiguity_clarification": pick.chosen_map(),
        "tokens": [
            {
                "token": t.token,
                "kind": t.kind,
                "pick_type": t.pick_type,
                "chosen": t.chosen,
                "abstain": t.abstain,
                "source": t.source,
                "ambig_type": getattr(t, "ambig_type", "") or "",
                "interpretation": getattr(t, "interpretation", "") or "",
            }
            for t in pick.tokens
        ],
    }
