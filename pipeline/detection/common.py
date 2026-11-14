"""检出共用辅助：gold evidence、人选列、pick 序列化，以及 06c QC JSON 解析。"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from simulator.human_simulator.standard import PickResult

from simulator.compose import _table_col_keys


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


def gold_evidence(gold) -> str:
    return str((getattr(gold, "meta", None) or {}).get("evidence") or "")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def parse_qc_json(llm_output: str) -> dict[str, Any]:
    text = (llm_output or "").strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, dict) or "choices" not in data:
        raise ValueError("QC output missing choices")
    if not isinstance(data["choices"], list):
        raise ValueError("QC choices must be a list")
    return data


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
