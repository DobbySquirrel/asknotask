#!/usr/bin/env python3
"""用现成 pred 的冻 φ，对指定类型跑 Difference，再全问剩余 ≥2、重解析、打 EX。

默认跑 Attachment 和 Scope。Scope 会先判断是不是真的对比，不适合或拿不准就继续问。
默认拿 outputs/bird_arcwise/detection/forward（可传 score_paper.json 或 pred.jsonl）。
默认是 Difference + Fidelity；加 --fidelity off 可跑 Difference only。

  python pipeline/checks/run_diff_checks.py --pred outputs/bird_arcwise/detection/forward/score_paper.json
  python pipeline/checks/run_diff_checks.py --pred outputs/bird_arcwise/detection/forward/score_paper.json --fidelity off
  python pipeline/checks/run_diff_checks.py --fidelity off --types Attachment,Scope
  python pipeline/checks/run_diff_checks.py --types Attachment,Scope --out outputs/bird_arcwise/checks/diff
  python pipeline/checks/run_diff_checks.py --limit 8 --ids bird:1482

输出（不要覆盖 detection/forward）：
  check_diff_att_on_none/              # Attachment + Fidelity
  check_diff_att_only_on_none/         # Attachment only
  check_diff_att_scope_only_on_none/   # Attachment+Scope, Difference only
    pred.jsonl  score_paper.json  summary.json
"""
from __future__ import annotations

from collections import Counter
import json
import sys
import time
from pathlib import Path

ASK = Path(__file__).resolve().parents[2]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))

from pipeline.checks.difference import TARGET_TYPES, apply_difference
from pipeline.checks.runtime import (
    ask_and_reparse,
    format_parser,
    open_frozen_run,
    parse_flag_args,
    resolve_baseline_score,
    score_against_baseline,
)

CHECKS = Path(__file__).resolve().parent
PROMPTS = CHECKS / "prompts"
OUT_ROOT = ASK / "outputs" / "bird_arcwise" / "checks"

TYPE_ABBREV = {
    "Attachment": "att",
    "Scope": "scope",
    "Aggregate": "agg",
    "Project": "proj",
    "Tie": "tie",
    "Column": "col",
    "Value": "val",
    "Join": "join",
}


def type_tag(target_types: set[str]) -> str:
    parts = [TYPE_ABBREV.get(t, t.lower()) for t in sorted(target_types)]
    return "_".join(parts) or "att"


def arm_name(use_fidelity: bool, target_types: set[str] | None = None) -> str:
    types = set(target_types or TARGET_TYPES)
    tag = type_tag(types)
    gate = "_gate" if "Scope" in types else ""
    return f"check_diff_{tag}{gate}_on_none" if use_fidelity else f"check_diff_{tag}{gate}_only_on_none"


def default_out(use_fidelity: bool, target_types: set[str] | None = None) -> Path:
    return OUT_ROOT / arm_name(use_fidelity, target_types)


def _reuse_baseline(gold, snap, phi_prime, types, interps, traces, n_dropped, n_att, use_fidelity: bool = True, target_types: set[str] | None = None, n_resolved: int = 0) -> dict:
    arm = arm_name(use_fidelity, target_types)
    src = dict(snap.get("source_row") or {})
    src.update({
        "id": gold.id,
        "db_id": getattr(gold, "db_id", src.get("db_id")),
        "system": arm,
        "pipeline": arm,
        "parser": src.get("parser") or "qwen_coder",
        "question_out": snap.get("question_out") or src.get("question_out"),
        "schema_out": snap.get("schema_out") or src.get("schema_out"),
        "evidence_out": snap.get("evidence_out") or src.get("evidence_out"),
        "predicted_sql": snap.get("baseline_sql") or src.get("predicted_sql") or "",
        "n_asked": snap.get("baseline_n_asked", src.get("n_asked") or 0),
        "n_probes": n_att,
        "n_healed": n_dropped,
        "n_resolved": n_resolved,
        "no_qc": True,
        "check": "difference_attachment",
        "baseline_n_asked": snap.get("baseline_n_asked"),
        "meta": {
            "phi": snap.get("phi"),
            "phi_prime": phi_prime,
            "span_types": types,
            "span_interps": interps,
            "check_trace": traces,
            "n_probes": n_att,
            "n_healed": n_dropped,
            "n_resolved": n_resolved,
            "reused_baseline_sql": True,
            "source_pred": "detection/forward",
            "difference": "pipeline/checks/difference.py",
            "fidelity": use_fidelity,
        },
        "align": "diff_on_forward",
        "fidelity": use_fidelity,
    })
    return src


