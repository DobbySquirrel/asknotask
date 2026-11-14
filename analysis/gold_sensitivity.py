#!/usr/bin/env python3
"""Gold sensitivity on the multi-gold benchmarks, with paired CIs and flips.

Reads the rescored eval files outputs/<ds>/eval_rescored/<parser>/<method>.json
(written by scripts/rescore_all.py, with per-question outcomes for every gold
key) and reports, for each method, EX against gold_1, gold_2, gold_3,
any_gold, and intended where present. For each method and gold key it also
compares against a reference method (Never-Ask by default) on the same
questions: the EX difference with a paired bootstrap 95% CI, the flips
(questions only one of the two gets right), and the exact McNemar p.

gold_k is evaluated on the questions that have a k-th gold query, so its n
can be smaller than the benchmark size (AMBROSIA has a third gold for 370
questions).

The clarification methods are answered by a simulated user who holds y*,
so scoring them against another gold measures a different intent than the
one they were told. The intent-independent rows are Never-Ask against every
key and every method against any_gold.

Usage:
  python analysis/gold_sensitivity.py
  python analysis/gold_sensitivity.py --ds ambrosia --parser qwen_coder --ref never_ask
"""

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluator.significance import mcnemar_exact  # noqa: E402

OUT = REPO / "outputs"
METHODS = ("never_ask", "clear", "ambisql", "ours_wo_scorer", "ours")
KEYS = ("gold_1", "gold_2", "gold_3", "intended", "any_gold")


def load(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return {str(r["qid"]): r for r in d["per_question"]}


def paired_ci(a, b, iters, seed):
    """95% percentile bootstrap CI of mean(a) - mean(b) in points, over paired questions."""
    n = len(a)
    if n == 0:
        return None, None
    plus = sum(1 for x, y in zip(a, b) if x > y)
    minus = sum(1 for x, y in zip(a, b) if x < y)
    p_plus, p_minus = plus / n, minus / n
    rest = 1.0 - p_plus
    # Each resampled difference is +1, -1, or 0, so a resample is a multinomial draw.
    if hasattr(random.Random, "binomialvariate"):
        rng = random.Random(seed)
        stats = []
        for _ in range(iters):
            k_plus = rng.binomialvariate(n, p_plus) if p_plus > 0 else 0
            k_minus = rng.binomialvariate(n - k_plus, p_minus / rest) if p_minus > 0 and rest > 0 else 0
            stats.append(100.0 * (k_plus - k_minus) / n)
    else:
        import numpy as np
        draws = np.random.default_rng(seed).multinomial(n, [p_plus, p_minus, max(0.0, 1 - p_plus - p_minus)], iters)
        stats = list(100.0 * (draws[:, 0] - draws[:, 1]) / n)
    stats.sort()
    return stats[int(0.025 * iters)], stats[int(0.975 * iters) - 1]


def analyse(ds, parser, ref, iters, seed):
    root = OUT / ds / "eval_rescored" / parser
    runs = {m: load(root / f"{m}.json") for m in METHODS if (root / f"{m}.json").exists()}
    if ref not in runs:
        raise SystemExit(f"{root}/{ref}.json not found, run scripts/rescore_all.py first")
    rows = []
    for m, per in runs.items():
        for key in KEYS:
            qids = sorted(q for q, r in per.items() if key in r and key in runs[ref].get(q, {}))
            if not qids:
                continue
            a = [int(bool(per[q][key])) for q in qids]
            b = [int(bool(runs[ref][q][key])) for q in qids]
            row = {"method": m, "gold": key, "n": len(qids), "ex": 100.0 * sum(a) / len(a)}
            if m != ref:
                only_m = sum(1 for x, y in zip(a, b) if x and not y)
                only_ref = sum(1 for x, y in zip(a, b) if y and not x)
                lo, hi = paired_ci(a, b, iters, seed)
                row.update({
                    "delta": 100.0 * (sum(a) - sum(b)) / len(a),
                    "ci95": [lo, hi],
                    "flips": {f"{m}_only": only_m, f"{ref}_only": only_ref},
                    "p": mcnemar_exact(only_m, only_ref),
                })
            rows.append(row)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ds", nargs="*", default=["ambrosia", "clambsql"])
    ap.add_argument("--parser", nargs="*", default=["qwen_coder", "gpt56_terra", "deepeye"])
    ap.add_argument("--ref", default="never_ask")
    ap.add_argument("--iters", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT / "analysis" / "gold_sensitivity_rescore.json")
    args = ap.parse_args()

    report = {}
    for ds in args.ds:
        for parser in args.parser:
            if not (OUT / ds / "eval_rescored" / parser).exists():
                continue
            rows = analyse(ds, parser, args.ref, args.iters, args.seed)
            report[f"{ds}/{parser}"] = rows
            print(f"\n{ds} / {parser}  (reference: {args.ref})")
            print(f"  {'method':<15} {'gold':<9} {'n':>5} {'EX':>6} {'delta':>7} {'95% CI':>15} {'flips':>9} {'p':>8}")
            for r in rows:
                if "delta" in r:
                    f = list(r["flips"].values())
                    ci = f"[{r['ci95'][0]:+.1f}, {r['ci95'][1]:+.1f}]"
                    print(f"  {r['method']:<15} {r['gold']:<9} {r['n']:>5} {r['ex']:>6.1f} {r['delta']:>+7.1f} "
                          f"{ci:>15} {f[0]:>4}/{f[1]:<4} {r['p']:>8.2g}")
                else:
                    print(f"  {r['method']:<15} {r['gold']:<9} {r['n']:>5} {r['ex']:>6.1f}")
    args.out.write_text(json.dumps({"ref": args.ref, "iters": args.iters, "seed": args.seed, "results": report},
                                   indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
