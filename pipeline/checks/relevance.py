# SOURCE: extracted from pipeline/checks/run_relevance_checks.py
"""Relevance check：对 Aggregate / Project / Tie / Attachment，
把每个候选写成澄清后再解析执行，并与未澄清 baseline 比结果。

对外入口是 `apply_relevance()`，返回 (phi_prime, traces, n_dropped, baseline_exec)。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pipeline.checks.runtime import (
    gold_evidence,
    json_canonical as _canonical,
    resolve_db_path,
    run_sql_with_repair,
    sqls_literally_same,
)

TARGET_TYPES = {"Aggregate", "Project", "Tie", "Attachment"}
DEFAULT_PROBES_PER_CANDIDATE = 1


def _complete(llm, prompt: str, max_tokens: int = 2048) -> str:
    fn = llm.complete
    try:
        return fn(prompt, max_tokens=max_tokens) or ""
    except TypeError:
        return fn(prompt) or ""

def _display_span(span: str) -> str:
    if "\n[" in (span or "") and span.endswith("]"):
        return span.split("\n[", 1)[0]
    return span

def _snippet(typ: str, candidate) -> object:
    try:
        from simulator.compose import render_mapping_snippet
        snip = render_mapping_snippet(typ, candidate)
        if snip is None or snip == "" or snip == []:
            return str(candidate)
        return snip
    except Exception:
        return str(candidate)

def compose_one(evidence: str, span: str, typ: str, candidate) -> str:
    entry = {
        "nl_span": _display_span(span),
        "type": typ,
        "interpretation": str(candidate),
        "mapping_snippet": _snippet(typ, candidate),
    }
    clar = "User clarification: " + json.dumps([entry], ensure_ascii=False)
    prefix = (evidence or "").strip()
    return f"{prefix}\n{clar}" if prefix else clar

def parse_one(llm, format_parser_base, schema: str, question: str, evidence: str) -> str:
    from utils.llm import parse_sql

    prompt = format_parser_base(schema or "", question or "", evidence or "")
    return (parse_sql(_complete(llm, prompt, 2048)) or "").strip()

def slim_exec(ex: dict) -> dict:
    return {k: v for k, v in ex.items() if k not in {"rows"}}


def _probe_role(rec: dict, baseline: dict) -> str:
    if rec.get("identical_to_baseline"):
        return "not_written_in"
    if rec.get("error") == "empty_sql" or not rec.get("sql"):
        return "empty"
    if rec.get("truncated"):
        return "truncated"
    if not rec.get("ok"):
        return "failed"
    if rec.get("vacuous"):
        return "vacuous"
    if rec.get("fingerprint") != baseline.get("fingerprint"):
        return "differs"
    return "equal"


def decide_relevance_card(
    *,
    span: str,
    cands: list,
    typ: str,
    evidence: str,
    schema: str,
    question: str,
    db_path: Path | None,
    llm,
    format_parser_base,
    baseline: dict,
    n_probes: int = DEFAULT_PROBES_PER_CANDIDATE,
) -> dict:
    result = {
        "stage": "relevance",
        "span": span,
        "type": typ,
        "action": "keep",
        "n_candidates": len(cands),
        "n_probes_per_candidate": n_probes,
        "baseline_sql": (baseline or {}).get("sql"),
        "baseline_fingerprint": (baseline or {}).get("fingerprint"),
        "baseline_error": (baseline or {}).get("error"),
        "baseline_ok": bool((baseline or {}).get("ok")),
        "baseline_repaired": bool((baseline or {}).get("repaired")),
        "baseline_unquoted": bool((baseline or {}).get("unquoted")),
        "queries": [],
    }
    if not baseline or not baseline.get("ok"):
        result["reason"] = "unclarified_query_failed"
        return result
    if baseline.get("vacuous"):
        result["reason"] = "empty_or_all_null_uninformative"
        result["vacuous_kind"] = baseline.get("vacuous_kind")
        return result
    if db_path is None:
        result["reason"] = "missing_database"
        return result

    encoded = { _canonical(c): compose_one(evidence, span, typ, c) for c in cands }
    if len(set(encoded.values())) < len(encoded):
        result["reason"] = "clarification_encoding_collision"
        result["encoded_evidence"] = list(encoded.values())
        return result

    role_counts: Counter = Counter()
    cand_has_equal: list[bool] = []
    any_differs = False

    for cand in cands:
        clarified = compose_one(evidence, span, typ, cand)
        probes = []
        has_equal = False
        for attempt in range(max(1, int(n_probes))):
            sql = parse_one(llm, format_parser_base, schema, question, clarified)
            rec: dict = {"attempt": attempt, "sql": sql, "evidence": clarified}
            if not sql:
                rec.update({"ok": False, "error": "empty_sql"})
            elif sqls_literally_same(sql, baseline.get("sql") or ""):
                rec["identical_to_baseline"] = True
                rec["ok"] = True
            else:
                execution = run_sql_with_repair(
                    db_path,
                    sql,
                    llm,
                    schema=schema,
                    question=question,
                    evidence=clarified,
                )
                rec.update(slim_exec({k: v for k, v in execution.items() if k != "sql"}))
                rec["sql"] = execution.get("sql") or sql
                rec["original_sql"] = execution.get("original_sql") or sql
                if sqls_literally_same(rec["sql"], baseline.get("sql") or ""):
                    rec["identical_to_baseline"] = True
            rec["role"] = _probe_role(rec, baseline)
            probes.append(rec)
            role_counts[rec["role"]] += 1
            if rec["role"] == "equal":
                has_equal = True
            elif rec["role"] == "differs":
                any_differs = True
        cand_has_equal.append(has_equal)
        result["queries"].append({
            "candidate": cand,
            "evidence": clarified,
            "probes": probes,
        })

    result["probe_roles"] = dict(role_counts)
    result["n_faithful_equal"] = role_counts["equal"]
    result["n_faithful_differs"] = role_counts["differs"]

    if any_differs:
        result["reason"] = "a_probe_differs_from_unclarified"
        return result
    if cand_has_equal and all(cand_has_equal):
        result["action"] = "drop"
        result["reason"] = "all_faithful_probes_results_equal"
        return result

    if role_counts["truncated"]:
        result["reason"] = "result_truncated"
    elif not role_counts["equal"] and (role_counts["failed"] or role_counts["empty"]):
        result["reason"] = "probe_execution_failed" if role_counts["failed"] else "probe_sql_empty"
    elif role_counts["vacuous"] and not role_counts["equal"]:
        result["reason"] = "empty_or_all_null_uninformative"
        kinds = [
            p.get("vacuous_kind")
            for q in result["queries"]
            for p in q.get("probes") or []
            if p.get("role") == "vacuous"
        ]
        result["vacuous_kind"] = next((k for k in kinds if k), None)
    elif role_counts["not_written_in"] and not all(cand_has_equal):
        result["reason"] = "clarification_not_written_in"
    else:
        result["reason"] = "insufficient_faithful_probes"
    return result


def apply_relevance(
    gold,
    phi: dict[str, list],
    span_types: dict[str, str],
    llm,
    format_parser_base,
    *,
    target_types: set[str] | None = None,
    evidence: str | None = None,
    n_probes: int = DEFAULT_PROBES_PER_CANDIDATE,
) -> tuple[dict, list, int, dict]:
    """返回 (phi_prime, traces, n_dropped, baseline_exec)。"""
    from schema_text import schema_clear_text, schema_map_for_prompt

    types = dict(span_types or {})
    phi_prime = {k: list(v) for k, v in (phi or {}).items()}
    question = gold.question or ""
    schema = schema_clear_text(schema_map_for_prompt(gold))
    ev = gold_evidence(gold) if evidence is None else evidence
    db_path = resolve_db_path(gold)
    wanted = set(target_types) if target_types is not None else set(TARGET_TYPES)
    n_probes = max(1, int(n_probes))

    work = []
    for span, cands in phi_prime.items():
        typ = str(types.get(span) or "")
        if typ in wanted and isinstance(cands, list) and len(cands) >= 2:
            work.append((span, cands, typ))

    baseline = {"ok": False, "sql": ""}
    if work:
        if db_path is None:
            baseline = {"ok": False, "sql": "", "error": "missing_database"}
        else:
            bsql = parse_one(llm, format_parser_base, schema, question, ev)
            if not bsql:
                bsql = parse_one(llm, format_parser_base, schema, question, ev)
            if not bsql:
                baseline = {"ok": False, "sql": "", "error": "empty_sql"}
            else:
                baseline = run_sql_with_repair(
                    db_path, bsql, llm, schema=schema, question=question, evidence=ev or "",
                )
                if not baseline.get("sql"):
                    baseline["sql"] = baseline.get("original_sql") or bsql

    traces = []
    n_dropped = 0
    for span, cands, typ in work:
        trace = decide_relevance_card(
            span=span,
            cands=cands,
            typ=typ,
            evidence=ev,
            schema=schema,
            question=question,
            db_path=db_path,
            llm=llm,
            format_parser_base=format_parser_base,
            baseline=baseline,
            n_probes=n_probes,
        )
        traces.append(trace)
        if trace.get("action") == "drop":
            phi_prime.pop(span, None)
            n_dropped += 1
    return phi_prime, traces, n_dropped, slim_exec(baseline)
