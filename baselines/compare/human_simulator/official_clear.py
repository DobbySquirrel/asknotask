"""Faithful port of CLEAR HumanSimulator.election_clambsql. Do not tidy the 0.9 / last-hit bugs.

PickResult / TokenPick live here so Hybrid can return the same object:
    result = pick_clambsql_official(clear, mapping)
    result.ambiguity_clarification  # {"continent": {"country": ["continent_name"]}}
    result.tokens[0].abstain        # type==2
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


@dataclass
class TokenPick:
    token: str
    kind: str  # schema | nl
    pick_type: int  # 0 hit, 1 merge, 2 abstain
    chosen: Any = None
    abstain: bool = False
    source: str = ""
    ambig_type: str = ""  # Scope | Column | Value | ...
    interpretation: str = ""  # QC desc of the chosen option
    clarification_question: str = ""  # 06c clarification_question


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

SIM_THRESHOLD = 0.9


@lru_cache(maxsize=1)
def _retriever():
    try:
        from sentence_transformers import SentenceTransformer, util
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2", device=device)

        def score(s1: str, s2: str) -> float:
            e1 = model.encode(s1)
            e2 = model.encode(s2)
            return float(util.cos_sim(e1, e2)[0].numpy().tolist()[0])

        return score
    except ImportError:
        def score(s1: str, s2: str) -> float:
            a, b = str(s1).strip().lower(), str(s2).strip().lower()
            return 1.0 if a == b else 0.0

        return score


def pick_clambsql_official(clear_ambiguity: Any, ambiguity_mapping: Any) -> PickResult:
    clear = parse_ambiguity_map(clear_ambiguity)
    if not isinstance(clear, dict):
        clear = {}
    query_ambiguity, match_ambiguity = as_query_match(ambiguity_mapping)
    score_fn = _retriever() if query_ambiguity else None

    msg: dict[str, Any] = {}
    clarification: dict[str, Any] = {}
    tokens: list[TokenPick] = []

    for token1, interpretations in query_ambiguity.items():
        flag = 0
        interpretation = None
        for token2 in clear:
            p = clear[token2]
            for interpretation in interpretations:
                if score_fn and score_fn(str(p), str(interpretation)) > SIM_THRESHOLD:
                    flag = 1
        rec = {"type": 2 if flag == 0 else 0}
        if flag == 0:
            rec["content"] = json.dumps({token1: interpretations})
            tokens.append(TokenPick(token1, "nl", 2, None, True, "clear_official"))
        else:
            rec["content"] = json.dumps({token1: interpretation})
            clarification[token1] = interpretation
            tokens.append(TokenPick(token1, "nl", 0, interpretation, False, "clear_official"))
        msg[token1] = rec

    for token1, table_dicts1 in match_ambiguity.items():
        flag = 0
        content = None
        for token2 in clear:
            table_dict2 = clear[token2]
            if table_dict2 in table_dicts1:
                flag = 1
                content = table_dict2
            else:
                sub_flag = 0
                if isinstance(table_dict2, dict):
                    for table in table_dict2:
                        for col in table_dict2[table]:
                            if {table: [col]} not in table_dicts1:
                                sub_flag = 1
                    if sub_flag == 0:
                        flag = 2
                        content = table_dict2
        rec: dict[str, Any] = {}
        if flag == 0:
            rec["type"] = 2
            rec["content"] = json.dumps({token1: table_dicts1})
            tokens.append(TokenPick(token1, "schema", 2, None, True, "clear_official"))
        elif flag == 1:
            rec["type"] = 0
            rec["content"] = json.dumps({token1: content})
            clarification[token1] = content
            tokens.append(TokenPick(token1, "schema", 0, content, False, "clear_official"))
        else:
            rec["type"] = 1
            rec["content"] = json.dumps({token1: content})
            clarification[token1] = content
            tokens.append(TokenPick(token1, "schema", 1, content, False, "clear_official"))
        msg[token1] = rec

    return PickResult(
        simulator="clear_official",
        tokens=tokens,
        ambiguity_clarification=clarification,
        msg=msg,
    )