def _run_changed(gold, snap, llm, format_parser_base, phi_prime, traces, n_dropped, use_fidelity: bool = True, target_types: set[str] | None = None, n_resolved: int = 0, healed: dict | None = None) -> dict:
    types = dict(snap.get("span_types") or {})
    interps = dict(snap.get("span_interps") or {})
    parsed = ask_and_reparse(gold, llm, format_parser_base, phi_prime, types, interps, healed=healed or {})
    arm = arm_name(use_fidelity, target_types)
    return {
        "id": gold.id,
        "db_id": getattr(gold, "db_id", None),
        "system": arm,
        "pipeline": arm,
        "parser": "qwen_coder",
        "question_out": parsed["question_out"],
        "schema_out": parsed["schema_out"],
        "evidence_out": parsed["evidence_out"],
        "predicted_sql": parsed["predicted_sql"],
        "n_asked": parsed["n_asked"],
        "n_probes": sum(1 for t in traces),
        "n_healed": n_dropped,
        "n_resolved": n_resolved,
        "no_qc": True,
        "check": "difference_attachment",
        "baseline_n_asked": snap.get("baseline_n_asked"),
        "meta": {
            "phi": snap.get("phi"),
            "phi_prime": phi_prime,
            "span_types": types,
            "span_interps": interps,
            "check_trace": traces,
            "n_probes": sum(1 for t in traces),
            "n_healed": n_dropped,
            "n_resolved": n_resolved,
            "healed": healed or {},
            "reused_baseline_sql": False,
            "source_pred": "detection/forward",
            "difference": "pipeline/checks/difference.py",
            "fidelity": use_fidelity,
        },
        "align": "diff_on_forward",
        "fidelity": use_fidelity,
    }


def _run_one(gold, snap, llm, format_parser_base, probe_tpl, check_tpl, use_fidelity: bool = True, target_types: set[str] | None = None, gate_tpl: str | None = None) -> dict:
    types = dict(snap.get("span_types") or {})
    interps = dict(snap.get("span_interps") or {})
    healed: dict = {}
    phi_prime, traces, n_dropped = apply_difference(
        gold,
        snap.get("phi") or {},
        types,
        llm,
        probe_tpl=probe_tpl,
        check_tpl=check_tpl,
        use_fidelity=use_fidelity,
        target_types=target_types,
        healed=healed,
        gate_tpl=gate_tpl,
    )
    n_att = len(traces)
    n_resolved = sum(1 for t in traces if t.get("action") == "resolve")
    if n_dropped == 0 and n_resolved == 0:
        return _reuse_baseline(gold, snap, phi_prime, types, interps, traces, n_dropped, n_att, use_fidelity=use_fidelity, target_types=target_types, n_resolved=n_resolved)
    return _run_changed(gold, snap, llm, format_parser_base, phi_prime, traces, n_dropped, use_fidelity=use_fidelity, target_types=target_types, n_resolved=n_resolved, healed=healed)


def _trace_counts(pred: Path) -> dict:
    reasons: Counter = Counter()
    by_type: dict[str, Counter] = {}
    drops = resolved = cards = 0
    for line in pred.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for tr in (row.get("meta") or {}).get("check_trace") or []:
            typ = str(tr.get("type") or "unknown")
            bag = by_type.setdefault(typ, Counter())
            cards += 1
            bag["cards"] += 1
            reason = str(tr.get("reason") or "unknown")
            reasons[reason] += 1
            bag[reason] += 1
            if tr.get("action") == "drop":
                drops += 1
                bag["dropped"] += 1
            elif tr.get("action") == "resolve":
                resolved += 1
                bag["resolved"] += 1
    return {
        "cards": cards,
        "attachment_cards": cards,
        "dropped": drops,
        "resolved": resolved,
        "reasons": dict(reasons),
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
    }


