#!/usr/bin/env python3
"""Exact two-sided McNemar test between two systems on the same questions.

Inputs are eval JSON files written by evaluator.ex (with "per_question"), or
prediction files whose records carry a boolean "ex_match". Questions are
paired by qid. With b = questions only A gets right and c = questions only B
gets right, p = min(1, 2 * P[X <= min(b, c)]) for X ~ Binomial(b + c, 1/2).

Usage:
  python -m evaluator.significance \\
      outputs/clambsql/eval/deepeye/ours.json outputs/clambsql/eval/deepeye/ambisql.json \\
      --gold intended
"""

import argparse
import json
from math import comb
from pathlib import Path


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2.0 * tail)


def outcomes(path, gold=None):
    path = Path(path)
    if path.suffix == ".jsonl":
        out = {}
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    qid = str(r.get("qid") or r.get("question_id") or r.get("id"))
                    out[qid] = bool(r.get(gold) if gold and gold in r else r.get("ex_match"))
        return out
    d = json.loads(path.read_text(encoding="utf-8"))
    if "per_question" not in d:
        raise SystemExit(f"{path}: no per_question list, rescore it with evaluator.ex first")
    key = gold or d.get("gold_key", "gold")
    return {str(r["qid"]): bool(r.get(key)) for r in d["per_question"]}


def compare(a, b):
    qids = sorted(set(a) & set(b))
    both_right = sum(1 for q in qids if a[q] and b[q])
    both_wrong = sum(1 for q in qids if not a[q] and not b[q])
    a_only = sum(1 for q in qids if a[q] and not b[q])
    b_only = sum(1 for q in qids if b[q] and not a[q])
    return {
        "n": len(qids),
        "both_right": both_right,
        "both_wrong": both_wrong,
        "a_only": a_only,
        "b_only": b_only,
        "p": mcnemar_exact(a_only, b_only),
        "unpaired": len(set(a) ^ set(b)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--gold", help="gold key, default: gold_key of the eval file")
    args = ap.parse_args()
    res = compare(outcomes(args.a, args.gold), outcomes(args.b, args.gold))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
