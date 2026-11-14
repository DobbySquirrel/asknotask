#!/usr/bin/env python3
"""Questions per instance (Q).

For our methods Q counts the ambiguities sent to the user, each as its own
question also when two share a span. Ambiguities settled without asking
(Auto) or removed (Drop) do not count. For CLEAR and AmbiSQL Q counts the
clarification slots each method asks.

Two sources give the same number:

  * a predictions file whose records carry "n_asked" (or a list "asked"),
  * a questions file, one record per question, with "question_id" and
    "decision" in ASK / AUTO / DROP.

Q divides by the benchmark size n, so questions without any record count 0.

Usage:
  python -m evaluator.question_count --ds ambrosia --pred outputs/ambrosia/predictions/qwen_coder/ours.jsonl
  python -m evaluator.question_count --ds ambrosia --questions outputs/ambrosia/questions/ours.jsonl
"""

import argparse
import json
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "configs" / "datasets.json"

COUNT_KEYS = ("n_asked", "num_questions", "n_questions", "q")
LIST_KEYS = ("asked", "questions", "clarifications")


def asked_in(record):
    for k in COUNT_KEYS:
        if record.get(k) is not None:
            return int(record[k])
    for k in LIST_KEYS:
        v = record.get(k)
        if isinstance(v, list):
            return sum(1 for x in v if not isinstance(x, dict) or x.get("decision", "ASK") == "ASK")
    return 0


def question_total(records):
    return sum(asked_in(r) for r in records)


def from_questions(path):
    """Per question id, the number of ASK decisions."""
    per = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            qid = str(r.get("question_id") or r.get("qid"))
            if str(r.get("decision", "")).upper() == "ASK":
                per[qid] += 1
            else:
                per.setdefault(qid, 0)
    return per


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ds", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pred", type=Path)
    src.add_argument("--questions", type=Path)
    args = ap.parse_args()
    n = json.loads(CONFIG.read_text())[args.ds]["n"]
    if args.pred:
        with open(args.pred, encoding="utf-8") as f:
            total = question_total(json.loads(l) for l in f if l.strip())
    else:
        total = sum(from_questions(args.questions).values())
    print(f"{args.ds}  asked={total}  n={n}  Q={total / n:.2f}")


if __name__ == "__main__":
    main()
