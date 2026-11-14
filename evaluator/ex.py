#!/usr/bin/env python3
"""Execution accuracy (EX) against every gold query of a benchmark.

A prediction is correct for a gold query if both execute on the instance
database and their result fingerprints match (same as paper_exp
make_gold_exec.fingerprint / score_gold): rows as a set, each row keeping
column order, floats rounded to 6 decimals, int/float kept distinct via JSON.
A prediction that fails or runs past the timeout (30 s) is wrong. Gold queries get
a longer timeout (300 s), and a gold that still fails is reported in n_gold_error
and gold_errors.

Gold file (configs/datasets.json, "gold_file"), one record per question:

    {"qid": "...", "db_id": "...", "db_path": "dataset/databases/...", "gold": ["SELECT ...", ...], "intended": 0}

"db_path" is preferred over the config template (needed when db_id is not unique).
"intended" is the 0-based index of y* on CLAMBSQL and is absent elsewhere.
Float cells are rounded to 6 decimals by default (paper_exp norm_cell).
For each question the evaluator reports gold_1 ... gold_k, any_gold, gold
(the same as gold_1), and intended (if given). The paper reports EX against
y*: gold on BIRD-Arcwise, gold_1 on AMBROSIA, intended on CLAMBSQL.

Usage:
  python -m evaluator.ex --ds ambrosia \\
      --pred outputs/ambrosia/predictions/qwen_coder/ours.jsonl \\
      --out  outputs/ambrosia/eval/qwen_coder/ours.json
"""

import argparse
import json
import sqlite3
import sys
import time
from multiprocessing import Pool
from pathlib import Path

from evaluator.question_count import question_total

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "configs" / "datasets.json"

QID_KEYS = ("qid", "question_id", "instance_id", "id", "idx")
SQL_KEYS = ("pred_sql", "final_sql", "sql", "pred", "predicted_sql", "prediction")


def load_config(ds):
    cfg = json.loads(CONFIG.read_text())
    if ds not in cfg:
        raise SystemExit(f"unknown dataset {ds!r}, expected one of {[k for k in cfg if not k.startswith('_')]}")
    return cfg[ds]


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def field(record, keys, what, path):
    for k in keys:
        if k in record and record[k] is not None:
            return record[k]
    raise KeyError(f"{path}: no {what} field among {keys} in record {list(record)[:8]}")


# ---------------------------------------------------------------- execution

_CONNS = {}
_TIMEOUT = 30.0
_FLOAT_DIGITS = None


def _init_worker(timeout, float_digits):
    global _TIMEOUT, _FLOAT_DIGITS
    _TIMEOUT, _FLOAT_DIGITS = timeout, float_digits


def _connect(db_path):
    conn = _CONNS.get(db_path)
    if conn is None:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        _CONNS[db_path] = conn
    return conn


def _norm(v):
    """Match paper_exp eval.clear.ex.norm_cell (float → round; int stays int)."""
    if v is None:
        return None
    if isinstance(v, float):
        return round(v, _FLOAT_DIGITS) if _FLOAT_DIGITS is not None else v
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except Exception:
            return v
    return v


def fingerprint(rows, float_digits=6):
    """Canonical fingerprint of SQL result rows (same semantics as EX scoring).

    Rows are treated as a set; each row keeps column order. Floats are rounded
    to ``float_digits`` (default 6, same as score()). Pass None to skip rounding.
    JSON keeps int/float distinct (288 vs 288.0).

    Unlike the old make_gold_exec SHA1 digest, this returns the canonical JSON
    string directly so callers share one representation with evaluator.ex.
    """

    def norm(v):
        if v is None:
            return None
        if isinstance(v, float):
            return round(v, float_digits) if float_digits is not None else v
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8")
            except Exception:
                return v
        return v

    canon = sorted(
        {tuple(norm(v) for v in r) for r in (rows or [])},
        key=lambda r: json.dumps(r, ensure_ascii=False, default=str),
    )
    return json.dumps(canon, ensure_ascii=False, default=str)


# Back-compat alias used by internal scoring paths.
_fingerprint = fingerprint


