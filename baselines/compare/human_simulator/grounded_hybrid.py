"""Grounded Hybrid Simulator (non-CLAMBSQL).

Schema linking: CLAMBSQL match rule against gold table.col.
NL leftovers: agent simulator.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .agent_nl import pick_nl_agent
from .official_clear import PickResult, TokenPick, as_query_match


def _norm_key(table: str, column: str) -> str:
    return f"{(table or '').strip().lower()}.{(column or '').strip().lower()}"


def _gold_keys(gold_table_columns: set[str]) -> set[str]:
    return {k.strip().lower() for k in gold_table_columns if k and "." in k}


def _option_keys(table_dict: dict) -> set[str]:
    out = set()
    if not isinstance(table_dict, dict):
        return out
    for table, cols in table_dict.items():
        if isinstance(cols, str):
            cols = [cols]
        for col in cols or []:
            out.add(_norm_key(str(table), str(col)))
    return out


def _gold_table_dict(gold: set[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for k in sorted(gold):
        table, column = k.split(".", 1)
        out.setdefault(table, []).append(column)
    return out


def pick_schema_clambsql_rule(
    match_ambiguity: dict[str, list],
    gold_table_columns: set[str],
) -> tuple[dict[str, Any], dict[str, Any], list[TokenPick]]:
    """CLAMBSQL match: gold reading in options → type 0; all gold {t:[c]} in options → type 1."""
    gold = _gold_keys(gold_table_columns)
    gold_dict = _gold_table_dict(gold)
    clarification: dict[str, Any] = {}
    msg: dict[str, Any] = {}
    tokens: list[TokenPick] = []
    for token, table_dicts in (match_ambiguity or {}).items():
        flag = 0
        content = None
        if gold_dict and gold_dict in (table_dicts or []):
            flag = 1
            content = gold_dict
        else:
            hits = [td for td in (table_dicts or []) if _option_keys(td) and _option_keys(td) <= gold]
            if len(hits) == 1:
                flag = 1
                content = hits[0]
            elif len(hits) > 1:
                flag = 2
                content = hits[0]
            elif gold:
                missing = False
                for k in gold:
                    t, c = k.split(".", 1)
                    if {t: [c]} not in (table_dicts or []):
                        missing = True
                        break
                if not missing:
                    flag = 2
                    content = gold_dict
        rec: dict[str, Any] = {}
        if flag == 0:
            rec["type"] = 2
            rec["content"] = json.dumps({token: table_dicts})
            tokens.append(TokenPick(token, "schema", 2, None, True, "hybrid_schema"))
        elif flag == 1:
            rec["type"] = 0
            rec["content"] = json.dumps({token: content})
            clarification[token] = content
            tokens.append(TokenPick(token, "schema", 0, content, False, "hybrid_schema"))
        else:
            rec["type"] = 1
            rec["content"] = json.dumps({token: content})
            clarification[token] = content
            tokens.append(TokenPick(token, "schema", 1, content, False, "hybrid_schema"))
        msg[token] = rec
    return clarification, msg, tokens


def pick_hybrid(
    *,
    gold_table_columns: set[str],
    ambiguity_mapping: Any = None,
    question: str = "",
    nl_options: Optional[dict[str, list[str]]] = None,
    agent_fn: Optional[Callable] = None,
) -> PickResult:
    query_map, match_map = as_query_match(ambiguity_mapping)
    clarification, msg, tokens = pick_schema_clambsql_rule(match_map, gold_table_columns)

    nl_map = dict(query_map or {})
    for token, opts in (nl_options or {}).items():
        nl_map.setdefault(token, opts)

    for token, options in nl_map.items():
        chosen = pick_nl_agent(question, token, list(options or []), agent_fn=agent_fn)
        if chosen is None:
            msg[token] = {"type": 2, "content": json.dumps({token: options})}
            tokens.append(TokenPick(token, "nl", 2, None, True, "hybrid_agent"))
        else:
            msg[token] = {"type": 0, "content": json.dumps({token: chosen})}
            clarification[token] = chosen
            tokens.append(TokenPick(token, "nl", 0, chosen, False, "hybrid_agent"))

    return PickResult(
        simulator="grounded_hybrid",
        tokens=tokens,
        ambiguity_clarification=clarification,
        msg=msg,
    )
