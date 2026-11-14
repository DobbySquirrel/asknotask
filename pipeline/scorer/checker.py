#!/usr/bin/env python3
"""Independent label checker.

Inputs are the question, the gold SQL, and the candidates. No schema.
Returns the candidates whose claim is realized by the gold SQL.
Others only when none are.
"""
from __future__ import annotations

import ast
import json
import re
from functools import lru_cache

import sqlglot
from sqlglot import exp

QUOTE = re.compile(r"'([^']*)'|\"([^\"]*)\"")


def choose(question: str, gold_sql: str, cands: list) -> list[int]:
    """Indices consistent with the gold SQL. Empty means Others."""
    del question  # the decision is the gold SQL against the candidates
    gold = _gold(gold_sql or "")
    if gold is None:
        return []
    parsed = [_claim(c) for c in cands]
    if not any(p["kind"] != "empty" for p in parsed):
        return []
    hit = [i for i, claim in enumerate(parsed) if _supports(claim, gold)]
    if parsed and all(p["kind"] == "cols" for p in parsed):
        hit = _projection(hit, parsed, gold)
    return hit


@lru_cache(maxsize=8192)
def _gold(sql: str):
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return None
    if tree is None:
        return None
    strings = set()
    numbers = set()
    for lit in tree.find_all(exp.Literal):
        if lit.is_string:
            strings.add(str(lit.this))
        else:
            numbers.add(_num(lit.this))
    columns = set()
    for col in tree.find_all(exp.Column):
        if col.name:
            columns.add(col.name.lower())
    select_cols = set()
    select_star = False
    for item in tree.selects if isinstance(tree, exp.Select) else []:
        node = item.this if isinstance(item, exp.Alias) else item
        if isinstance(node, exp.Column) and node.name:
            select_cols.add(node.name.lower())
        elif isinstance(node, exp.Star):
            select_star = True
    distinct_cols = set()
    plain_cols = set()
    count_star = False
    for node in tree.find_all(exp.Count):
        star = node.find(exp.Star) is not None and not list(node.find_all(exp.Column))
        cols = {c.name.lower() for c in node.find_all(exp.Column) if c.name}
        if node.args.get("distinct"):
            if star:
                distinct_cols.add("*")
            distinct_cols |= cols
        else:
            if star or not cols:
                count_star = True
            plain_cols |= cols
    sum_case_one = False
    for node in tree.find_all(exp.Sum):
        if node.find(exp.Case) and "1" in {_num(lit.this) for lit in node.find_all(exp.Literal) if not lit.is_string}:
            sum_case_one = True
    return {
        "strings": strings,
        "numbers": numbers,
        "columns": columns,
        "select_cols": select_cols,
        "select_star": select_star,
        "distinct_cols": distinct_cols,
        "plain_cols": plain_cols,
        "count_star": count_star,
        "sum_case_one": sum_case_one,
    }


def _num(text) -> str:
    raw = str(text).strip()
    try:
        value = float(raw)
    except ValueError:
        return raw
    if value.is_integer():
        return str(int(value))
    return str(value)


def _obj(cand):
    if isinstance(cand, str):
        text = cand.strip()
        if text[:1] in "{[":
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                try:
                    return ast.literal_eval(text)
                except (SyntaxError, ValueError):
                    return cand
        return cand
    return cand


def _is_expr(text: str) -> bool:
    body = text.strip()
    if "(" in body or ")" in body:
        return True
    if re.search(r"[=<>/*+]|(?<![\w])-(?![\w])", body):
        return True
    return False


def _claim(cand) -> dict:
    obj = _obj(cand)
    if isinstance(obj, dict):
        lits = []
        cols = []
        exprs = []
        for key, val in obj.items():
            qualified = "." in str(key)
            seq = val if isinstance(val, list) else [val]
            for item in seq:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    lits.append(_num(item))
                    continue
                if not isinstance(item, str):
                    continue
                piece = item.strip()
                if not piece:
                    continue
                if _is_expr(piece):
                    exprs.append(piece)
                elif isinstance(val, list) and re.fullmatch(r"[A-Za-z_][\w]*|\*", piece):
                    cols.append(piece)
                elif not isinstance(val, list) and qualified:
                    lits.append(piece)
                elif re.fullmatch(r"[A-Za-z_][\w]*|\*", piece):
                    cols.append(piece)
                else:
                    lits.append(piece)
        if exprs:
            return {"kind": "expr", "exprs": exprs, "lits": lits, "cols": cols}
        if cols and not lits:
            return {"kind": "cols", "cols": cols}
        if lits and not cols:
            return {"kind": "lits", "lits": lits}
        if lits or cols:
            return {"kind": "mix", "lits": lits, "cols": cols, "exprs": exprs}
        return {"kind": "empty"}
    if isinstance(obj, str):
        found = [a or b for a, b in QUOTE.findall(obj)]
        return {"kind": "nl", "text": obj, "lits": found}
    return {"kind": "empty"}


