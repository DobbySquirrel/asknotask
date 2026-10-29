"""Task C: the draft pool as extra input to the three detection stages.

Variants, all on the same frozen forward cards:
  d10    frozen D10 run (one card per question, whole-query readings)
  multi  cards from re-running Stages 1-3 with the draft pool block
  hybrid multi, falling back to the D10 card when multi adds no card

Usage:
  python task_c.py verify  --manifest MANIFEST.sha256
  python task_c.py run     --dataset bird --out runs/full_b/task_c
  python task_c.py report  --dataset bird --out runs/full_b/task_c

All steps are resumable: finished questions are skipped on rerun.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import adapters as A

PORTS = [int(p) for p in os.environ.get("TASK_C_PORTS", "8000,8001,8002,8003,8004,8005,8006,8007").split(",")]
PER_PORT = int(os.environ.get("TASK_C_PER_PORT", "8"))
PREVIEW_ROWS = 3
POOL_HEADER = "Candidate queries drafted for this question disagree. Groups by result:"

_port_cycle = itertools.cycle(PORTS)
_port_lock = threading.Lock()


def next_port() -> int:
    with _port_lock:
        return next(_port_cycle)


# ---------------------------------------------------------------- io

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> dict[str, dict]:
    out = {}
    if path.exists():
        with open(path) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[r["qid"]] = r
    return out


class JsonlWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a")
        self.lock = threading.Lock()

    def write(self, rec: dict) -> None:
        with self.lock:
            self.f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.f.flush()


# ---------------------------------------------------------------- pool

def group_drafts(rec: dict, d10: dict, y_bot_sql: str) -> list[dict] | None:
    """Group drafts by result with the scoring comparator. Return None when
    no group differs from y_bot, i.e. the drafts do not disagree with it."""
    q = rec["question"]
    bot_rows = A.execute(rec["db_id"], y_bot_sql)
    groups: list[dict] = []
    for d in d10.get("drafts", []):
        rows = A.execute(rec["db_id"], d["sql"])
        if rows is None:
            continue
        for g in groups:
            if A.results_equal(g["rows"], rows, q):
                g["sqls"].append(d["sql"])
                break
        else:
            groups.append({"rows": rows, "sqls": [d["sql"]]})
    if bot_rows is not None:
        for g in groups:
            g["is_bot"] = A.results_equal(g["rows"], bot_rows, q)
    if not any(not g.get("is_bot", False) for g in groups) or len(groups) < 2:
        return None
    return groups


def pool_block(groups: list[dict], descriptions: dict[str, str]) -> str:
    lines = [POOL_HEADER]
    for i, g in enumerate(groups, 1):
        rep = g["sqls"][0]
        desc = descriptions.get(rep, "").strip() or rep
        tag = " (same result as the query written without clarification)" if g.get("is_bot") else ""
        lines.append(f"Group {i}{tag}: {desc}")
        rows = list(g["rows"])[:PREVIEW_ROWS] if g["rows"] else []
        for r in rows:
            lines.append("  " + " | ".join(str(v) for v in (r if isinstance(r, (list, tuple)) else [r])))
    return "\n".join(lines)


# ---------------------------------------------------------------- merge (R1)

_ws = re.compile(r"\s+")


def norm_span(s: str) -> str:
    return _ws.sub(" ", (s or "").strip().lower())


def same_r1(a: dict, b: dict) -> bool:
    return norm_span(a.get("span", "")) == norm_span(b.get("span", "")) and a.get("type") == b.get("type")


# ---------------------------------------------------------------- per question

def redetect(rec: dict, block: str) -> list[dict]:
    open_amb: list[dict] = []
    cards: list[dict] = []
    for stage in (1, 2, 3):
        out = A.detect_stage(stage, rec, list(open_amb), block, next_port())
        for c in out:
            c = dict(c)
            c["stage"] = stage
            c["source"] = "pool"
            cards.append(c)
        open_amb.extend(out)
    return cards


def process_question(rec: dict, frozen: dict, d10: dict | None) -> dict:
    qid = rec["qid"]
    base = {"qid": qid, "diverge": False}
    if not d10:
        return base
    groups = group_drafts(rec, d10, frozen["y_bot_sql"])
    if groups is None:
        return base
    block = pool_block(groups, d10.get("draft_descriptions", {}))
    pool_cards = redetect(rec, block)

    new_cards = [c for c in pool_cards if not any(same_r1(c, f) for f in frozen["cards"])]
    merged_into_forward = len(pool_cards) - len(new_cards)

    funnel, written, ask_cards = [], [], []
    for c in new_cards:
        res = A.run_checks(rec, c, next_port())
        funnel.append({"type": c.get("type"), "stage": c.get("stage"), "outcome": res["outcome"]})
        if res["outcome"] == "settled_written" and res.get("written"):
            written.append(res["written"])
        elif res["outcome"] == "ask":
            ask_cards.append(res["card"])

    new_resp = [(c, A.simulate_user(rec, c, next_port())) for c in ask_cards]

    return {
        "qid": qid,
        "diverge": True,
        "n_groups": len(groups),
        "pool_block": block,
        "pool_cards": pool_cards,
        "merged_into_forward": merged_into_forward,
        "funnel": funnel,
        "written": written,
        "asked": [{"card": c, "response": r} for c, r in new_resp],
    }


_parse_cache: dict[tuple[str, str], tuple[str, bool]] = {}
_parse_lock = threading.Lock()


def finish_variant(rec: dict, frozen: dict, d10: dict | None, det: dict, variant: str) -> dict:
    """Compose, parse, and score one variant. Reuse the frozen prediction
    when the evidence is byte-identical."""
    fw_answered = [(c, frozen["responses"].get(c.get("card_id"))) for c in frozen["asked"]]
    fw_written = frozen.get("written", [])
    if variant == "d10":
        return {"evidence": d10["evidence"] if d10 else frozen["evidence"],
                "pred_sql": d10["pred_sql"] if d10 else frozen["pred_sql"],
                "correct": d10["correct"] if d10 else frozen["correct"],
                "q": d10["n_asked"] if d10 else len(frozen["asked"]),
                "reused": True}
    extra_written = det.get("written", []) if det.get("diverge") else []
    extra_answered = [(a["card"], a["response"]) for a in det.get("asked", [])] if det.get("diverge") else []
    fallback = False
    if variant == "hybrid" and det.get("diverge") and not det.get("funnel") and d10:
        return {"evidence": d10["evidence"], "pred_sql": d10["pred_sql"], "correct": d10["correct"],
                "q": d10["n_asked"], "reused": True, "fallback": True}
    evidence = A.compose_evidence(rec, fw_written + extra_written, fw_answered + extra_answered)
    q = len(frozen["asked"]) + len(extra_answered)
    if evidence == frozen["evidence"]:
        return {"evidence": evidence, "pred_sql": frozen["pred_sql"], "correct": frozen["correct"],
                "q": q, "reused": True, "fallback": fallback}
    key = (rec["qid"], evidence)
    with _parse_lock:
        hit = _parse_cache.get(key)
    if hit is None:
        pred = A.parse(rec, evidence, next_port())
        hit = (pred, A.score(rec, pred))
        with _parse_lock:
            _parse_cache[key] = hit
    return {"evidence": evidence, "pred_sql": hit[0], "correct": hit[1],
            "q": q, "reused": False, "fallback": fallback}


# ---------------------------------------------------------------- stats

def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


# ---------------------------------------------------------------- commands

def cmd_verify(args) -> None:
    bad = 0
    with open(args.manifest) as f:
        for line in f:
            if not line.strip():
                continue
            digest, path = line.split(maxsplit=1)
            path = path.strip()
            got = sha256(Path(path))
            if got != digest:
                print(f"MISMATCH {path}\n  want {digest}\n  got  {got}")
                bad += 1
    print("all sha256 match" if bad == 0 else f"{bad} mismatches")
    sys.exit(1 if bad else 0)


def cmd_run(args) -> None:
    out = Path(args.out) / args.dataset
    qs = A.load_questions(args.dataset)
    if args.limit:
        rnd = random.Random(0)
        qs = rnd.sample(qs, min(args.limit, len(qs)))
    frozen = A.load_frozen(args.dataset)
    d10 = A.load_d10(args.dataset)

    det_path, var_path = out / "detect.jsonl", out / "variants.jsonl"
    done_det = read_jsonl(det_path)
    det_w = JsonlWriter(det_path)
    todo = [r for r in qs if r["qid"] not in done_det]
    print(f"[{args.dataset}] detection: {len(todo)} to do, {len(done_det)} done", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(PORTS) * PER_PORT) as ex:
        futs = {ex.submit(process_question, r, frozen[r["qid"]], d10.get(r["qid"])): r["qid"] for r in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                rec = fu.result()
            except Exception as e:
                rec = {"qid": futs[fu], "diverge": False, "error": repr(e)}
            det_w.write(rec)
            done_det[rec["qid"]] = rec
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)

    done_var = read_jsonl(var_path)
    var_w = JsonlWriter(var_path)
    todo = [r for r in qs if r["qid"] not in done_var]
    print(f"[{args.dataset}] parsing: {len(todo)} to do", flush=True)

    def one(r):
        qid = r["qid"]
        return {"qid": qid, **{v: finish_variant(r, frozen[qid], d10.get(qid), done_det[qid], v)
                               for v in ("d10", "multi", "hybrid")}}

    with ThreadPoolExecutor(max_workers=len(PORTS) * PER_PORT) as ex:
        futs = {ex.submit(one, r): r["qid"] for r in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                var_w.write(fu.result())
            except Exception as e:
                var_w.write({"qid": futs[fu], "error": repr(e)})
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}  {time.time() - t0:.0f}s", flush=True)
    print(f"[{args.dataset}] done in {time.time() - t0:.0f}s")


def cmd_report(args) -> None:
    out = Path(args.out) / args.dataset
    det = read_jsonl(out / "detect.jsonl")
    var = read_jsonl(out / "variants.jsonl")
    errs = [q for q, r in var.items() if "error" in r] + [q for q, r in det.items() if "error" in r]
    rows = [r for r in var.values() if "error" not in r]
    n = len(rows)
    lines = [f"# Task C report: {args.dataset}", "",
             f"questions {n}, errors {len(errs)}, diverging {sum(1 for r in det.values() if r.get('diverge'))}", ""]

    lines += ["| variant | EX | Q | gained vs d10 | lost vs d10 | McNemar p | reparsed |", "|---|---|---|---|---|---|---|"]
    for v in ("d10", "multi", "hybrid"):
        ex = sum(r[v]["correct"] for r in rows)
        q = sum(r[v]["q"] for r in rows) / max(n, 1)
        b = sum(1 for r in rows if r[v]["correct"] and not r["d10"]["correct"])
        c = sum(1 for r in rows if not r[v]["correct"] and r["d10"]["correct"])
        rep = sum(1 for r in rows if not r[v]["reused"])
        lines.append(f"| {v} | {ex}/{n} = {100 * ex / max(n, 1):.1f}% | {q:.2f} | {b} | {c} | "
                     f"{mcnemar_exact(b, c):.3g} | {rep} |")
    fb = sum(1 for r in rows if r["hybrid"].get("fallback"))
    lines += ["", f"hybrid fallbacks to the D10 card (Q3 only): {fb}", ""]

    funnel = defaultdict(Counter)
    for r in det.values():
        for f in r.get("funnel", []):
            funnel[f["type"]][f["outcome"]] += 1
    outs = ["q1_removed", "settled_written", "settled_dropped", "q3_removed", "ask", "error"]
    lines += ["## New pool cards by type and check outcome", "",
              "| type | " + " | ".join(outs) + " | total |", "|---" * (len(outs) + 2) + "|"]
    for t in sorted(funnel, key=str):
        c = funnel[t]
        lines.append(f"| {t} | " + " | ".join(str(c[o]) for o in outs) + f" | {sum(c.values())} |")
    merged = sum(r.get("merged_into_forward", 0) for r in det.values())
    lines += ["", f"pool cards merged into a forward card by R1: {merged}", ""]

    ex_q = [q for q, r in det.items() if r.get("asked")]
    random.Random(0).shuffle(ex_q)
    lines += ["## Examples", ""]
    for qid in ex_q[:4]:
        r = det[qid]
        lines.append(f"### {qid}")
        lines.append("```\n" + r["pool_block"] + "\n```")
        for a in r["asked"]:
            c = a["card"]
            lines.append(f"- {c.get('type')} 「{c.get('span')}」 response: {a['response']}")
            for p in c.get("interpretations", []):
                lines.append(f"  - {p.get('description', p) if isinstance(p, dict) else p}")
        lines.append("")
    (out / "report.md").write_text("\n".join(lines))
    print("\n".join(lines[:20]))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify"); v.add_argument("--manifest", required=True)
    for name in ("run", "report"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", required=True, choices=["bird", "ambrosia", "clambsql"])
        p.add_argument("--out", default="runs/full_b/task_c")
        p.add_argument("--limit", type=int, default=0, help="smoke test on N questions (seed 0)")
    args = ap.parse_args()
    {"verify": cmd_verify, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