def run_sql(sql: str, db_path: str, timeout_s: float = 30.0, float_digits: int | None = 6):
    """Execute one SQLite query for pipeline helpers (sql_pool grouping, checks).

    Returns a simple namespace: ok, rows, error, fingerprint.
    On failure fingerprint is None (callers should not group failed drafts).
    """
    from types import SimpleNamespace

    if not sql or not isinstance(sql, str) or not sql.strip():
        return SimpleNamespace(ok=False, rows=None, error="empty", fingerprint=None)
    path = str(db_path or "")
    if not path:
        return SimpleNamespace(ok=False, rows=None, error="no db_path", fingerprint=None)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    except sqlite3.Error as e:
        return SimpleNamespace(ok=False, rows=None, error=f"connect: {e}", fingerprint=None)
    deadline = time.monotonic() + float(timeout_s)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        rows = conn.execute(sql).fetchall()
        fp = fingerprint(rows, float_digits=float_digits)
        return SimpleNamespace(ok=True, rows=rows, error=None, fingerprint=fp)
    except sqlite3.OperationalError as e:
        err = "timeout" if "interrupted" in str(e) else f"sql: {e}"
        return SimpleNamespace(ok=False, rows=None, error=err, fingerprint=None)
    except Exception as e:  # noqa: BLE001
        return SimpleNamespace(ok=False, rows=None, error=f"sql: {e}", fingerprint=None)
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def execute(task):
    """Return (key, fingerprint_str) or (key, None) on error or timeout."""
    key, db_path, sql, limit = task
    if not sql or not isinstance(sql, str) or not sql.strip():
        return key, None, "empty"
    try:
        conn = _connect(db_path)
    except sqlite3.Error as e:
        return key, None, f"connect: {e}"
    deadline = time.monotonic() + (limit or _TIMEOUT)
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        rows = conn.execute(sql).fetchall()
        return key, fingerprint(rows, float_digits=_FLOAT_DIGITS), None
    except sqlite3.OperationalError as e:
        return key, None, "timeout" if "interrupted" in str(e) else f"sql: {e}"
    except Exception as e:  # noqa: BLE001
        return key, None, f"sql: {e}"
    finally:
        conn.set_progress_handler(None, 0)


def run_all(tasks, workers, timeout, float_digits):
    results = {}
    if workers <= 1:
        _init_worker(timeout, float_digits)
        for t in tasks:
            k, rows, err = execute(t)
            results[k] = (rows, err)
        return results
    with Pool(workers, initializer=_init_worker, initargs=(timeout, float_digits)) as pool:
        for k, rows, err in pool.imap_unordered(execute, tasks, chunksize=8):
            results[k] = (rows, err)
    return results


# Process-local cache so rescore_all does not re-run the same gold SQL (incl. slow ones)
# for every method. Keyed by (db, sql, float_digits).
_GOLD_CACHE = {}


# ---------------------------------------------------------------- scoring

def gold_keys(g):
    keys = [f"gold_{i + 1}" for i in range(len(g["gold"]))]
    return keys + ["any_gold", "gold"] + (["intended"] if g.get("intended") is not None else [])


