# SOURCE: extracted from pipeline/checks/run_diff_checks.py
"""Difference check：对指定类型（默认 Attachment 和 Scope）跑探测 SQL → 执行 →（可选）Fidelity 核对。

对外入口是 `apply_difference()`，签名靠近 `apply_existence()`：
返回 (phi_prime, traces, n_dropped)。探测结果相同时保留其中一条读法，写入 phi（及可选的 healed），不再把 span 从 phi 移除。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pipeline.checks.runtime import (
    _is_readonly_sql,
    gold_evidence,
    json_canonical as _canonical,
    resolve_db_path,
    run_sql_with_repair,
)

CHECKS = Path(__file__).resolve().parent
PROMPTS = CHECKS / "prompts"

TARGET_TYPES = {"Attachment", "Scope"}


def _load_templates() -> tuple[str, str]:
    probe = (PROMPTS / "difference_probe.md").read_text(encoding="utf-8")
    check = (PROMPTS / "difference_check.md").read_text(encoding="utf-8")
    if "{options}" not in probe or "{candidate_sql_pairs}" not in check:
        raise SystemExit("prompt templates missing required slots")
    return probe, check


def _fill(template: str, **slots) -> str:
    text = template
    for key, value in slots.items():
        text = text.replace("{" + key + "}", str(value))
    return text

def _json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text or ""):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
    return {}

def _same_cand(a, b) -> bool:
    return _canonical(a) == _canonical(b)

def _complete(llm, prompt: str, max_tokens: int = 2400) -> str:
    fn = llm.complete
    try:
        return fn(prompt, max_tokens=max_tokens) or ""
    except TypeError:
        return fn(prompt) or ""

_WORD_NUM = (
    r"(?:twenty(?:[-\s](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
    r"|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
    r"|ten|one|two|three|four|five|six|seven|eight|nine)"
)
_ZH_NUM = r"(?:三十|二十|十|一|二|两|三|四|五|六|七|八|九)"


def _mentions_limit(question: str, candidate) -> bool:
    """True if the question or candidate itself asks for a top-N / extreme value.

    Recognizes 'top 10', 'top ten', 'least', 'peak', etc. Does not treat
    'at least' as a limit request.
    """
    blob = f"{question or ''} {_canonical(candidate)}"
    if re.search(
        r"\b(limit|top\s+\d+|first\s+\d+|highest\s+\d+|lowest\s+\d+|前\s*\d+)\b",
        blob, re.I,
    ):
        return True
    if re.search(rf"\b(?:top|first|highest|lowest)\s+{_WORD_NUM}\b", blob, re.I):
        return True
    if re.search(rf"前\s*{_ZH_NUM}", blob):
        return True
    if re.search(r"\b(?:peak|lowest|highest|maximum|minimum|maximal|minimal)\b", blob, re.I):
        return True
    if re.search(r"(?<!\bat\s)\bleast\b", blob, re.I):
        return True
    if re.search(r"\bthe\s+most\b", blob, re.I):
        return True
    return False


PROBE_LABELS = {"each_vs_total", "exclusive_vs_atleast", "one_vs_all", "group_vs_member"}
KEEP_LABELS = {
    "paraphrase", "value_or_threshold", "attachment", "agg_or_project",
    "template_on_filter", "unsure", "other",
}


def evaluate_scope_gate(
    *,
    llm,
    gate_tpl: str,
    question: str,
    evidence: str,
    span: str,
    typ: str,
    cands: list,
) -> dict:
    """Judge whether a Scope card is a real contrast. Fail-open: keep (do not probe)."""
    prompt = _fill(
        gate_tpl,
        question=question or "",
        evidence=evidence or "NULL",
        span=span,
        type=typ,
        options=indexed_options(cands),
    )
    raw = _complete(llm, prompt, 800)
    draft = _json_object(raw)
    decision = str(draft.get("decision") or "").strip().lower()
    label = str(draft.get("label") or "").strip().lower()
    reason = draft.get("reason")
    if not isinstance(reason, str):
        reason = ""
    reason = reason.strip()
    if decision != "probe" or label == "unsure":
        decision = "keep"
        if label not in KEEP_LABELS and label not in PROBE_LABELS:
            label = "unsure" if not label else label
    out = {
        "decision": decision,
        "label": label or "unsure",
        "reason": reason,
        "raw": raw,
    }
    return out

def other_fixed_readings(phi: dict, types: dict, current: str) -> str:
    items = []
    for span, cands in phi.items():
        if span == current:
            continue
        items.append({
            "span": span,
            "type": types.get(span, ""),
            "status": "unresolved" if isinstance(cands, list) and len(cands) >= 2 else "fixed_or_unary",
            "candidates": cands,
            "instruction": (
                "Keep this ambiguity fixed. Do not resolve it differently "
                "across the queries for the current card."
            ),
        })
    return json.dumps(items, ensure_ascii=False, indent=2) if items else "None"

def indexed_options(cands: list) -> str:
    return json.dumps(
        [{"index": i, "candidate": c} for i, c in enumerate(cands)],
        ensure_ascii=False, indent=2,
    )

def parse_queries(draft: dict, cands: list) -> tuple[list | None, str]:
    raw = draft.get("queries")
    if not isinstance(raw, list):
        return None, "invalid_query_plan"
    indexed = {}
    for item in raw:
        if not isinstance(item, dict) or "index" not in item:
            return None, "invalid_query_plan"
        try:
            idx = int(item["index"])
        except (TypeError, ValueError):
            return None, "invalid_query_plan"
        if idx in indexed:
            return None, "duplicate_index"
        indexed[idx] = item
    if set(indexed) != set(range(len(cands))):
        return None, "index_mismatch"
    parsed = []
    for i, cand in enumerate(cands):
        item = indexed[i]
        if "candidate" in item and not _same_cand(item["candidate"], cand):
            return None, "candidate_echo_mismatch"
        sql = item.get("sql")
        if sql is not None and not isinstance(sql, str):
            return None, "invalid_sql"
        if isinstance(sql, str):
            sql = sql.strip()
            if sql == "":
                sql = None
        parsed.append({
            "index": i,
            "candidate": cand,
            "sql": sql,
            "issue": item.get("issue"),
            "implemented_binding": item.get("implemented_binding"),
        })
    return parsed, "ok"

def decide_attachment_card(
    *,
    gold,
    card_span: str,
    cands: list,
    typ: str,
    phi: dict,
    types: dict,
    question: str,
    schema: str,
    evidence: str,
    db_path: Path | None,
    llm,
    probe_tpl: str,
    check_tpl: str,
    use_fidelity: bool = True,
    gate_tpl: str | None = None,
) -> dict:
    result = {
        "span": card_span,
        "type": typ,
        "action": "keep",
        "n_candidates": len(cands),
        "fidelity": use_fidelity,
    }
    if typ == "Scope":
        gate = evaluate_scope_gate(
            llm=llm,
            gate_tpl=gate_tpl or (PROMPTS / "difference_scope_gate.md").read_text(encoding="utf-8"),
            question=question,
            evidence=evidence,
            span=card_span,
            typ=typ,
            cands=cands,
        )
        result["gate"] = {k: gate[k] for k in ("decision", "label", "reason")}
        result["gate_raw"] = gate.get("raw")
        if gate.get("decision") != "probe":
            result["reason"] = "scope_gate_unsure" if gate.get("label") == "unsure" else "scope_gate_keep"
            return result
    if db_path is None:
        result["reason"] = "missing_database"
        return result

    prompt = _fill(
        probe_tpl,
        question=question,
        schema=schema,
        evidence=evidence or "NULL",
        span=card_span,
        type=typ,
        other_fixed_readings=other_fixed_readings(phi, types, card_span),
        options=indexed_options(cands),
    )
    raw_gen = _complete(llm, prompt, 2400)
    draft = _json_object(raw_gen)
    parsed, plan_reason = parse_queries(draft, cands)
    result["generator_raw"] = raw_gen
    result["generator_draft"] = draft
    if parsed is None:
        result["reason"] = plan_reason
        return result
    result["queries"] = [
        {k: q[k] for k in ("index", "candidate", "sql", "issue") if k in q}
        for q in parsed
    ]

    if any(q["sql"] is None or not _is_readonly_sql(q["sql"]) for q in parsed):
        result["reason"] = "invalid_or_unimplementable_sql"
        return result

    unauthorized_limit = [
        q["index"] for q in parsed
        if re.search(r"\bLIMIT\b", q["sql"] or "", re.I)
        and not _mentions_limit(question, q["candidate"])
    ]
    if unauthorized_limit:
        result["reason"] = "result_truncated_or_unauthorized_limit"
        result["unauthorized_limit_indices"] = unauthorized_limit
        return result

    executions = []
    for q in parsed:
        cand_ev = (evidence or "").strip()
        binding = "Candidate to preserve: " + json.dumps(q["candidate"], ensure_ascii=False)
        repair_ev = f"{cand_ev}\n{binding}" if cand_ev else binding
        ex = run_sql_with_repair(
            db_path,
            q["sql"],
            llm,
            schema=schema,
            question=question,
            evidence=repair_ev,
        )
        if ex.get("repaired") or ex.get("unquoted"):
            q["sql"] = ex.get("sql") or q["sql"]
            q["original_sql"] = ex.get("original_sql")
            q["repaired"] = bool(ex.get("repaired"))
            q["unquoted"] = bool(ex.get("unquoted"))
        executions.append(ex)
    result["queries"] = [
        {k: q[k] for k in ("index", "candidate", "sql", "issue", "original_sql", "repaired", "unquoted") if k in q}
        for q in parsed
    ]
    result["executions"] = [
        {k: v for k, v in ex.items() if k not in {"rows"}} for ex in executions
    ]
    if any(ex.get("truncated") or ex.get("error") == "row_limit_exceeded; truncated results cannot establish equality" for ex in executions):
        result["reason"] = "result_truncated_or_unauthorized_limit"
        return result
    if not all(ex.get("ok") for ex in executions):
        result["reason"] = "execution_failed"
        return result

    if any(ex.get("vacuous") for ex in executions):
        result["reason"] = "empty_or_all_null_uninformative"
        result["vacuous_kind"] = next(
            (ex.get("vacuous_kind") for ex in executions if ex.get("vacuous")),
            None,
        )
        return result

    fingerprints = {ex.get("fingerprint") for ex in executions}
    if len(fingerprints) != 1:
        result["reason"] = "results_differ"
        return result

    if not use_fidelity:
        result["action"] = "resolve"
        result["chosen_index"] = 0
        result["healed"] = cands[0]
        result["reason"] = "results_equal_fidelity_skipped"
        return result

    pairs = [
        {"index": q["index"], "candidate": q["candidate"], "sql": q["sql"], "issue": q.get("issue")}
        for q in parsed
    ]
    verify_prompt = _fill(
        check_tpl,
        question=question,
        schema=schema,
        evidence=evidence or "NULL",
        span=card_span,
        type=typ,
        other_fixed_readings=other_fixed_readings(phi, types, card_span),
        candidate_sql_pairs=json.dumps(pairs, ensure_ascii=False, indent=2),
    )
    raw_ver = _complete(llm, verify_prompt, 1600)
    verifier = _json_object(raw_ver)
    result["verifier_raw"] = raw_ver
    result["verifier"] = verifier
    verdicts = {
        int(v["index"]): v
        for v in verifier.get("verdicts") or []
        if isinstance(v, dict) and "index" in v
    }
    if set(verdicts) != set(range(len(cands))):
        result["reason"] = "verifier_index_mismatch"
        return result
    if not all(verdicts[i].get("faithful") is True for i in range(len(cands))):
        result["reason"] = "unfaithful"
        return result

    result["action"] = "resolve"
    result["chosen_index"] = 0
    result["healed"] = cands[0]
    result["reason"] = "all_faithful_and_results_equal"
    return result

def apply_attachment_difference(
    gold, phi, types, llm, question, schema, evidence, probe_tpl, check_tpl,
    use_fidelity: bool = True,
    target_types: set[str] | None = None,
    healed: dict | None = None,
    gate_tpl: str | None = None,
) -> tuple[dict, list, int]:
    phi = {k: list(v) for k, v in (phi or {}).items()}
    types = dict(types or {})
    target_types = set(target_types or TARGET_TYPES)
    db_path = resolve_db_path(gold)
    traces = []
    n_dropped = 0
    for span, cands in list(phi.items()):
        typ = str(types.get(span) or "")
        if typ not in target_types or not isinstance(cands, list) or len(cands) < 2:
            continue
        trace = decide_attachment_card(
            gold=gold,
            card_span=span,
            cands=cands,
            typ=typ,
            phi=phi,
            types=types,
            question=question,
            schema=schema,
            evidence=evidence,
            db_path=db_path,
            llm=llm,
            probe_tpl=probe_tpl,
            check_tpl=check_tpl,
            use_fidelity=use_fidelity,
            gate_tpl=gate_tpl,
        )
        traces.append(trace)
        if trace.get("action") == "resolve" and "healed" in trace:
            phi[span] = [trace["healed"]]
            if healed is not None:
                healed[span] = trace["healed"]
        elif trace.get("action") == "drop":
            phi.pop(span, None)
            n_dropped += 1
    return phi, traces, n_dropped


def apply_difference(
    gold,
    phi: dict[str, list],
    span_types: dict[str, str],
    llm,
    *,
    question: str | None = None,
    schema: str | None = None,
    evidence: str | None = None,
    probe_tpl: str | None = None,
    check_tpl: str | None = None,
    use_fidelity: bool = True,
    target_types: set[str] | None = None,
    healed: dict | None = None,
    gate_tpl: str | None = None,
) -> tuple[dict, list, int]:
    """返回 (phi_prime, traces, n_dropped)。只处理 target_types（默认 Attachment 和 Scope）且候选 ≥2 的卡。

    探测结果相同时 action 为 resolve：phi 里只保留其中一条，并写入 healed（若传入）。
    Scope 卡会先判断候选项是否真是 scope 对比，不适合或不确定则 keep，不探测。
    """
    from schema_text import schema_numbered_rich

    if probe_tpl is None or check_tpl is None:
        default_probe, default_check = _load_templates()
        probe_tpl = probe_tpl or default_probe
        check_tpl = check_tpl or default_check
    if gate_tpl is None:
        gate_tpl = (PROMPTS / "difference_scope_gate.md").read_text(encoding="utf-8")
        if "{options}" not in gate_tpl:
            raise SystemExit("scope gate prompt missing {options}")
    return apply_attachment_difference(
        gold,
        phi,
        span_types,
        llm,
        question if question is not None else (getattr(gold, "question", None) or ""),
        schema if schema is not None else schema_numbered_rich(gold),
        evidence if evidence is not None else gold_evidence(gold),
        probe_tpl,
        check_tpl,
        use_fidelity=use_fidelity,
        target_types=target_types,
        healed=healed,
        gate_tpl=gate_tpl,
    )
