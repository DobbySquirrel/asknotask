#!/usr/bin/env python3
"""用现成 pred 的冻 φ，只对 Aggregate / Project / Tie / Attachment
跑 paper_spec Relevance（encoding_guard 打开），再全问剩余 ≥2、重解析、打 EX。
Scope 不进本臂。

默认拿 outputs/bird_arcwise/detection/forward（可传 score_paper.json 或 pred.jsonl）：

  python pipeline/checks/run_relevance_checks.py \\
      --pred outputs/bird_arcwise/detection/forward/score_paper.json
  python pipeline/checks/run_relevance_checks.py --limit 8 --ids bird:1472

输出（不覆盖 detection/forward 或旧结果）：
  outputs/bird_arcwise/checks/relevance/
    pred.jsonl  score_paper.json  summary.json

每张目标卡：用未澄清 Q/S/E 生成 baseline SQL 并执行（失败则先确定性去引号，再修一轮）。
每个候选默认解析 1 条探测 SQL（可用 --probes 改）；探测失败同样先修一轮。
探测 SQL 与 baseline 字面相同视为没写入澄清，不能作为 drop 证据。
任一忠实探测结果与 baseline 不同则保留；全部候选都跑完再决定，不在第一个
失败或空结果上停。空表或全 NULL 不当成相等。每个候选至少有一条忠实且结果
相同的探测、且没有任何忠实探测不同，才丢掉整张卡。不跑 Fidelity。
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

from pipeline.checks.relevance import DEFAULT_PROBES_PER_CANDIDATE, TARGET_TYPES, apply_relevance
from pipeline.checks.runtime import (
    ask_and_reparse,
    format_parser,
    open_frozen_run,
    parse_flag_args,
    resolve_baseline_score,
    score_against_baseline,
)

ARM = "check_rel_revise_probe_on_none"
OUT_DIR = ASK / "outputs" / "bird_arcwise" / "checks" / "relevance"


def _reuse_baseline(gold, snap, phi_prime, types, interps, traces, n_dropped) -> dict:
    src = dict(snap.get("source_row") or {})
    src.update({
        "id": gold.id,
        "db_id": getattr(gold, "db_id", src.get("db_id")),
        "system": ARM,
        "pipeline": ARM,
        "parser": src.get("parser") or "qwen_coder",
        "question_out": snap.get("question_out") or src.get("question_out"),
        "schema_out": snap.get("schema_out") or src.get("schema_out"),
        "evidence_out": snap.get("evidence_out") or src.get("evidence_out"),
        "predicted_sql": snap.get("baseline_sql") or src.get("predicted_sql") or "",
        "n_asked": snap.get("baseline_n_asked", src.get("n_asked") or 0),
        "n_probes": len(traces),
        "n_healed": n_dropped,
        "no_qc": True,
        "check": "relevance_typed",
        "baseline_n_asked": snap.get("baseline_n_asked"),
        "meta": {
            "phi": snap.get("phi"),
            "phi_prime": phi_prime,
            "span_types": types,
            "span_interps": interps,
            "check_trace": traces,
            "n_probes": len(traces),
            "n_healed": n_dropped,
            "reused_baseline_sql": True,
            "source_pred": "detection/forward",
            "relevance": "pipeline/checks/relevance.py",
            "target_types": sorted(TARGET_TYPES),
            "encoding_guard": True,
            "policy": "paper_spec",
        },
        "align": "relevance_on_forward",
    })
    return src


def _run_changed(gold, snap, llm, format_parser_base, phi_prime, traces, n_dropped) -> dict:
    types = dict(snap.get("span_types") or {})
    interps = dict(snap.get("span_interps") or {})
    parsed = ask_and_reparse(gold, llm, format_parser_base, phi_prime, types, interps)
    return {
        "id": gold.id,
        "db_id": getattr(gold, "db_id", None),
        "system": ARM,
        "pipeline": ARM,
        "parser": "qwen_coder",
        "question_out": parsed["question_out"],
        "schema_out": parsed["schema_out"],
        "evidence_out": parsed["evidence_out"],
        "predicted_sql": parsed["predicted_sql"],
        "n_asked": parsed["n_asked"],
        "n_probes": len(traces),
        "n_healed": n_dropped,
        "no_qc": True,
        "check": "relevance_typed",
        "baseline_n_asked": snap.get("baseline_n_asked"),
        "meta": {
            "phi": snap.get("phi"),
            "phi_prime": phi_prime,
            "span_types": types,
            "span_interps": interps,
            "check_trace": traces,
            "n_probes": len(traces),
            "n_healed": n_dropped,
            "reused_baseline_sql": False,
            "source_pred": "detection/forward",
            "relevance": "pipeline/checks/relevance.py",
            "target_types": sorted(TARGET_TYPES),
            "encoding_guard": True,
            "policy": "paper_spec",
        },
        "align": "relevance_on_forward",
    }


def _run_one(gold, snap, llm, format_parser_base, target_types: set[str], n_probes: int) -> dict:
    types = dict(snap.get("span_types") or {})
    interps = dict(snap.get("span_interps") or {})
    phi_prime, traces, n_dropped, baseline = apply_relevance(
        gold,
        snap.get("phi") or {},
        types,
        llm,
        format_parser_base,
        target_types=target_types,
        n_probes=n_probes,
    )
    if n_dropped == 0:
        row = _reuse_baseline(gold, snap, phi_prime, types, interps, traces, n_dropped)
    else:
        row = _run_changed(gold, snap, llm, format_parser_base, phi_prime, traces, n_dropped)
    meta = dict(row.get("meta") or {})
    meta["baseline_exec"] = baseline
    meta["n_probes_per_candidate"] = n_probes
    meta["policy"] = "revise_and_multi_probe"
    row["meta"] = meta
    return row


def _trace_counts(pred: Path) -> dict:
    reasons: Counter = Counter()
    by_type: dict[str, Counter] = {}
    drops = cards = 0
    for line in pred.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for tr in (row.get("meta") or {}).get("check_trace") or []:
            cards += 1
            typ = str(tr.get("type") or "unknown")
            reason = str(tr.get("reason") or "unknown")
            reasons[reason] += 1
            bucket = by_type.setdefault(typ, Counter())
            bucket["cards"] += 1
            bucket[reason] += 1
            if tr.get("action") == "drop":
                drops += 1
                bucket["dropped"] += 1
    return {
        "cards": cards,
        "dropped": drops,
        "reasons": dict(reasons),
        "by_type": {k: dict(v) for k, v in sorted(by_type.items())},
    }


def run_relevance(
    *,
    pred_path: Path,
    baseline_score_path: Path | None,
    out_dir: Path,
    limit: int | None,
    ids: list[str],
    resume: bool,
    target_types: set[str],
    n_probes: int,
) -> None:
    pred_path, frozen, golds, work, out_pred = open_frozen_run(
        pred_path=pred_path, out_dir=out_dir, ids=ids, limit=limit, resume=resume,
    )
    if baseline_score_path is None:
        baseline_score_path = resolve_baseline_score(pred_path, None)
    print(
        f"[data] golds={len(golds)} freeze={len(frozen)} todo={len(work)} "
        f"resume={resume} types={sorted(target_types)} probes={n_probes} out={out_dir}",
        flush=True,
    )

    from utils.llm import LLM

    llm = LLM()
    print(f"[llm] {llm.model} @ {llm.url}", flush=True)
    fmt = format_parser("rel")

    t0 = time.time()
    n_new = 0
    with out_pred.open("a", encoding="utf-8") as f:
        for i, gold in enumerate(work, 1):
            print(f"[rel {i}/{len(work)}] {gold.id}", flush=True)
            row = _run_one(gold, frozen[gold.id], llm, fmt, target_types, n_probes)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
            dropped = row.get("n_healed") or 0
            n_cards = row.get("n_probes") or 0
            print(
                f"  target_cards={n_cards} dropped={dropped} "
                f"n_asked={row['n_asked']} (base={row.get('baseline_n_asked')}) "
                f"reused={row.get('meta', {}).get('reused_baseline_sql')}",
                flush=True,
            )
    print(f"[done] new={n_new} elapsed={(time.time()-t0)/60:.1f}min", flush=True)

    metrics, base, delta = score_against_baseline(
        "bird_arcwise", out_pred, out_dir, baseline_score_path,
    )
    traces = _trace_counts(out_pred)
    summary = {
        "arm": ARM,
        "policy": "revise_and_multi_probe",
        "encoding_guard": True,
        "vacuous_guard": "empty_or_all_null_not_equal",
        "n_probes_per_candidate": n_probes,
        "target_types": sorted(target_types),
        "source_pred": str(pred_path),
        "baseline_score": str(baseline_score_path) if baseline_score_path else None,
        "baseline": base,
        "relevance": metrics,
        "cards": traces,
        "delta_ex": delta,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(
        f"[ex {ARM}] n={metrics.get('n')} EX={metrics.get('ex')} "
        f"n_hit={metrics.get('n_hit')} Q={metrics.get('Q')} "
        f"base_EX={base.get('ex')} ΔEX={summary.get('delta_ex')} "
        f"cards={traces.get('cards')} dropped={traces.get('dropped')}",
        flush=True,
    )


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] in {"-h", "--help"}:
        print(__doc__)
        raise SystemExit(0)

    extra = args
    if extra and not extra[0].startswith("-"):
        extra = extra[1:]

    def _parse_types(val: str) -> set[str]:
        return {x.strip() for x in val.split(",") if x.strip()}

    parsed = parse_flag_args(
        extra,
        default_out=OUT_DIR,
        extras={
            "--types": ("target_types", 1, _parse_types),
            "--probes": ("n_probes", 1, int),
        },
    )
    run_relevance(
        pred_path=parsed["pred"],
        baseline_score_path=parsed["baseline"],
        out_dir=parsed["out"],
        limit=parsed["limit"],
        ids=parsed["ids"],
        resume=parsed["resume"],
        target_types=parsed.get("target_types") or set(TARGET_TYPES),
        n_probes=parsed.get("n_probes") or DEFAULT_PROBES_PER_CANDIDATE,
    )


if __name__ == "__main__":
    main()
