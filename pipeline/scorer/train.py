#!/usr/bin/env python3
"""字母读出训练。有效 batch 32，最多 3 个 epoch，半个 epoch 验证一次。

用法：python -m pipeline.scorer.train
读 outputs/scorer/train_set.jsonl 与 val_set.jsonl，adapter 写到 outputs/scorer/checkpoint。
环境变量 CUDA_VISIBLE_DEVICES 决定用哪张卡。
"""
from __future__ import annotations

import sys
from pathlib import Path

# So `python pipeline/scorer/train.py` works the same as `python -m pipeline.scorer.train`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
import math
import os
import random

import torch
from torch.nn import functional as F

from pipeline.scorer.paths import MODEL, WORK

ROOT = WORK
MAX_LEN = 8192
EFFECTIVE = 32
MAX_EPOCH = 3
LR = 2e-4
LETTERS = [chr(ord("A") + i) for i in range(26)]


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def permute(text: str, target: list[float], rng: random.Random) -> tuple[str, list[float]]:
    head, rest = text.split("[Options]\n", 1)
    body, tail = rest.split("\nWhich option", 1)
    lines = [ln for ln in body.split("\n") if ln.strip()]
    m = len(target)
    if len(lines) != m:
        raise RuntimeError(f"option lines {len(lines)} != m {m}")
    order = list(range(m))
    rng.shuffle(order)
    new_lines = []
    new_target = []
    for new_i, old_i in enumerate(order):
        payload = lines[old_i].split(". ", 1)[1]
        new_lines.append(f"{LETTERS[new_i]}. {payload}")
        new_target.append(target[old_i])
    return head + "[Options]\n" + "\n".join(new_lines) + "\nWhich option" + tail, new_target


def apply_ids(tokenizer, text: str) -> list[int]:
    ids = tokenizer.apply_chat_template(
        [{"role": "user", "content": text}],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    if hasattr(ids, "input_ids"):
        ids = ids["input_ids"]
    ids = [int(x) for x in list(ids)]
    if len(ids) > MAX_LEN:
        ids = ids[-MAX_LEN:]
    return ids


def letter_ids(tokenizer) -> list[int]:
    ids = []
    for letter in LETTERS:
        tok = tokenizer.encode(letter, add_special_tokens=False)
        if len(tok) != 1:
            raise RuntimeError(f"{letter} -> {tok}")
        ids.append(tok[0])
    return ids


def batch_logits(model, tokenizer, texts: list[str], marks: list[int], device=None):
    if device is None:
        device = next(model.parameters()).device
    encoded = [apply_ids(tokenizer, text) for text in texts]
    width = max(len(ids) for ids in encoded)
    batch, mask, lengths = [], [], []
    for ids in encoded:
        pad = width - len(ids)
        batch.append(ids + [tokenizer.pad_token_id] * pad)
        mask.append([1] * len(ids) + [0] * pad)
        lengths.append(len(ids))
    out = model(
        input_ids=torch.tensor(batch, dtype=torch.long, device=device),
        attention_mask=torch.tensor(mask, dtype=torch.long, device=device),
    ).logits
    picked = []
    mark = torch.tensor(marks, dtype=torch.long, device=device)
    for b, n in enumerate(lengths):
        picked.append(out[b, n - 1].index_select(0, mark))
    return picked


def soft_ce(logit_row: torch.Tensor, target: list[float]) -> torch.Tensor:
    m = len(target)
    sel = logit_row[:26].float()
    mask = torch.zeros(26, dtype=torch.bool, device=sel.device)
    mask[:m] = True
    sel = sel.masked_fill(~mask, float("-inf"))
    logp = F.log_softmax(sel, dim=-1)
    q = torch.zeros(26, dtype=torch.float, device=sel.device)
    q[:m] = torch.tensor(target, dtype=torch.float, device=sel.device)
    return -(q * logp.masked_fill(~mask, 0)).sum()


def val_loss(model, tokenizer, rows: list[dict], marks: list[int]) -> float:
    model.eval()
    total = 0.0
    n = 0
    with torch.inference_mode():
        for start in range(0, len(rows), 2):
            chunk = rows[start:start + 2]
            texts = [row["messages"][0]["content"] for row in chunk]
            picked = batch_logits(model, tokenizer, texts, marks)
            for row, logit in zip(chunk, picked):
                total += float(soft_ce(logit, row["target"]))
                n += 1
    model.train()
    return total / max(n, 1)


def main() -> None:
    train_path = ROOT / "train_set.jsonl"
    val_path = ROOT / "val_set.jsonl"
    if not train_path.is_file() or not val_path.is_file():
        raise SystemExit(
            "缺少训练卡。请先运行 python -m pipeline.scorer.build --pred <pred.jsonl> --ds birdtrain，"
            f"或把 train_set.jsonl / val_set.jsonl 放到 {ROOT}"
        )
    out = ROOT / "checkpoint"
    out.mkdir(parents=True, exist_ok=True)
    train_rows = load_rows(train_path)
    val_rows = load_rows(val_path)
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    tokenizer = AutoTokenizer.from_pretrained(MODEL, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    marks = letter_ids(tokenizer)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL, torch_dtype=torch.bfloat16, trust_remote_code=True, attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    ))
    model.cuda()
    model.train()
    opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=LR)
    rng = random.Random(0)
    log_path = out / "train_log.txt"
    steps_per_epoch = math.ceil(len(train_rows) / EFFECTIVE)
    half = max(1, steps_per_epoch // 2)
    print(
        f"train {len(train_rows)} val {len(val_rows)} "
        f"steps/epoch {steps_per_epoch} half {half} cuda {os.environ.get('CUDA_VISIBLE_DEVICES')}",
        flush=True,
    )
    best = float("inf")
    worse = 0
    step = 0
    opt.zero_grad()
    pending = 0
    stop = False
    for epoch in range(MAX_EPOCH):
        order = list(range(len(train_rows)))
        rng.shuffle(order)
        running = 0.0
        seen = 0
        for idx in order:
            if stop:
                break
            row = train_rows[idx]
            text, target = permute(row["messages"][0]["content"], row["target"], rng)
            logit = batch_logits(model, tokenizer, [text], marks)[0]
            loss = soft_ce(logit, target) / EFFECTIVE
            loss.backward()
            pending += 1
            running += float(loss.detach()) * EFFECTIVE
            seen += 1
            if pending < EFFECTIVE:
                continue
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            pending = 0
            step += 1
            if step == 1 or step % 10 == 0:
                line = f"epoch {epoch} step {step} loss {running / seen:.4f}\n"
                log_path.open("a", encoding="utf-8").write(line)
                print(line, end="", flush=True)
            if step % half == 0:
                v = val_loss(model, tokenizer, val_rows, marks)
                line = f"epoch {epoch} step {step} val {v:.4f} best {best:.4f}\n"
                log_path.open("a", encoding="utf-8").write(line)
                print(line, end="", flush=True)
                if v < best - 1e-5:
                    best = v
                    worse = 0
                    model.save_pretrained(out)
                    tokenizer.save_pretrained(out)
                else:
                    worse += 1
                    if worse >= 2:
                        stop = True
                        log_path.open("a", encoding="utf-8").write("early stop\n")
                        print("early stop", flush=True)
        if stop:
            break
    if pending:
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
    if not (out / "adapter_config.json").exists():
        model.save_pretrained(out)
        tokenizer.save_pretrained(out)
    print("TRAIN_DONE", "best", best, flush=True)


if __name__ == "__main__":
    main()
