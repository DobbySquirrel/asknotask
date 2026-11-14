#!/usr/bin/env python3
"""Rescore every prediction file and compare with the recorded eval numbers.

For each outputs/<ds>/predictions/<parser>/<method>.jsonl this runs
evaluator.ex, writes outputs/<ds>/eval_rescored/<parser>/<method>.json (with
per-question outcomes for every gold key), and compares the count of correct
queries against y* and Q with outputs/<ds>/eval/<parser>/<method>.json, which
holds the numbers wired to the paper.

Some recorded numbers are means over repeated runs (their "source" says so).
A single prediction file cannot reproduce those exactly, and they are marked
"mean" instead of "diff".

Usage (on the cluster, where predictions and databases exist):
  python scripts/rescore_all.py
  python scripts/rescore_all.py --ds clambsql --parser qwen_coder --workers 32
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluator.ex import score  # noqa: E402

OUT = REPO / "outputs"
DATASETS = ("bird_arcwise", "ambrosia", "clambsql")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ds", nargs="*", default=list(DATASETS))
    ap.add_argument("--parser", nargs="*", help="qwen_coder, gpt56_terra, deepeye (default: all)")
    ap.add_argument("--method", nargs="*", help="method names (default: all)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--gold-timeout", type=float, default=300.0)
    ap.add_argument("--float-digits", type=int, default=6,
                    help="round floats before compare (default 6 = paper_exp)")
    ap.add_argument("--no-write", action="store_true", help="compare only, do not write eval_rescored/")
    args = ap.parse_args()

    rows = []
    for ds in args.ds:
        pred_root = OUT / ds / "predictions"
        if not pred_root.exists():
            continue
        for pred in sorted(pred_root.glob("*/*.jsonl")):
            parser, method = pred.parent.name, pred.stem
            if args.parser and parser not in args.parser:
                continue
            if args.method and method not in args.method:
                continue
            print(f"scoring {ds}/{parser}/{method} ...", flush=True)
            try:
                res = score(ds, pred, workers=args.workers, timeout=args.timeout,
                            float_digits=args.float_digits, gold_timeout=args.gold_timeout)
            except Exception as e:  # noqa: BLE001
                rows.append((ds, parser, method, "error", None, None, None, None, str(e)[:80]))
                print(f"  error: {e}", flush=True)
                continue
            print(f"  correct={res['correct'].get(res['gold_key'])} gold_err={res['n_gold_error']}", flush=True)
            g = res["gold_key"]
            got_c, got_q = res["correct"].get(g), res["q"]
            if not args.no_write:
                dst = OUT / ds / "eval_rescored" / parser / f"{method}.json"
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

            ref_path = OUT / ds / "eval" / parser / f"{method}.json"
            ref_c = ref_q = None
            note = f"missing={res['n_pred_missing']} err={res['n_pred_error']} gold_err={res['n_gold_error']}"
            if res["gold_errors"]:
                note += " (" + ", ".join(f"{e['qid']}:{e['error'][:20]}" for e in res["gold_errors"][:3]) + ")"
            status = "new"
            # Theta-curve preds are often SQL-only (no n_asked); recorded Q comes from summary.json.
            pred_has_q = False
            with open(pred, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    if any(k in r for k in ("n_asked", "q", "num_questions", "n_questions")):
                        pred_has_q = True
                        break
                    if i >= 20:
                        break
            if ref_path.exists():
                ref = json.loads(ref_path.read_text(encoding="utf-8"))
                ref_c = (ref.get("correct") or {}).get(g)
                ref_q = ref.get("q")
                same_c = ref_c is None or round(float(ref_c)) == got_c
                if ref_q is None or not pred_has_q:
                    same_q = True
                    if ref_q is not None and not pred_has_q:
                        note += "; Q from summary (pred has no n_asked)"
                        got_q = None  # display as unavailable
                else:
                    same_q = round(ref_q, 2) == round(got_q, 2)
                if same_c and same_q:
                    status = "ok"
                elif "mean" in str(ref.get("source", "")):
                    status = "mean"
                else:
                    status = "diff"
            rows.append((ds, parser, method, status, got_c, ref_c, got_q, ref_q, note))

    head = ("dataset", "parser", "method", "status", "correct", "recorded", "Q", "rec.Q", "notes")
    print("  ".join(f"{h:<14}" if i < 3 else f"{h:<8}" for i, h in enumerate(head)))
    for ds, parser, method, status, c, rc, q, rq, note in rows:
        fq = lambda v: "-" if v is None else f"{v:.2f}"
        fc = lambda v: "-" if v is None else f"{float(v):.0f}"
        print(f"{ds:<14}  {parser:<14}  {method:<14}  {status:<8}  {fc(c):<8}  {fc(rc):<8}  "
              f"{fq(q):<8}  {fq(rq):<8}  {note}")
    counts = {}
    for r in rows:
        counts[r[3]] = counts.get(r[3], 0) + 1
    print("\n" + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("diff") or counts.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
