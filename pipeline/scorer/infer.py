#!/usr/bin/env python3
"""给一组训练卡打分（默认验证集）。

用法：python -m pipeline.scorer.infer [cards.jsonl]
默认读 outputs/scorer/val_set.jsonl，结果写到同目录 scores_<文件名>.jsonl。
选项保持原始顺序。只对 m 个字母做 softmax，不做温度缩放。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# So `python pipeline/scorer/infer.py` works the same as `python -m pipeline.scorer.infer`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import torch
from torch.nn import functional as F

from pipeline.scorer.paths import WORK
from pipeline.scorer import train as tj


def score_rows(model, tokenizer, marks, rows, dest: Path) -> list[dict]:
    model.eval()
    done = {}
    if dest.exists():
        for line in dest.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["card_id"]] = item
    pending = [row for row in rows if row["card_id"] not in done]
    print(f"todo {len(pending)} done {len(done)}", flush=True)
    handle = dest.open("a", encoding="utf-8")
    with torch.inference_mode():
        for start in range(0, len(pending), 2):
            chunk = pending[start:start + 2]
            texts = [row["messages"][0]["content"] for row in chunk]
            picked = tj.batch_logits(model, tokenizer, texts, marks)
            for row, logit in zip(chunk, picked):
                m = row["m"]
                vec = [float(x) for x in F.softmax(logit[:m].float(), dim=-1)]
                top = max(range(m), key=lambda j: (vec[j], -j))
                h = -sum(x * math.log(x) for x in vec if x > 0) / math.log(m)
                item = {
                    "card_id": row["card_id"],
                    "qid": row.get("qid"),
                    "ds": row.get("ds"),
                    "type": row.get("type"),
                    "m": m,
                    "probs": vec,
                    "H_norm": h,
                    "top1": top,
                    "label_kind": row.get("label_kind"),
                }
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                done[row["card_id"]] = item
            if (start + 2) % 100 == 0 or start + 2 >= len(pending):
                handle.flush()
                print(f"{min(start + 2, len(pending))}/{len(pending)}", flush=True)
    handle.close()
    return [done[row["card_id"]] for row in rows]


def main() -> None:
    cards = Path(sys.argv[1]) if len(sys.argv) > 1 else WORK / "val_set.jsonl"
    if not cards.is_file():
        raise SystemExit(f"找不到卡片文件 {cards}")
    adapter = WORK / "checkpoint"
    if not (adapter / "adapter_config.json").is_file():
        raise SystemExit(f"找不到 adapter {adapter}，请先运行 python -m pipeline.scorer.train")
    rows = tj.load_rows(cards)
    for i, row in enumerate(rows):
        row.setdefault("card_id", f"{row.get('qid', '')}|{i}")
    dest = cards.with_name(f"scores_{cards.stem}.jsonl")
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    tokenizer = AutoTokenizer.from_pretrained(tj.MODEL, trust_remote_code=True)
    marks = tj.letter_ids(tokenizer)
    base = AutoModelForCausalLM.from_pretrained(
        tj.MODEL, torch_dtype=torch.bfloat16, trust_remote_code=True, attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base, adapter).cuda()
    model.eval()
    scored = score_rows(model, tokenizer, marks, rows, dest)
    bad = sum(1 for item in scored if abs(sum(item["probs"]) - 1) >= 1e-4)
    print(f"INFER_DONE {dest} n {len(scored)} prob_bad {bad}", flush=True)
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