def score(ds, pred_path, gold_path=None, db_template=None, workers=8, timeout=30.0,
          float_digits=6, qid_key=None, sql_key=None, gold_timeout=300.0):
    """Score predictions. float_digits defaults to 6 to match paper_exp norm_cell."""
    cfg = load_config(ds)
    gold_path = Path(gold_path or REPO / cfg["gold_file"])
    db_template = db_template or cfg["db_path"]
    golds = read_jsonl(gold_path)
    preds = read_jsonl(pred_path)

    qk = (qid_key,) if qid_key else QID_KEYS
    sk = (sql_key,) if sql_key else SQL_KEYS
    by_qid = {}
    for r in preds:
        by_qid[str(field(r, qk, "question id", pred_path))] = r

    def db_of(g):
        # Prefer per-question db_path (AMBROSIA/CLAMBSQL db_id is not unique).
        if g.get("db_path"):
            p = Path(g["db_path"])
            return str(p if p.is_absolute() else REPO / p)
        p = Path(db_template.format(db_id=g["db_id"]))
        return str(p if p.is_absolute() else REPO / p)

    tasks, seen, results = [], set(), {}
    for g in golds:
        db = db_of(g)
        for sql in g["gold"]:
            key = ("g", db, sql)
            if key in seen:
                continue
            seen.add(key)
            cached = _GOLD_CACHE.get((db, sql, float_digits))
            if cached is not None:
                results[key] = cached
            else:
                tasks.append((key, db, sql, gold_timeout))
        r = by_qid.get(str(g["qid"]))
        if r is not None:
            sql = next((r[k] for k in sk if r.get(k) is not None), None)
            tasks.append((("p", str(g["qid"])), db, sql, timeout))
    results.update(run_all(tasks, workers, timeout, float_digits))
    for key, val in results.items():
        if key[0] == "g":
            _GOLD_CACHE[(key[1], key[2], float_digits)] = val

    per_question, n_missing, n_pred_err, n_gold_err = [], 0, 0, 0
    gold_errors = []
    for g in golds:
        qid, db = str(g["qid"]), db_of(g)
        rec = {"qid": qid, "db_id": g["db_id"]}
        pred_rows, err = results.get(("p", qid), (None, "missing"))
        if ("p", qid) not in results:
            n_missing += 1
        elif err:
            n_pred_err += 1
        if err:
            rec["error"] = err
        hits = []
        for i, sql in enumerate(g["gold"]):
            gold_rows, gerr = results[("g", db, sql)]
            if gerr:
                n_gold_err += 1
                gold_errors.append({"qid": qid, "gold": i + 1, "error": gerr})
            hit = pred_rows is not None and gold_rows is not None and pred_rows == gold_rows
            rec[f"gold_{i + 1}"] = hit
            hits.append(hit)
        rec["any_gold"] = any(hits)
        rec["gold"] = hits[0] if hits else False
        if g.get("intended") is not None:
            rec["intended"] = hits[int(g["intended"])]
        r = by_qid.get(qid)
        if r is not None:
            rec["q"] = question_total([r])
        per_question.append(rec)

    n = len(per_question)
    keys = sorted({k for rec in per_question for k in rec if k == "gold" or k.startswith("gold_")
                   or k in ("any_gold", "intended")}, key=_key_order)
    correct = {k: sum(1 for rec in per_question if rec.get(k)) for k in keys}
    q_total = sum(rec.get("q", 0) for rec in per_question)
    return {
        "n": n,
        "gold_key": cfg["gold"],
        "correct": correct,
        "ex": {k: 100.0 * v / n for k, v in correct.items()} if n else {},
        "q": q_total / n if n else None,
        "q_total": q_total,
        "n_pred_missing": n_missing,
        "n_pred_error": n_pred_err,
        "n_gold_error": n_gold_err,
        "gold_errors": gold_errors,
        "pred_file": str(pred_path),
        "gold_file": str(gold_path),
        "timeout_s": timeout,
        "per_question": per_question,
    }


def _key_order(k):
    order = {"gold": 0, "intended": 1, "any_gold": 99}
    if k.startswith("gold_"):
        return 10 + int(k.split("_")[1])
    return order.get(k, 50)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ds", required=True, help="bird_arcwise, ambrosia, or clambsql")
    ap.add_argument("--pred", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="eval JSON to write (default: print summary only)")
    ap.add_argument("--gold", type=Path, help="override gold_file from configs/datasets.json")
    ap.add_argument("--db", help="override db_path template, e.g. /data/bird/{db_id}/{db_id}.sqlite")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=30.0, help="per predicted query")
    ap.add_argument("--gold-timeout", type=float, default=300.0,
                    help="per gold query, longer so that a slow gold does not count every prediction wrong")
    ap.add_argument("--float-digits", type=int, default=6,
                    help="round floats before comparing (default 6, matches paper_exp norm_cell)")
    ap.add_argument("--qid-key", help="question id field in the predictions")
    ap.add_argument("--sql-key", help="SQL field in the predictions")
    args = ap.parse_args()

    res = score(args.ds, args.pred, args.gold, args.db, args.workers, args.timeout,
                args.float_digits, args.qid_key, args.sql_key, args.gold_timeout)
    g = res["gold_key"]
    n_cfg = load_config(args.ds)["n"]
    if res["n"] != n_cfg:
        print(f"warning: gold file has {res['n']} questions, {args.ds} has {n_cfg}", file=sys.stderr)
    print(f"{args.ds}  n={res['n']}  EX[{g}]={res['ex'].get(g, 0):.1f} "
          f"({res['correct'].get(g, 0)})  Q={res['q']:.2f}  "
          f"missing={res['n_pred_missing']} pred_err={res['n_pred_error']} gold_err={res['n_gold_error']}")
    for k, v in res["correct"].items():
        if k != g:
            print(f"  {k:<9} {res['ex'][k]:5.1f} ({v})")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
