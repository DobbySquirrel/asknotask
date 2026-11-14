#!/usr/bin/env python3
"""用现成 pred 的冻 φ 跑本地 Existence，再全问剩余 ≥2、重解析、打 EX。

默认拿 outputs/bird_arcwise/detection/forward（可传 score_paper.json 或 pred.jsonl）：
  python pipeline/checks/run_ext_checks.py existence
  python pipeline/checks/run_ext_checks.py existence \\
      --pred outputs/bird_arcwise/detection/forward/score_paper.json
  python pipeline/checks/run_ext_checks.py existence --limit 8 --ids bird:62

输出：
  outputs/bird_arcwise/checks/exist/
    pred.jsonl  score_paper.json  summary.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ASK = Path(__file__).resolve().parents[2]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))

from pipeline.checks.runtime import (
    DEFAULT_PRED,
    DEFAULT_SCORE,
    ask_and_reparse,
    format_parser,
    open_frozen_run,
    parse_flag_args,
    resolve_baseline_score,
    score_against_baseline,
)

CHECKS = Path(__file__).resolve().parent
OUT_DIR = ASK / "outputs" / "bird_arcwise" / "checks" / "exist"


def _run_one(gold, snap: dict, llm, format_parser_base) -> dict:
    from pipeline.checks import existence as exist_mod

    phi = {k: list(v) for k, v in (snap.get("phi") or {}).items()}
    types = dict(snap.get("span_types") or {})
    interps = dict(snap.get("span_interps") or {})
    healed: dict = {}

    phi_prime, n_probes, n_healed, check_trace = exist_mod.apply_existence(
        gold, phi, types, healed,
    )
    parsed = ask_and_reparse(
        gold, llm, format_parser_base, phi_prime, types, interps, healed=healed,
    )
    return {
        "id": gold.id,
        "db_id": getattr(gold, "db_id", None),
        "system": "check_exist_on_none",
        "pipeline": "check_exist_on_none",
        "parser": "qwen_coder",
        "question_out": parsed["question_out"],
        "schema_out": parsed["schema_out"],
        "evidence_out": parsed["evidence_out"],
        "predicted_sql": parsed["predicted_sql"],
        "n_asked": parsed["n_asked"],
        "n_probes": n_probes,
        "n_healed": n_healed,
        "no_qc": True,
        "check": "exist",
        "baseline_n_asked": snap.get("baseline_n_asked"),
        "meta": {
            "phi": phi,
            "phi_prime": phi_prime,
            "span_types": types,
            "span_interps": interps,
            "healed": healed,
            "check_trace": check_trace,
            "n_probes": n_probes,
            "n_healed": n_healed,
            "source_pred": "detection/forward",
            "existence": "pipeline/checks/existence.py",
        },
        "align": "exist_on_forward",
    }


def run_existence(
    *,
    pred_path: Path,
    baseline_score_path: Path | None,
    out_dir: Path,
    limit: int | None,
    ids: list[str],
    resume: bool,
) -> None:
    pred_path, frozen, golds, work, out_pred = open_frozen_run(
        pred_path=pred_path, out_dir=out_dir, ids=ids, limit=limit, resume=resume,
    )
    if baseline_score_path is None:
        baseline_score_path = resolve_baseline_score(pred_path, None)
    print(
        f"[data] golds={len(golds)} freeze={len(frozen)} todo={len(work)} "
        f"resume={resume} out={out_dir}",
        flush=True,
    )

    from utils.llm import LLM

    llm = LLM()
    print(f"[llm] {llm.model} @ {llm.url}", flush=True)
    fmt = format_parser("ext")

    t0 = time.time()
    n_new = 0
    with out_pred.open("a", encoding="utf-8") as f:
        for i, gold in enumerate(work, 1):
            print(f"[exist {i}/{len(work)}] {gold.id}", flush=True)
            row = _run_one(gold, frozen[gold.id], llm, fmt)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
            print(
                f"  n_asked={row['n_asked']} (base={row.get('baseline_n_asked')}) "
                f"n_probes={row['n_probes']} n_healed={row['n_healed']}",
                flush=True,
            )
    print(f"[done] new={n_new} elapsed={(time.time()-t0)/60:.1f}min", flush=True)

    metrics, base, delta = score_against_baseline(
        "bird_arcwise", out_pred, out_dir, baseline_score_path,
    )
    summary = {
        "arm": "check_exist_on_none",
        "source_pred": str(pred_path),
        "baseline_score": str(baseline_score_path) if baseline_score_path else None,
        "baseline": base,
        "exist": metrics,
        "delta_ex": delta,
        "existence_module": str(CHECKS / "existence.py"),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(
        f"[ex exist_on_none] n={metrics.get('n')} EX={metrics.get('ex')} "
        f"n_hit={metrics.get('n_hit')} Q={metrics.get('Q')} "
        f"base_EX={base.get('ex')} ΔEX={summary.get('delta_ex')}",
        flush=True,
    )


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        raise SystemExit(0)
    cmd = args[0]
    extra = args[1:]
    if cmd not in {"existence", "exist", "e", "check_exist"}:
        raise SystemExit(f"unknown cmd {cmd!r}; only 'existence' for now")

    args = parse_flag_args(extra, default_out=OUT_DIR)
    run_existence(
        pred_path=args["pred"],
        baseline_score_path=args["baseline"],
        out_dir=args["out"],
        limit=args["limit"],
        ids=args["ids"],
        resume=args["resume"],
    )


if __name__ == "__main__":
    main()
