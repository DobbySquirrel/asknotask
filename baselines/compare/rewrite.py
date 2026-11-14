"""改写三选一：同一 mapping + Human pick，只换落地方式。

schema_dq  — CLEAR 原文：改问句 + 从 schema 删没选中的列（query 类不动 schema）
schema_dqg — 只在真的删列时走 schema_dq；否则原问原 schema（避开括号改写伤 EX）
schema_q   — 消融：只做问句括号改写，保留完整 schema（不删列）
ambisql    — 原问原 schema，人选写成 QA 放进 evidence
evidence   — 原问原 schema，人选整包塞进 evidence
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from .human_simulator.official_clear import PickResult, as_query_match


def _table_col_keys(table_dict: Any) -> list[str]:
    out: list[str] = []
    if isinstance(table_dict, str) and "." in table_dict:
        return [table_dict.strip()]
    if not isinstance(table_dict, dict):
        return out
    for table, cols in table_dict.items():
        t = str(table).strip()
        if not t:
            continue
        # Value / Project 常写成 {"customers.Currency": "Currency"}。
        # key 已是 table.col，禁止再把 payload 拼成 table.col.col。
        if "." in t:
            out.append(t)
            continue
        if isinstance(cols, str):
            cols = [cols]
        elif isinstance(cols, (int, float)):
            cols = [str(cols)]
        elif not isinstance(cols, (list, tuple)):
            cols = [cols] if cols is not None else []
        for col in cols:
            c = str(col).strip()
            if t and c:
                out.append(f"{t}.{c}")
    return out


def _norm(key: str) -> str:
    return key.strip().lower()


def _fmt_keys(keys: list[str]) -> str:
    return " and ".join(keys)


def rewrite_question_schema_dq(
    question: str,
    mapping: Any,
    pick: Optional[PickResult],
) -> str:
    query_map, match_map = as_query_match(mapping)
    chosen = pick.chosen_map() if pick else {}
    q = question or ""
    for token, options in (query_map or {}).items():
        picked = chosen.get(token)
        if picked is None or not str(token).strip():
            continue
        if str(token) in q:
            q = q.replace(str(token), str(picked), 1)
        else:
            q = f"{q} ({picked})"
    for token, options in (match_map or {}).items():
        picked = chosen.get(token)
        if picked is None or not str(token).strip():
            continue
        keys = _table_col_keys(picked) if isinstance(picked, dict) else [str(picked)]
        if not keys:
            continue
        repl = f"{token} ({_fmt_keys(keys)})"
        if str(token) in q:
            q = q.replace(str(token), repl, 1)
        else:
            q = f"{q} ({repl})"
    return q


def drop_unselected_columns(
    schema_map: dict[str, list[str]],
    mapping: Any,
    pick: Optional[PickResult],
) -> dict[str, list[str]]:
    """match 人选之外的候选列从 schema 删掉；query 类 / 弃权不动。"""
    _, match_map = as_query_match(mapping)
    chosen = pick.chosen_map() if pick else {}
    drop: set[str] = set()
    for token, options in (match_map or {}).items():
        picked = chosen.get(token)
        if picked is None:
            continue
        keep = {_norm(k) for k in _table_col_keys(picked)} if isinstance(picked, dict) else set()
        if not keep:
            continue
        for opt in options or []:
            for key in _table_col_keys(opt):
                if _norm(key) not in keep:
                    drop.add(_norm(key))
    if not drop:
        return {t: list(cols) for t, cols in (schema_map or {}).items()}
    out: dict[str, list[str]] = {}
    for table, cols in (schema_map or {}).items():
        kept = [c for c in cols if _norm(f"{table}.{c}") not in drop]
        if kept:
            out[table] = kept
    return out


def _schema_map_equal(a: dict[str, list[str]] | None, b: dict[str, list[str]] | None) -> bool:
    aa = {str(t): [str(c) for c in (cols or [])] for t, cols in (a or {}).items()}
    bb = {str(t): [str(c) for c in (cols or [])] for t, cols in (b or {}).items()}
    return aa == bb


def evidence_qa(pick: Optional[PickResult]) -> str:
    if not pick:
        return ""
    lines: list[str] = []
    for tok in pick.tokens:
        if tok.abstain:
            lines.append(f"Q: {tok.token}\nA: Abstain")
        else:
            lines.append(f"Q: {tok.token}\nA: {json.dumps(tok.chosen, ensure_ascii=False)}")
    return "\n".join(lines)


_SCHEMA_TYPES = {"column", "table", "join", "project", "aggregate", "scope", "attachment"}
_PRED_TYPES = {"value", "null", "tie"}
_SIMPLE_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_sql_ident(ident: str) -> str:
    """列名含空格或 - / ( ) 等时强制双引号，避免下游 SQL 语法挂掉。"""
    s = str(ident or "")
    if not s:
        return s
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s
    if _SIMPLE_IDENT.fullmatch(s):
        return s
    return '"' + s.replace('"', '""') + '"'


def quote_table_col(ref: str) -> str:
    s = str(ref or "").strip()
    if not s:
        return s
    parts = s.split(".")
    # customers.Currency.Currency → customers.Currency
    if len(parts) >= 3 and parts[-1] == parts[-2]:
        s = ".".join(parts[:-1])
        parts = s.split(".")
    if "." in s:
        table, col = s.split(".", 1)
        return f"{quote_sql_ident(table)}.{quote_sql_ident(col)}"
    return quote_sql_ident(s)


def _quote_snippet(snip: Any) -> Any:
    if isinstance(snip, list):
        return [_quote_snippet(x) for x in snip]
    if not isinstance(snip, str):
        return snip
    for sep in (" IN ", " = ", ": "):
        if sep in snip:
            left, right = snip.split(sep, 1)
            return f"{quote_table_col(left.strip())}{sep}{right}"
    if "." in snip:
        return quote_table_col(snip)
    return quote_sql_ident(snip) if not _SIMPLE_IDENT.fullmatch(snip) and " " in snip else snip


def _table_of_snippet(item: Any) -> str | None:
    """table.col / table."col" → table；没有点的光列名 → None。"""
    if isinstance(item, dict):
        tabs = {t for k in _table_col_keys(item) if (t := _table_of_snippet(k))}
        if len(tabs) == 1:
            return next(iter(tabs))
        return None
    s = str(item or "").strip().strip('"').strip("'")
    if not s or "." not in s:
        return None
    head = s.split(".", 1)[0].strip().strip('"').strip("'").lower()
    if not head or any(ch in head for ch in " {}[]:=,"):
        return None
    return head or None


def _tables_in_snip(snip: list) -> set[str]:
    named: set[str] = set()
    for x in snip:
        if isinstance(x, dict):
            named.update(t for k in _table_col_keys(x) if (t := _table_of_snippet(k)))
        else:
            t = _table_of_snippet(x)
            if t:
                named.add(t)
    return named


def _leaf_col(item: Any) -> str | None:
    if isinstance(item, dict):
        cols = []
        for k in _table_col_keys(item):
            s = str(k)
            if "." in s:
                cols.append(s.split(".", 1)[1].strip().strip('"').strip("'").lower())
        return cols[0] if cols and len(set(cols)) == 1 else None
    s = str(item or "").strip().strip('"').strip("'")
    if "." not in s:
        return None
    col = s.split(".", 1)[1].strip().strip('"').strip("'").lower()
    if not col or any(ch in col for ch in " {}[]:=,"):
        return None
    return col


def _is_join_key_col(col: str) -> bool:
    c = (col or "").lower()
    return c == "id" or c.endswith("id") or c.endswith("key")


def is_join_key_list(snip: list) -> bool:
    """跨表但像外键/同名 id：保留。name/name、Currency vs CustomerID 仍算争端。"""
    if not isinstance(snip, list) or len(_tables_in_snip(snip)) <= 1:
        return False
    cols = [_leaf_col(x) for x in snip]
    if any(c is None for c in cols):
        return False
    uniq = {c.lower() for c in cols}
    if len(uniq) == 1:
        return _is_join_key_col(next(iter(uniq)))
    if len(uniq) == 2:
        a, b = sorted(uniq)
        if a == "id" and _is_join_key_col(b):
            return True
    return False


_COMPETE_SAME_COLS = {"name", "type", "year", "date", "diagnosis", "location"}


def is_name_join_list(snip: list) -> bool:
    """OwnerDisplayName↔DisplayName 这类同义 name 列当 join 留；circuits.name↔races.name 仍丢。"""
    if not isinstance(snip, list) or len(_tables_in_snip(snip)) <= 1:
        return False
    cols = [_leaf_col(x) for x in snip]
    if any(c is None for c in cols):
        return False
    lows = [c.lower() for c in cols]
    uniq = set(lows)
    if len(uniq) == 1:
        c = next(iter(uniq))
        if c in _COMPETE_SAME_COLS:
            return False
        return "name" in c
    if len(lows) == 2:
        a, b = sorted(lows, key=len)
        if a and a in b and "name" in a:
            return True
    return False


def is_keepable_cross_list(snip: list) -> bool:
    return is_join_key_list(snip) or is_name_join_list(snip)


def force_389_snippet(snip: Any, chosen: Any = None) -> Any:
    """389 单值口径：同表复合列可留 list；跨表未决不入 Hint；唯一 winner 解成字符串。"""
    if not isinstance(snip, list):
        return snip
    if not snip:
        return None
    if len(_tables_in_snip(snip)) <= 1:
        return snip
    if isinstance(chosen, str) and chosen.strip():
        return _quote_snippet(chosen.strip())
    if isinstance(chosen, dict):
        keys = _table_col_keys(chosen)
        key_tables = {t for k in keys if (t := _table_of_snippet(k))}
        if len(keys) == 1:
            return _quote_snippet(keys[0])
        if len(key_tables) == 1:
            return [_quote_snippet(k) for k in keys]
    if isinstance(chosen, list) and len(chosen) == 1:
        return force_389_snippet(render_mapping_snippet("", chosen[0]), chosen[0])
    return None


def sanitize_qmap_list(snip: Any, chosen: Any = None) -> Any:
    """List snippet：同表复合列保留；跨表 id/FK/同义 name join 保留；其余竞争能解包则解包，否则丢掉。

    A. ["t.col1","t.col2"] 或 ["col1","col2"] → 保留。
    A2. ["t1.id","t2.id"] / ["t1.foo_id","t2.id"] / OwnerDisplayName↔DisplayName → join 线索保留。
    B. ["tableA.x","tableB.y"] 且不像 join：chosen 唯一 winner → 单字符串；否则 None。
    """
    if not isinstance(snip, list):
        return snip
    if not snip:
        return None
    named = _tables_in_snip(snip)
    if len(named) <= 1 or is_keepable_cross_list(snip):
        return snip
    if isinstance(chosen, str) and chosen.strip():
        return _quote_snippet(chosen.strip())
    if isinstance(chosen, dict):
        keys = _table_col_keys(chosen)
        key_tables = {t for k in keys if (t := _table_of_snippet(k))}
        if len(keys) == 1:
            return _quote_snippet(keys[0])
        if len(key_tables) == 1:
            return [_quote_snippet(k) for k in keys]
    if isinstance(chosen, list) and len(chosen) == 1:
        return sanitize_qmap_list(render_mapping_snippet("", chosen[0]), chosen[0])
    return None


def render_mapping_snippet(ambig_type: str, chosen: Any) -> Any:
    """Prompt-3 风格：Column 只留 table.col，Value 才写成谓词。丢掉 DISTINCT 样例值。"""
    t = (ambig_type or "").strip().lower()
    if chosen is None:
        return None
    if isinstance(chosen, str):
        return _quote_snippet(chosen)
    if not isinstance(chosen, dict):
        return chosen
    if t in _SCHEMA_TYPES:
        if len(chosen) == 1:
            k, v = next(iter(chosen.items()))
            if "." in str(k) and isinstance(v, (list, tuple)):
                return _quote_snippet(str(k))
        keys = _table_col_keys(chosen)
        if keys:
            quoted = [_quote_snippet(x) for x in keys]
            return quoted[0] if len(quoted) == 1 else quoted
        return chosen
    if t in _PRED_TYPES and len(chosen) == 1:
        k, v = next(iter(chosen.items()))
        if isinstance(v, str):
            if t == "value":
                return _quote_snippet(f"{k} = {json.dumps(v, ensure_ascii=False)}")
            return _quote_snippet(f"{k}: {v}")
        if isinstance(v, list) and t == "value":
            return _quote_snippet(f"{k} IN {json.dumps(v, ensure_ascii=False)}")
    return chosen


def rewrite_pack_for(parser: str | None = None, pack: str | None = None) -> str:
    """Parser-Adaptive Packaging：DeepEye=qmap，Qwen/base=verbose。"""
    if pack:
        p = pack.strip().lower()
        if p in {"qmap", "deepeye"}:
            return "qmap"
        if p in {"verbose", "base"}:
            return "verbose"
        raise ValueError(f"unknown evidence pack {pack!r}; use qmap|verbose")
    kind = (parser or "base").strip().lower()
    if kind in {"deepeye", "deepeye_official"}:
        return "qmap"
    return "verbose"


def evidence_dump_qmap(pick: Optional[PickResult]) -> str:
    """DeepEye 瘦格式：只放 Q + mapping_snippet。"""
    if not pick:
        return ""
    items: list[dict[str, Any]] = []
    for tok in pick.tokens:
        if tok.abstain:
            continue
        ambig_type = (getattr(tok, "ambig_type", None) or "").strip()
        snip = sanitize_qmap_list(render_mapping_snippet(ambig_type, tok.chosen), tok.chosen)
        q = (getattr(tok, "clarification_question", None) or "").strip() or (tok.token or "").strip()
        if snip is None or snip == "" or snip == []:
            continue
        items.append({"Q": q, "mapping_snippet": snip})
    if not items:
        return ""
    return json.dumps(items, ensure_ascii=False)


def evidence_dump_verbose(pick: Optional[PickResult]) -> str:
    """Qwen 富语义：User clarification + nl_span/type/interpretation/snippet（snippet 带引号转义）。"""
    items: list[dict[str, Any]] = []
    if pick:
        for tok in pick.tokens:
            if tok.abstain:
                continue
            ambig_type = (getattr(tok, "ambig_type", None) or "").strip()
            snip = render_mapping_snippet(ambig_type, tok.chosen)
            items.append({
                "nl_span": tok.token,
                "type": ambig_type,
                "interpretation": (getattr(tok, "interpretation", None) or "").strip(),
                "mapping_snippet": snip,
            })
    if not items:
        return "User clarification: {}"
    return "User clarification: " + json.dumps(items, ensure_ascii=False)


def evidence_dump(
    pick: Optional[PickResult],
    *,
    parser: str = "base",
    pack: str | None = None,
) -> str:
    if rewrite_pack_for(parser, pack) == "qmap":
        return evidence_dump_qmap(pick)
    return evidence_dump_verbose(pick)


def merge_evidence(*parts: Optional[str]) -> str:
    return "\n".join(p.strip() for p in parts if p and str(p).strip())


def apply_rewrite(
    mode: str,
    *,
    question: str,
    schema_str: str,
    schema_map: dict[str, list[str]],
    mapping: Any,
    pick: Optional[PickResult],
    evidence: str = "",
    schema_formatter=None,
    parser: str = "base",
    pack: str | None = None,
) -> tuple[str, str, str]:
    mode = (mode or "none").strip().lower()
    if mode in {"", "none"}:
        return question, schema_str, evidence or ""
    if mode == "schema_dq":
        q = rewrite_question_schema_dq(question, mapping, pick)
        dropped = drop_unselected_columns(schema_map, mapping, pick)
        fmt = schema_formatter or _schema_to_text
        return q, fmt(dropped), evidence or ""
    if mode == "schema_dqg":
        dropped = drop_unselected_columns(schema_map, mapping, pick)
        if _schema_map_equal(schema_map, dropped):
            return question, schema_str, evidence or ""
        q = rewrite_question_schema_dq(question, mapping, pick)
        fmt = schema_formatter or _schema_to_text
        return q, fmt(dropped), evidence or ""
    if mode == "schema_q":
        q = rewrite_question_schema_dq(question, mapping, pick)
        return q, schema_str, evidence or ""
    if mode == "ambisql":
        return question, schema_str, merge_evidence(evidence, evidence_qa(pick))
    if mode == "evidence":
        dump = evidence_dump(pick, parser=parser, pack=pack)
        return question, schema_str, merge_evidence(evidence, dump)
    raise ValueError(f"unknown rewrite mode {mode!r}; use schema_dq|schema_dqg|schema_q|ambisql|evidence|none")


def _schema_to_text(schema_map: dict[str, list[str]]) -> str:
    lines = []
    for i, (table, cols) in enumerate(schema_map.items(), 1):
        lines.append(f"[{i}] {table} : " + " , ".join(cols))
    return "\n".join(lines)


def _self_test() -> None:
    from .human_simulator.official_clear import PickResult, TokenPick

    schema = {"head": ["name", "title"], "dept": ["name"]}
    mapping = {
        "query": {},
        "match": {"name": [{"head": ["name"]}, {"head": ["title"]}]},
    }
    pick = PickResult(
        simulator="test",
        tokens=[TokenPick(
            "name", "schema", 0, {"head": ["title"]}, False, "test",
            ambig_type="Column",
            interpretation="Use the professional job title of the department head.",
            clarification_question="Which attribute should represent the head name?",
        )],
        ambiguity_clarification={"name": {"head": ["title"]}},
    )
    q, s, e = apply_rewrite(
        "schema_dq",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
    )
    assert "name (head.title)" in q, q
    assert "title" in s and "head : name" not in s.replace("title", ""), s
    assert "dept" in s, s
    assert e == ""

    qk, sk, ek = apply_rewrite(
        "schema_q",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
    )
    assert qk == q
    assert sk == _schema_to_text(schema)
    assert "head : name" in sk and "title" in sk
    assert ek == ""

    qg, sg, eg = apply_rewrite(
        "schema_dqg",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
    )
    assert qg == q and sg == s and eg == ""
    qg2, sg2, _ = apply_rewrite(
        "schema_dqg",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping={"query": {}, "match": {"name": [{"head": ["name"]}, {"head": ["title"]}, {"head": ["name", "title"]}]}},
        pick=PickResult(
            simulator="test",
            tokens=[TokenPick("name", "schema", 0, {"head": ["name", "title"]}, False, "test")],
            ambiguity_clarification={"name": {"head": ["name", "title"]}},
        ),
    )
    assert qg2 == "list the name" and sg2 == _schema_to_text(schema)

    q2, s2, e2 = apply_rewrite(
        "ambisql",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
        evidence="orig",
    )
    assert q2 == "list the name"
    assert s2 == _schema_to_text(schema)
    assert "Q: name" in e2 and "head" in e2

    q3, s3, e3 = apply_rewrite(
        "evidence",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
        parser="base",
    )
    assert q3 == "list the name" and s3 == _schema_to_text(schema)
    assert e3.startswith("User clarification:")
    assert "nl_span" in e3 and "interpretation" in e3 and "head.title" in e3
    assert "Use the professional job title" in e3
    assert '"Q"' not in e3

    q4, _, e4 = apply_rewrite(
        "evidence",
        question="list the name",
        schema_str=_schema_to_text(schema),
        schema_map=schema,
        mapping=mapping,
        pick=pick,
        parser="deepeye",
    )
    assert q4 == "list the name"
    assert "User clarification:" not in e4
    assert '"Q"' in e4 and "head.title" in e4
    assert "Which attribute should represent the head name?" in e4
    assert "interpretation" not in e4 and "nl_span" not in e4

    empty = evidence_dump_verbose(PickResult(simulator="test", tokens=[]))
    assert empty == "User clarification: {}"
    assert rewrite_pack_for("base") == "verbose"
    assert rewrite_pack_for("deepeye") == "qmap"
    assert _table_col_keys({"customers.Currency": "Currency"}) == ["customers.Currency"]
    assert render_mapping_snippet("Project", {"customers.Currency": "Currency"}) == "customers.Currency"
    assert quote_table_col("customers.Currency.Currency") == "customers.Currency"
    assert render_mapping_snippet("Column", {"legalities.format": ["commander", "duel"]}) == "legalities.format"
    assert render_mapping_snippet("Column", {"frpm": ["Free Meal Count (Ages 5-17)"]}) == 'frpm."Free Meal Count (Ages 5-17)"'
    assert 'frpm."Enrollment (K-12)"' == render_mapping_snippet("Aggregate", {"frpm": ["Enrollment (K-12)"]})
    assert "East Bohemia" in str(render_mapping_snippet("Value", {"district.A3": "East Bohemia"}))
    quoted = evidence_dump_verbose(PickResult(
        simulator="test",
        tokens=[TokenPick(
            "eligible free rate", "schema", 0, {"frpm": ["Free Meal Count (Ages 5-17)"]}, False, "test",
            ambig_type="Aggregate",
            interpretation="Map to frpm free-meal count.",
        )],
    ))
    body = json.loads(quoted.split("User clarification:", 1)[1].strip())
    assert body[0]["mapping_snippet"] == 'frpm."Free Meal Count (Ages 5-17)"'
    assert body[0]["nl_span"] == "eligible free rate"
    print("rewrite self-test ok")


if __name__ == "__main__":
    _self_test()
