#!/usr/bin/env python3
"""Forward + Backward(B)：把 B 的澄清卡并进 forward，全部重新作答，再出 SQL 打 EX。

默认：
  forward = outputs/.../detection/forward/pred.jsonl
  B       = outputs/.../detection/backward/b/pred.jsonl
  out     = outputs/.../detection/forward_backward/

无 B 的题直接复用 forward 的 SQL/问数；有 B 的题：cards = forward ∪ B（按 span/_phi_key 去重）→ 08 全答 → evidence 改写 → qwen_coder SQL → evaluator.ex。

用法：
  python pipeline/detection/run_forward_backward.py smoke --limit 3
  python pipeline/detection/run_forward_backward.py all --workers 1
  python pipeline/detection/run_forward_backward.py all --resume --workers 1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ASK = HERE.parents[1]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))

from pipeline.checks.runtime import format_parser, load_golds
from pipeline.detection.run_common import card_key as _card_key, load_jsonl as _load_jsonl, score as _score

DEFAULT_FWD = ASK / "outputs" / "bird_arcwise" / "detection" / "forward" / "pred.jsonl"
DEFAULT_B = ASK / "outputs" / "bird_arcwise" / "detection" / "backward" / "b" / "pred.jsonl"
OUT_ROOT = ASK / "outputs" / "bird_arcwise" / "detection" / "forward_backward"


def _load_golds() -> dict[str, Any]:
    return {g.id: g for g in load_golds("bird_arcwise")}


def _merge_cards(fwd_cards: list, b_cards: list) -> tuple[list[dict], int]:
    """Forward 优先；B 里新 span 追加。返回 (merged, n_from_b)."""
    merged: list[dict] = []
    seen: set[str] = set()
    for c in fwd_cards or []:
        k = _card_key(c)
        if not k or k in seen:
            continue
        if not isinstance(c.get("cands"), list) or len(c.get("cands") or []) < 2:
            continue
        if not isinstance(c.get("choices"), list) or len(c.get("choices") or []) < 2:
            continue
        seen.add(k)
        merged.append(dict(c))
    n_b = 0
    for c in b_cards or []:
        k = _card_key(c)
        if not k or k in seen:
            continue
        if not isinstance(c.get("cands"), list) or len(c.get("cands") or []) < 2:
            continue
        if not isinstance(c.get("choices"), list) or len(c.get("choices") or []) < 2:
            continue
        seen.add(k)
        card = dict(c)
        card["source"] = "backward_b"
        merged.append(card)
        n_b += 1
    return merged, n_b


def _merge_phi(fwd: dict, b: dict) -> dict[str, list]:
    out: dict[str, list] = {}
    for src in (fwd or {}, b or {}):
        for span, cands in (src or {}).items():
            if span in out:
                continue
            if isinstance(cands, list) and len(cands) >= 2:
                out[str(span)] = list(cands)
    return out


def _run_merged(gold, cards: list[dict], phi: dict, llm, format_parser_base) -> dict:
    from pipeline.detection import three_stage as det
    from schema_text import schema_clear_text, schema_map_for_prompt, schema_numbered_rich
    from simulator.compose import apply_rewrite
    from simulator.human_simulator.standard import PickResult
    from utils.llm import parse_sql

    types = {c["span"]: str(c.get("ambig_type") or "") for c in cards if c.get("ambig_type")}
    interps = {
        c["span"]: str(c.get("interpretation") or "")
        for c in cards
        if c.get("interpretation")
    }
    # fill phi holes from cards
    phi_use = dict(phi)
    for c in cards:
        key = c.get("_phi_key") or c.get("span")
        if key and key not in phi_use and isinstance(c.get("cands"), list):
            phi_use[str(key)] = list(c["cands"])

    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = str((gold.meta or {}).get("evidence") or "") or "NULL"
    q = gold.question or ""

    tokens, clarification = det._ask_human_cards(
        gold, llm, cards, q, schema_llm, ev, types, interps,
    )
    pick = PickResult(simulator="fwd_b_08", tokens=tokens, ambiguity_clarification=clarification)
    mapping = det.phi_to_mapping(phi_use)
    q_out, s_out, e_out = apply_rewrite(
        "evidence",
        question=q,
        schema_str=schema,
        schema_map=smap,
        mapping=mapping,
        pick=pick,
        evidence="" if ev == "NULL" else ev,
        schema_formatter=schema_clear_text,
        parser="base",
    )
    prompt = format_parser_base(s_out or "", q_out or q, e_out or "")
    sql = parse_sql(llm.complete(prompt)) or ""
    return {
        "question_out": q_out,
        "schema_out": s_out,
        "evidence_out": e_out,
        "predicted_sql": sql,
        **det.ask_stats(tokens, cards),
        "ask_cards": cards,
        "phi": phi_use,
        "span_types": types,
        "clarification": clarification,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["smoke", "all", "score-only"])
    ap.add_argument("--forward", type=Path, default=DEFAULT_FWD)
    ap.add_argument("--backward-b", type=Path, default=DEFAULT_B)
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=None, help="最多重跑多少道「有 B」的题（smoke 用）")
    ap.add_argument("--ids", default="", help="逗号分隔 qid，只跑这些")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--reuse-non-b", action="store_true", default=True,
                    help="无 B 的题直接复用 forward（默认开）")
    args = ap.parse_args()

    if not args.forward.is_file():
        raise SystemExit(f"missing forward pred: {args.forward}")
    if not args.backward_b.is_file():
        raise SystemExit(f"missing B pred: {args.backward_b}")

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "pred.jsonl"
    score_path = out_dir / "score_paper.json"
    summary_path = out_dir / "summary.json"

    if args.cmd == "score-only":
        metrics = _score(pred_path, score_path)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return

    fwd = _load_jsonl(args.forward)
    bmap = _load_jsonl(args.backward_b)
    golds = _load_golds()
    want = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids else None

    # 凡是有 B 的题都必须合并重跑；limit/ids 只缩小 todo，不能把它们写成 forward-only
    b_ids = set(bmap)
    merge_all = [qid for qid in sorted(fwd) if qid in b_ids]
    merge_ids = list(merge_all)
    if want:
        merge_ids = [q for q in merge_ids if q in want]
    if args.limit is not None:
        merge_ids = merge_ids[: args.limit]

    done: set[str] = set()
    if args.resume and pred_path.is_file():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            qid = row["id"]
            # 有 B 但未真正 merged 的旧行不算完成
            if qid in b_ids and not row.get("merged"):
                continue
            done.add(qid)
    elif pred_path.is_file() and not args.resume:
        pred_path.unlink()
        score_path.unlink(missing_ok=True)

    lock = threading.Lock()
    written = set(done)

    def _write(row: dict) -> None:
        with lock:
            with pred_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            written.add(row["id"])

    if not args.resume or not pred_path.exists():
        n_copy = 0
        with pred_path.open("w", encoding="utf-8") as f:
            for qid, row in sorted(fwd.items()):
                if qid in b_ids:
                    continue  # 留给 merge 重跑
                out = dict(row)
                out["pipeline"] = "forward_only_reuse"
                out["n_from_b"] = 0
                out["merged"] = False
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                written.add(qid)
                n_copy += 1
        print(
            f"[init] reused forward-only {n_copy}; B-overlap {len(merge_all)}; "
            f"this run merge {len(merge_ids)}",
            flush=True,
        )
    else:
        # resume：清掉「有 B 但未 merged」的脏行，避免最终重复
        keep = []
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["id"] in b_ids and not row.get("merged"):
                continue
            keep.append(row)
        pred_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
            encoding="utf-8",
        )
        done = {r["id"] for r in keep}
        print(
            f"[resume] kept {len(done)}; B-overlap {len(merge_all)}; "
            f"to_merge left {sum(1 for q in merge_ids if q not in done)}",
            flush=True,
        )

    todo = [q for q in merge_ids if q not in done]
    print(f"[merge] B∩forward={len(merge_ids)} todo={len(todo)} port={args.port} workers={args.workers}", flush=True)

    from utils.llm import LLM

    format_parser_base = format_parser("fb")
    llm0 = LLM(url=f"http://127.0.0.1:{args.port}/v1")
    t0 = time.time()
    stats = {"n_b_cards": 0, "n_fwd_cards": 0, "n_merged_cards": 0}

    def work(qid: str) -> dict:
        gold = golds[qid]
        fr, br = fwd[qid], bmap[qid]
        fwd_cards = list(fr.get("ask_cards") or (fr.get("meta") or {}).get("ask_cards") or [])
        b_cards = list(br.get("ask_cards") or (br.get("meta") or {}).get("ask_cards") or [])
        cards, n_b = _merge_cards(fwd_cards, b_cards)
        phi = _merge_phi(fr.get("phi") or (fr.get("meta") or {}).get("phi") or {}, br.get("phi") or {})
        got = _run_merged(gold, cards, phi, llm0, format_parser_base)
        row = {
            "id": qid,
            "db_id": getattr(gold, "db_id", None) or fr.get("db_id"),
            "system": "forward_backward",
            "pipeline": "forward_plus_b",
            "parser": "qwen_coder",
            "merged": True,
            "n_from_b": n_b,
            "n_fwd_cards": len(fwd_cards),
            "n_b_cards": len(b_cards),
            "baseline_n_asked": fr.get("n_asked"),
            "b_n_asked": br.get("n_asked"),
            **got,
            "meta": {
                "forward_source": str(args.forward),
                "b_source": str(args.backward_b),
                "n_from_b": n_b,
            },
        }
        return row

    if todo:
        # 单端口时串行更稳；workers>1 仍共用同一 LLM 对象需小心，这里强制串行调用 complete
        workers = max(1, min(args.workers, 1 if args.port else args.workers))
        if workers == 1:
            for i, qid in enumerate(todo, 1):
                row = work(qid)
                _write(row)
                stats["n_b_cards"] += int(row.get("n_b_cards") or 0)
                stats["n_fwd_cards"] += int(row.get("n_fwd_cards") or 0)
                stats["n_merged_cards"] += int(row.get("n_asked") or 0)
                print(
                    f"  [{i}/{len(todo)}] {qid} cards={row['n_asked']} "
                    f"(fwd {row['n_fwd_cards']}+b_new {row['n_from_b']}) "
                    f"{(time.time()-t0)/60:.1f}m",
                    flush=True,
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(work, q): q for q in todo}
                for i, fut in enumerate(as_completed(futs), 1):
                    row = fut.result()
                    _write(row)
                    print(f"  [{i}/{len(todo)}] {row['id']} cards={row['n_asked']}", flush=True)

    # 汇总 Q
    rows = [json.loads(l) for l in pred_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 去重保序
    by_id = {r["id"]: r for r in rows}
    rows = [by_id[k] for k in sorted(by_id)]
    pred_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    q_mean = sum(float(r.get("n_asked") or 0) for r in rows) / max(1, len(rows))
    q_sum = sum(float(r.get("n_asked") or 0) for r in rows)
    n_merged = sum(1 for r in rows if r.get("merged"))
    print(f"[Q] n={len(rows)} sum={q_sum:.0f} mean={q_mean:.4f} merged_qids={n_merged}", flush=True)

    metrics = _score(pred_path, score_path)
    # baseline EX from forward score if present
    base_score = args.forward.parent / "score_paper.json"
    baseline = {}
    if base_score.is_file():
        blob = json.loads(base_score.read_text(encoding="utf-8"))
        sm = blob.get("summary") if isinstance(blob.get("summary"), dict) else blob
        ex = sm.get("ex") if isinstance(sm, dict) else None
        if isinstance(ex, dict):
            baseline = {"ex": ex.get("ex"), "n_hit": ex.get("n_hit"), "n": ex.get("n")}

    summary = {
        "arm": "forward_backward",
        "forward": str(args.forward),
        "backward_b": str(args.backward_b),
        "n": len(rows),
        "n_merged_with_b": n_merged,
        "Q_sum": q_sum,
        "Q_mean": q_mean,
        "ex": metrics.get("ex"),
        "n_hit": metrics.get("n_hit"),
        "baseline": baseline,
        "delta_ex": (
            (metrics.get("ex") - baseline["ex"])
            if metrics.get("ex") is not None and baseline.get("ex") is not None
            else None
        ),
        "elapsed_min": (time.time() - t0) / 60.0,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
