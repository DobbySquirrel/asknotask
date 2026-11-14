#!/usr/bin/env python3
"""Check result files in outputs/ against the numbers printed in the paper.

outputs/analysis/expected.json lists the paper's numbers as strings, so the
printed precision is kept ("59.0", "2.00"). Each computed value is formatted
to the same number of decimals and compared as text.

Two kinds of entries:

  * EX/Q entries ("ex", "q", "bench"), read from the evaluation files
    outputs/<ds>/eval/<parser>/<method>.json. EX is taken against y*, the
    gold key that expected.json names per benchmark ("gold" for
    BIRD-Arcwise, "gold_1" for AMBROSIA, "intended" for CLAMBSQL). The file
    may give "ex" and "q" as numbers or as objects keyed by gold, or
    "n"/"correct"/"q_total", or only a per-question list ("per_question",
    "items", or "results") whose records carry a boolean per gold key (or
    "correct") and "q". A .jsonl file is read as that per-question list.
  * value entries ("values"). Each key is a '/'-separated path into a JSON
    file. With "percent", a stored fraction in [0, 1] is scaled to percent.

Usage:
  python scripts/check_manifest.py                 # report
  python scripts/check_manifest.py --strict        # missing files fail too
  python scripts/check_manifest.py --only T2 T4    # filter by id prefix
  python scripts/check_manifest.py --json out.json # write the report
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUTS = REPO / "outputs"
DEFAULT_EXPECTED = DEFAULT_OUTPUTS / "analysis" / "expected.json"


def first(d, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def decimals(printed):
    s = str(printed)
    return len(s.split(".", 1)[1]) if "." in s else 0


def same(got, printed):
    """True if got, printed with the paper's precision, equals the paper's text."""
    d = decimals(printed)
    return f"{float(got):.{d}f}" == f"{float(printed):.{d}f}"


PER_QUESTION_KEYS = ("per_question", "items", "results")


def pick(v, gold):
    return v.get(gold) if isinstance(v, dict) else v


def from_records(records, gold):
    n = correct = q_total = 0
    has_q = False
    for r in records:
        n += 1
        c = r[gold] if gold in r else first(r, "correct", "ex", "is_correct")
        correct += bool(c)
        q = first(r, "q", "num_questions", "n_questions")
        if q is not None:
            has_q = True
            q_total += int(q)
    return {"n": n, "correct": correct, "q_total": q_total if has_q else None}


def load_jsonl(path, gold):
    with open(path) as f:
        return from_records((json.loads(l) for l in f if l.strip()), gold)


def descend(obj, keys):
    for key in keys:
        if not isinstance(obj, dict) or key not in obj:
            raise KeyError(f"key {key!r} not found in {'/'.join(keys)}")
        obj = obj[key]
    return obj


def load_exq(path, select, gold):
    obj = descend(json.loads(Path(path).read_text()), select or [])
    if not isinstance(obj, dict):
        raise ValueError("selected value is not an object")
    raw = {
        "n": first(obj, "n", "total", "num"),
        "correct": pick(first(obj, "correct", "n_correct"), gold),
        "ex": pick(first(obj, "ex", "EX", "accuracy"), gold),
        "q_total": first(obj, "q_total", "questions_total"),
        "q_mean": first(obj, "q_mean", "q", "Q", "questions_per_instance"),
    }
    records = first(obj, *PER_QUESTION_KEYS)
    if isinstance(records, list):
        derived = from_records(records, gold)
        for k, v in derived.items():
            if raw.get(k) is None:
                raw[k] = v
    return raw


def measure(raw, n_expected):
    n = raw.get("n") or n_expected
    correct = raw.get("correct")
    ex = raw.get("ex")
    if correct is not None and n:
        ex = 100.0 * correct / n
    elif ex is not None and ex <= 1.0:
        ex = 100.0 * ex
    q = raw.get("q_mean")
    if raw.get("q_total") is not None and n:
        q = raw["q_total"] / n
    return {"n": n, "correct": correct, "ex": ex, "q": q}


def check_exq(entry, path, sizes, golds, res, fail):
    bench = entry.get("bench")
    n_expected = sizes.get(bench)
    gold = entry.get("gold") or golds.get(bench, "gold")
    if path.suffix == ".jsonl":
        raw = load_jsonl(path, gold)
    else:
        raw = load_exq(path, entry.get("select"), gold)
    got = measure(raw, n_expected)
    res["got"] = got
    if n_expected and got["n"] != n_expected:
        fail(f"n={got['n']} expected {n_expected}")
    for field, label in (("ex", "EX"), ("q", "Q")):
        if field not in entry:
            continue
        if got[field] is None:
            fail(f"no {label} in file")
        elif not same(got[field], entry[field]):
            d = decimals(entry[field])
            fail(f"{label} {got[field]:.{d + 2}f} expected {entry[field]}")


def check_values(entry, path, res, fail):
    obj = json.loads(Path(path).read_text())
    got = {}
    for key, printed in entry["values"].items():
        try:
            v = descend(obj, key.split("/"))
        except KeyError:
            fail(f"{key}: not in file")
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            fail(f"{key}: not a number ({v!r})")
            continue
        if entry.get("percent") and v <= 1.0 and float(printed) > 1.0:
            v = 100.0 * v
        got[key] = v
        if not same(v, printed):
            fail(f"{key}: {v} expected {printed}")
    res["got"] = got


def check(entry, outputs, sizes, golds):
    path = outputs / entry["path"]
    res = {"id": entry["id"], "paper": entry.get("paper", ""), "path": entry["path"],
           "status": "ok", "notes": []}
    if not path.exists():
        res["status"] = "missing"
        return res

    def fail(msg):
        res["status"] = "mismatch"
        res["notes"].append(msg)

    try:
        if "values" in entry:
            check_values(entry, path, res, fail)
        else:
            check_exq(entry, path, sizes, golds, res, fail)
    except Exception as e:  # noqa: BLE001
        res["status"] = "error"
        res["notes"].append(str(e))
    return res


def summary_cell(res):
    g = res.get("got") or {}
    if "ex" not in g:
        return f"{len(g)} values" if g else ""
    ex = "-" if g.get("ex") is None else f"{g['ex']:.1f}"
    q = "-" if g.get("q") is None else f"{g['q']:.2f}"
    return f"EX {ex}  Q {q}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    ap.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    ap.add_argument("--only", nargs="*", help="id prefixes, e.g. T2 T6")
    ap.add_argument("--strict", action="store_true", help="treat missing files as failures")
    ap.add_argument("--json", type=Path, help="write the full report to this file")
    args = ap.parse_args()

    spec = json.loads(args.expected.read_text())
    sizes = spec.get("sizes", {})
    golds = spec.get("gold", {})
    entries = spec["entries"]
    if args.only:
        entries = [e for e in entries if any(e["id"].startswith(p) for p in args.only)]

    results = [check(e, args.outputs, sizes, golds) for e in entries]

    width = max((len(r["id"]) for r in results), default=10)
    print(f"{'id':<{width}}  {'status':<8}  {'got':<18}  notes")
    for r in results:
        print(f"{r['id']:<{width}}  {r['status']:<8}  {summary_cell(r):<18}  {'; '.join(r['notes'])}")

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("\n" + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))

    if args.json:
        args.json.write_text(json.dumps(results, indent=2))

    bad = counts.get("mismatch", 0) + counts.get("error", 0)
    if args.strict:
        bad += counts.get("missing", 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