def run_difference(
    *,
    pred_path: Path,
    baseline_score_path: Path | None,
    out_dir: Path,
    limit: int | None,
    ids: list[str],
    resume: bool,
    use_fidelity: bool = True,
    target_types: set[str] | None = None,
) -> None:
    pred_path, frozen, golds, work, out_pred = open_frozen_run(
        pred_path=pred_path, out_dir=out_dir, ids=ids, limit=limit, resume=resume,
    )
    if baseline_score_path is None:
        baseline_score_path = resolve_baseline_score(pred_path, None)

    probe_tpl = (PROMPTS / "difference_probe.md").read_text(encoding="utf-8")
    check_tpl = (PROMPTS / "difference_check.md").read_text(encoding="utf-8")
    gate_tpl = (PROMPTS / "difference_scope_gate.md").read_text(encoding="utf-8")
    if "{options}" not in probe_tpl or "{candidate_sql_pairs}" not in check_tpl:
        raise SystemExit("prompt templates missing required slots")
    if not gate_tpl or "{options}" not in gate_tpl:
        raise SystemExit("scope gate prompt missing required slots")
    print(
        f"[data] golds={len(golds)} freeze={len(frozen)} todo={len(work)} "
        f"resume={resume} fidelity={use_fidelity} types={sorted(target_types or TARGET_TYPES)} "
        f"out={out_dir}",
        flush=True,
    )

    from utils.llm import LLM

    llm = LLM()
    print(f"[llm] {llm.model} @ {llm.url}", flush=True)
    fmt = format_parser("diff")

    t0 = time.time()
    n_new = 0
    with out_pred.open("a", encoding="utf-8") as f:
        for i, gold in enumerate(work, 1):
            print(f"[diff {i}/{len(work)}] {gold.id}", flush=True)
            row = _run_one(gold, frozen[gold.id], llm, fmt, probe_tpl, check_tpl, use_fidelity=use_fidelity, target_types=target_types, gate_tpl=gate_tpl)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
            dropped = row.get("n_healed") or 0
            n_cards = row.get("n_probes") or 0
            print(
                f"  cards={n_cards} dropped={dropped} "
                f"resolved={row.get('n_resolved') or 0} "
                f"n_asked={row['n_asked']} (base={row.get('baseline_n_asked')}) "
                f"reused={row.get('meta', {}).get('reused_baseline_sql')}",
                flush=True,
            )
    print(f"[done] new={n_new} elapsed={(time.time()-t0)/60:.1f}min", flush=True)

    metrics, base, delta = score_against_baseline(
        "bird_arcwise", out_pred, out_dir, baseline_score_path,
    )
    traces = _trace_counts(out_pred)
    arm = arm_name(use_fidelity, target_types)
    gate_stats = {"probe": 0, "keep": 0, "labels": {}}
    if out_pred.is_file():
        from collections import Counter
        labels = Counter()
        for line in out_pred.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for tr in (row.get("meta") or {}).get("check_trace") or []:
                if tr.get("type") != "Scope" or not isinstance(tr.get("gate"), dict):
                    continue
                dec = tr["gate"].get("decision")
                if dec == "probe":
                    gate_stats["probe"] += 1
                else:
                    gate_stats["keep"] += 1
                lab = str(tr["gate"].get("label") or "unknown")
                labels[lab] += 1
        gate_stats["labels"] = dict(labels)
    summary = {
        "arm": arm,
        "fidelity": use_fidelity,
        "target_types": sorted(target_types or TARGET_TYPES),
        "scope_gate_stats": gate_stats,
        "source_pred": str(pred_path),
        "baseline_score": str(baseline_score_path) if baseline_score_path else None,
        "baseline": base,
        "difference": metrics,
        "cards": traces,
        "delta_ex": delta,
        "prompts": {
            "generator": str(PROMPTS / "difference_probe.md"),
            "verifier": str(PROMPTS / "difference_check.md"),
            "scope_gate": str(PROMPTS / "difference_scope_gate.md"),
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(
        f"[ex {arm}] n={metrics.get('n')} EX={metrics.get('ex')} "
        f"n_hit={metrics.get('n_hit')} Q={metrics.get('Q')} "
        f"base_EX={base.get('ex')} ΔEX={summary.get('delta_ex')} "
        f"cards={traces.get('cards')} dropped={traces.get('dropped')} resolved={traces.get('resolved')} by_type={traces.get('by_type')}",
        flush=True,
    )


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in {"-h", "--help"}:
        print(__doc__)
        raise SystemExit(0)

    extra = args
    if extra and not extra[0].startswith("-"):
        # allow a dummy subcommand like run_ext_checks, but ignore it
        extra = extra[1:]

    def _parse_fidelity(val: str) -> bool:
        flag = val.strip().lower()
        if flag in {"on", "true", "1", "yes"}:
            return True
        if flag in {"off", "false", "0", "no"}:
            return False
        raise SystemExit("use --fidelity on or --fidelity off")

    def _parse_types(val: str) -> set[str]:
        types = {x.strip() for x in val.split(",") if x.strip()}
        if not types:
            raise SystemExit("--types needs at least one type")
        return types


    parsed = parse_flag_args(
        extra,
        extras={
            "--fidelity": ("use_fidelity", 1, _parse_fidelity),
            "--types": ("target_types", 1, _parse_types),
        },
    )
    use_fidelity = parsed.get("use_fidelity", True)
    target_types = parsed.get("target_types") or set(TARGET_TYPES)
    out = parsed["out"] if parsed["out"] is not None else default_out(use_fidelity, target_types)
    run_difference(
        pred_path=parsed["pred"],
        baseline_score_path=parsed["baseline"],
        out_dir=out,
        limit=parsed["limit"],
        ids=parsed["ids"],
        resume=parsed["resume"],
        use_fidelity=use_fidelity,
        target_types=target_types,
    )


if __name__ == "__main__":
    main()
