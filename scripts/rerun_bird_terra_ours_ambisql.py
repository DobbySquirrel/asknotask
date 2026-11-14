#!/usr/bin/env python3
"""Fresh gpt-5.6-terra re-run on BIRD-Arcwise: Ours (train1 θ=0.5 soft) + AmbiSQL soft.

Reads precomputed prompts from outputs/bird_arcwise/terra/jobs/{ours,ambisql}.jsonl
(schema / question / evidence / prompt; no code or paths outside this repo).
Writes under outputs/bird_arcwise/terra/{ours,ambisql}/ then syncs
predictions/gpt56_terra/{ours,ambisql}.jsonl and eval(+rescored).

Needs OPENAI_API_KEY in the environment; OPENAI_BASE_URL optional
(default https://aigc-api.hkust-gz.edu.cn/api/v2).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from utils.llm import parse_sql  # noqa: E402
from evaluator.ex import score as ex_score  # noqa: E402

OUT = REPO / "outputs/bird_arcwise/terra"
JOBS = OUT / "jobs"
WORKERS = int(os.environ.get("TERRA_WORKERS", "8"))
MODEL = "gpt-5.6-terra"
DEFAULT_BASE = "https://aigc-api.hkust-gz.edu.cn/api/v2"


def _base_url() -> str:
    url = (os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE).strip().rstrip("/")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    return url


def client():
    from openai import OpenAI
    import httpx

    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("需要环境变量 OPENAI_API_KEY")
    return OpenAI(
        api_key=key,
        base_url=_base_url(),
        timeout=httpx.Timeout(connect=20.0, read=180.0, write=30.0, pool=20.0),
        max_retries=0,
    )


def call_one(cli, prompt: str) -> dict:
    t0 = time.time()
    resp = cli.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        reasoning_effort="minimal",
        max_completion_tokens=2048,
    )
    dt = time.time() - t0
    usage = resp.usage
    details = getattr(usage, "completion_tokens_details", None) if usage else None
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    return {
        "text": text,
        "latency_s": dt,
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "reasoning_tokens": int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0,
        "finish_reason": resp.choices[0].finish_reason if resp.choices else None,
        "error": None,
    }


def load_jobs(arm: str) -> list[dict]:
    path = JOBS / f"{arm}.jsonl"
    if not path.is_file():
        raise SystemExit(f"缺少 jobs 文件: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    missing = [r.get("id") for r in rows if not r.get("prompt")]
    if missing:
        raise SystemExit(f"{path} 缺 prompt: {missing[:5]}")
    return rows


def done_ids(calls: Path) -> set[str]:
    if not calls.exists():
        return set()
    seen = set()
    for line in calls.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("id") and rec.get("predicted_sql") is not None and not rec.get("error"):
            seen.add(rec["id"])
    return seen


def run_arm(cli, arm: str, jobs: list[dict]) -> Path:
    dest = OUT / arm
    dest.mkdir(parents=True, exist_ok=True)
    calls = dest / "calls.jsonl"
    seen = done_ids(calls)
    todo = [j for j in jobs if j["id"] not in seen]
    print(f"{arm} resume {len(seen)} todo {len(todo)}", flush=True)

    def one(job):
        rec = {"id": job["id"], "arm": arm, "model": MODEL, "system": arm}
        try:
            got = call_one(cli, job["prompt"])
            rec.update(got)
            rec["predicted_sql"] = parse_sql(got.get("text") or "") or ""
            rec["error"] = None
        except Exception as exc:  # noqa: BLE001
            rec["predicted_sql"] = ""
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["traceback"] = traceback.format_exc()
        return rec

    with calls.open("a", encoding="utf-8") as handle:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = [pool.submit(one, j) for j in todo]
            for i, fut in enumerate(as_completed(futs), 1):
                rec = fut.result()
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
                handle.flush()
                if i % 20 == 0 or i == len(todo):
                    print(f"{arm} {i}/{len(todo)} {rec['id']} err={rec.get('error')}", flush=True)

    by: dict[str, dict] = {}
    for line in calls.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if rec.get("id"):
                by[rec["id"]] = rec
    pred = dest / "pred.jsonl"
    lines = []
    for j in jobs:
        r = by.get(j["id"]) or {}
        lines.append(
            json.dumps(
                {
                    "id": j["id"],
                    "predicted_sql": r.get("predicted_sql") or "",
                    "parser": "gpt-5.6-terra",
                    "system": arm,
                    "error": r.get("error"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    pred.write_text("".join(lines), encoding="utf-8")
    print(f"{arm} wrote {pred} n={len(lines)}", flush=True)
    return pred


def dest_summary(arm: str, hit, n, ex) -> str:
    return f"RESULT {arm}: {hit}/{n} = {ex:.2f}%"


def sync_and_score(arm: str, pred: Path) -> dict:
    pred_dst = REPO / f"outputs/bird_arcwise/predictions/gpt56_terra/{arm}.jsonl"
    pred_dst.parent.mkdir(parents=True, exist_ok=True)
    pred_dst.write_text(pred.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"synced {pred_dst}", flush=True)
    res = ex_score("bird_arcwise", pred_dst, workers=16, timeout=30.0, gold_timeout=600.0)
    g = res["gold_key"]
    hit = res["correct"].get(g)
    n = res["n"]
    ex = 100.0 * hit / n if n else 0.0
    payload = {
        "n": n,
        "correct": {"gold": hit},
        "ex": {"gold": ex},
        "gold_key": "gold",
        "source": f"terra/{arm} ({pred})",
        "q": res.get("q", 0.0),
        "q_total": res.get("q_total", 0),
        "rerun_meta": {
            "parser": "gpt-5.6-terra",
            "note": "soft NOTE inserted in evidence",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }
    for kind in ("eval", "eval_rescored"):
        dst = REPO / f"outputs/bird_arcwise/{kind}/gpt56_terra/{arm}.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if kind == "eval_rescored":
            dst.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        else:
            dst.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = dest_summary(arm, hit, n, ex)
    (OUT / arm / "score_askornotask.json").write_text(
        json.dumps({"hit": hit, "n": n, "ex": ex, "full": res}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(summary, flush=True)
    return {"arm": arm, "hit": hit, "n": n, "ex": ex}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"OUT={OUT} workers={WORKERS}", flush=True)
    arms = os.environ.get("TERRA_ARMS", "ours,ambisql").split(",")
    limit = int(os.environ.get("TERRA_LIMIT", "0") or "0")
    jobs_by = {}
    for arm in arms:
        arm = arm.strip()
        if not arm:
            continue
        jobs_by[arm] = load_jobs(arm)
    if limit > 0:
        jobs_by = {k: v[:limit] for k, v in jobs_by.items()}
    for arm, jobs in jobs_by.items():
        n_note = sum(1 for j in jobs if "可能会模糊" in (j.get("prompt") or ""))
        print(f"{arm} jobs {len(jobs)} with_note {n_note}", flush=True)
    cli = client()

    results = []
    with ThreadPoolExecutor(max_workers=max(1, len(jobs_by))) as pool:
        futs = {pool.submit(run_arm, cli, arm, jobs): arm for arm, jobs in jobs_by.items()}
        preds = {}
        for fut in as_completed(futs):
            arm = futs[fut]
            preds[arm] = fut.result()
            print(f"arm done {arm}", flush=True)

    for arm in jobs_by:
        results.append(sync_and_score(arm, preds[arm]))

    (OUT / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DONE", results, flush=True)


if __name__ == "__main__":
    main()