def _supports(claim: dict, gold: dict) -> bool:
    kind = claim["kind"]
    if kind == "lits":
        return bool(claim["lits"]) and all(_lit_in(v, gold) for v in claim["lits"])
    if kind == "cols":
        return _cols_in(claim["cols"], gold)
    if kind == "expr":
        return all(_expr_in(e, gold) for e in claim["exprs"]) and all(_lit_in(v, gold) for v in claim["lits"])
    if kind == "mix":
        ok = True
        if claim["lits"]:
            ok = ok and all(_lit_in(v, gold) for v in claim["lits"])
        if claim["cols"]:
            ok = ok and _cols_in(claim["cols"], gold)
        if claim["exprs"]:
            ok = ok and all(_expr_in(e, gold) for e in claim["exprs"])
        return ok and (claim["lits"] or claim["cols"] or claim["exprs"])
    if kind == "nl":
        lits = claim["lits"]
        return bool(lits) and all(_lit_in(v, gold) for v in lits)
    return False


def _lit_in(value: str, gold: dict) -> bool:
    if value in gold["strings"]:
        return True
    num = _num(value)
    return num in gold["numbers"] and re.fullmatch(r"-?\d+(\.\d+)?", value.strip()) is not None


def _cols_in(cols: list[str], gold: dict) -> bool:
    if not cols:
        return False
    for col in cols:
        if col == "*":
            if not gold["select_star"]:
                return False
            continue
        if col.lower() not in gold["columns"]:
            return False
    return True


def _expr_in(text: str, gold: dict) -> bool:
    try:
        node = sqlglot.parse_one(text, read="sqlite")
    except Exception:
        try:
            node = sqlglot.parse_one(f"SELECT {text}", read="sqlite")
        except Exception:
            return False
    if isinstance(node, exp.Select):
        if len(node.selects) != 1:
            return False
        node = node.selects[0]
    cols = [c.name.lower() for c in node.find_all(exp.Column) if c.name]
    lits_s = [str(lit.this) for lit in node.find_all(exp.Literal) if lit.is_string]
    lits_n = [_num(lit.this) for lit in node.find_all(exp.Literal) if not lit.is_string]
    if any(s not in gold["strings"] for s in lits_s):
        return False
    if any(n not in gold["numbers"] for n in lits_n):
        return False
    if any(c not in gold["columns"] for c in cols):
        return False
    counts = list(node.find_all(exp.Count))
    if counts and len(counts) == 1 and not list(node.find_all(exp.Div)):
        return _count_ok(counts[0], gold)
    if counts and node.find(exp.Div):
        return all(_count_ok(c, gold) for c in counts)
    if isinstance(node, exp.Column) or (isinstance(node, exp.Alias) and isinstance(node.this, exp.Column)):
        return True
    if not counts and not lits_n and not lits_s and cols:
        return True
    if lits_s or lits_n or cols:
        return True
    return False


def _count_ok(node: exp.Count, gold: dict) -> bool:
    star = node.find(exp.Star) is not None and not list(node.find_all(exp.Column))
    cols = {c.name.lower() for c in node.find_all(exp.Column) if c.name}
    if node.args.get("distinct"):
        if star:
            return "*" in gold["distinct_cols"]
        return bool(cols) and cols <= gold["distinct_cols"]
    if star or not cols:
        return gold["count_star"] or gold["sum_case_one"]
    return cols <= gold["plain_cols"] or (gold["sum_case_one"] and not gold["distinct_cols"] and not gold["plain_cols"])


def _projection(hit: list[int], parsed: list[dict], gold: dict) -> list[int]:
    if not hit:
        return []
    sets = [{c.lower() for c in parsed[i]["cols"] if c != "*"} for i in range(len(parsed))]
    select = set(gold["select_cols"])
    offered = set()
    for cols in sets:
        offered |= cols
    kept = []
    for i in hit:
        cols = sets[i]
        if "*" in parsed[i]["cols"]:
            kept.append(i)
            continue
        if select and cols < select and (select - offered):
            continue
        kept.append(i)
    if not kept:
        return []
    maximal = []
    for i in kept:
        if any(sets[i] < sets[j] for j in kept if j != i):
            continue
        maximal.append(i)
    return maximal
