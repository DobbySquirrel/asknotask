#!/usr/bin/env python3
"""在验证卡上选 θ*。不读测试集。

用法：python -m pipeline.scorer.select_theta
读 outputs/scorer/val_set.jsonl 和 checkpoint，写出 outputs/scorer/select_theta.json。
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# So `python pipeline/scorer/select_theta.py` works the same as `python -m pipeline.scorer.select_theta`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch
from torch.nn import functional as F

from pipeline.scorer.paths import WORK
from pipeline.scorer import train as tj


VAL = WORK / "val_set.jsonl"
ADAPTER = WORK / "checkpoint"
OUT = WORK / "select_theta.json"
THETAS = [i / 10 for i in range(1, 10)]
ALPHA = 0.9


def accepted(target: list[float], kind: str) -> set[int]:
    """onehot / multi：质量最大的下标。others（都不是）没有可对上的选项。"""
    if kind == "others":
        return set()
    hi = max(target) if target else 0.0
    return {i for i, x in enumerate(target) if abs(x - hi) < 1e-8}


def score(rows: list[dict]) -> list[dict]:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    if not (ADAPTER / "adapter_config.json").is_file():
        raise SystemExit(f"找不到 adapter {ADAPTER}，请先运行 python -m pipeline.scorer.train")
    out_path = WORK / "theta_scores.jsonl"
    done = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["i"]] = item
    pending = [r for r in rows if r["i"] not in done]
    print(f"todo {len(pending)} done {len(done)}", flush=True)
    if not pending:
        return [done[r["i"]] for r in rows]
    tokenizer = AutoTokenizer.from_pretrained(tj.MODEL, trust_remote_code=True)
    marks = tj.letter_ids(tokenizer)
    base = AutoModelForCausalLM.from_pretrained(
        tj.MODEL, torch_dtype=torch.bfloat16, trust_remote_code=True, attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base, ADAPTER).cuda()
    model.eval()
    handle = out_path.open("a", encoding="utf-8")
    with torch.inference_mode():
        for start in range(0, len(pending), 4):
            chunk = pending[start:start + 4]
            texts = [r["messages"][0]["content"] for r in chunk]
            picked = tj.batch_logits(model, tokenizer, texts, marks)
            for row, logit in zip(chunk, picked):
                m = int(row["m"])
                vec = [float(x) for x in F.softmax(logit[:m].float(), dim=-1)]
                top = max(range(m), key=lambda j: (vec[j], -j))
                h = -sum(x * math.log(x) for x in vec if x > 0) / math.log(m)
                gold = accepted(row["target"], row.get("label_kind") or "")
                item = {
                    "i": row["i"],
                    "qid": row.get("qid"),
                    "source": row.get("source"),
                    "type": row.get("type"),
                    "m": m,
                    "probs": vec,
                    "H_norm": h,
                    "top1": top,
                    "agree": top in gold,
                    "label_kind": row.get("label_kind"),
                }
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                done[item["i"]] = item
            if (start + 4) % 100 == 0 or start + 4 >= len(pending):
                handle.flush()
                print(f"{min(start + 4, len(pending))}/{len(pending)}", flush=True)
    handle.close()
    return [done[r["i"]] for r in rows]


def sweep(rows: list[dict]) -> dict:
    usable = list(rows)
    table = []
    chosen = None
    for theta in THETAS:
        auto = [r for r in usable if r["H_norm"] <= theta]
        hit = sum(1 for r in auto if r["agree"])
        agree = (hit / len(auto)) if auto else None
        table.append({
            "theta": theta,
            "n_auto": len(auto),
            "n_agree": hit,
            "agreement": agree,
            "auto_rate": len(auto) / len(usable) if usable else None,
        })
        if agree is not None and agree >= ALPHA:
            chosen = theta
    groups = defaultdict(list)
    theta = chosen if chosen is not None else 0.1
    for r in usable:
        if r["H_norm"] <= theta:
            groups[(r.get("source"), r.get("type"))].append(r)
    by = []
    for (src, typ), items in sorted(groups.items()):
        by.append({
            "source": src,
            "type": typ,
            "n_auto": len(items),
            "agreement": sum(1 for r in items if r["agree"]) / len(items),
        })
    auto_rate = None
    if chosen is not None:
        auto_rate = table[[t["theta"] for t in table].index(chosen)]["auto_rate"]
    return {
        "n": len(rows),
        "n_others": sum(1 for r in rows if r.get("label_kind") == "others"),
        "theta_star": chosen,
        "alpha": ALPHA,
        "sweep": table,
        "by_source_type": by,
        "auto_rate_all": auto_rate,
    }


def main() -> None:
    if not VAL.is_file():
        raise SystemExit(f"找不到验证卡 {VAL}，请先运行 python -m pipeline.scorer.build")
    rows = []
    for i, line in enumerate(VAL.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        row["i"] = i
        rows.append(row)
    print("val", len(rows), flush=True)
    scored = score(rows)
    doc = sweep(scored)
    # Keep a short headline next to the sweep so theta_star() can read this file.
    doc["val_cards"] = doc["n"]
    if doc["theta_star"] is not None:
        row = next(item for item in doc["sweep"] if item["theta"] == doc["theta_star"])
        doc["val_auto"] = row["n_auto"]
        doc["val_auto_pct"] = round(100.0 * (row["auto_rate"] or 0.0), 1)
        doc["val_agree_pct"] = round(100.0 * (row["agreement"] or 0.0), 1)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("theta_star", doc["theta_star"], "auto", doc["auto_rate_all"], "DONE", OUT, flush=True)


if __name__ == "__main__":
    main()
