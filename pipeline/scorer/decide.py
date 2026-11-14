"""检测提问前的 Auto/Ask 判定。默认关闭，不在 import 时加载模型。"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

_lock = threading.Lock()
_bundle: tuple[Any, Any, Any, str] | None = None
_schema_cache: dict[str, tuple[dict, dict]] = {}


def enabled() -> bool:
    return (os.environ.get("SCORER_ENABLE") or "").strip().lower() in {"1", "true", "yes"}


def device_name() -> str:
    env = (os.environ.get("SCORER_DEVICE") or "").strip()
    if env:
        return env
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def ready() -> tuple[bool, str]:
    from pathlib import Path
    from pipeline.scorer.paths import MODEL, WORK

    adapter = WORK / "checkpoint"
    if not (adapter / "adapter_config.json").is_file():
        return False, f"找不到 scorer adapter：{adapter}"
    path = Path(str(MODEL))
    if not (path.is_file() or (path / "config.json").is_file()):
        return False, f"找不到基座模型 {path}，请设置 SCORER_MODEL"
    return True, ""


def _require_ready() -> None:
    ok, msg = ready()
    if not ok:
        raise SystemExit(f"已设置 SCORER_ENABLE，但{msg}")


def _schema_pack(gold) -> tuple[dict, dict]:
    from pipeline.scorer import schema as sch

    db_path = str(getattr(gold, "db_path", "") or "")
    key = db_path or f"id:{id(gold)}"
    hit = _schema_cache.get(key)
    if hit is not None:
        return hit
    try:
        from schema_text import schema_rich
        rich = schema_rich(gold, with_examples=True) or {}
    except Exception:
        rich = {}
    types = sch.column_types(db_path) if db_path else {}
    _schema_cache[key] = (rich, types)
    return rich, types


def _options_and_bindings(card: dict) -> tuple[list[str], list[dict], list[dict]]:
    choices = list(card.get("choices") or [])
    if not choices:
        choices = [{"desc": t, "elements": [t]} for t in (card.get("cands") or [])]
    texts: list[str] = []
    opts: list[dict] = []
    for ch in choices:
        if isinstance(ch, dict):
            text = str(ch.get("desc") or "")
            binding = json.dumps(ch.get("elements"), ensure_ascii=False) if ch.get("elements") else "none"
        else:
            text = str(ch)
            binding = json.dumps([ch], ensure_ascii=False)
        texts.append(text)
        opts.append({"description": text, "binding": binding})
    return texts, opts, choices


def _load():
    global _bundle
    if _bundle is not None:
        return _bundle
    _require_ready()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from pipeline.scorer.paths import MODEL, WORK
    from pipeline.scorer import train as tj

    device = device_name()
    adapter = str(WORK / "checkpoint")
    print(f"[scorer] 加载 {MODEL} + LoRA → {device}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL), trust_remote_code=True)
    dtype = torch.bfloat16 if str(device).startswith("cuda") else torch.float32
    base = AutoModelForCausalLM.from_pretrained(
        str(MODEL), torch_dtype=dtype, trust_remote_code=True, attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base, adapter)
    model.to(device)
    model.eval()
    _bundle = (model, tokenizer, tj.letter_ids(tokenizer), device)
    return _bundle


def apply_to_cards(gold, cards: list[dict], evidence: str = "") -> None:
    """给每张卡写入 card["scorer"] = {H_norm, top1, auto, theta, ...}。"""
    _require_ready()
    import math
    import torch
    from torch.nn import functional as F
    from pipeline.scorer.paths import theta_star
    from pipeline.scorer.prompt import user_message
    from pipeline.scorer import schema as sch
    from pipeline.scorer import train as tj
    evidence = (evidence or "").strip()
    if evidence == "NULL":
        evidence = ""
    theta = theta_star()
    with _lock:
        model, tokenizer, marks, device = _load()

    rich, types = _schema_pack(gold)
    db_id = getattr(gold, "db_id", None) or ""
    question = getattr(gold, "question", None) or ""
    texts: list[str] = []
    index: list[int] = []
    ms: list[int] = []
    for i, card in enumerate(cards):
        option_texts, opts, choices = _options_and_bindings(card)
        m = len(option_texts)
        if not (2 <= m <= 26):
            card["scorer"] = {"auto": False, "skipped": True, "m": m, "theta": theta}
            continue
        typ = card.get("ambig_type") or card.get("type") or ""
        span = card.get("span") or ""
        wanted = sch.tables_in(option_texts, choices)
        rows = sch.schema_rows(rich, types, wanted) or sch.schema_rows(rich, types, set())
        sch.mark_bound(rows, choices)

        def count(text: str, _opts=opts, _typ=typ, _span=span) -> int:
            return len(tj.apply_ids(
                tokenizer,
                user_message(db_id, question, evidence, text, _span, _typ, _opts),
            ))

        schema, _trunc = sch.fit_schema(rows, count)
        texts.append(user_message(db_id, question, evidence, schema, span, typ, opts))
        index.append(i)
        ms.append(m)

    if not texts:
        return

    with _lock:
        model, tokenizer, marks, device = _load()
        for start in range(0, len(texts), 2):
            chunk = texts[start:start + 2]
            ids = index[start:start + 2]
            chunk_m = ms[start:start + 2]
            logits = tj.batch_logits(model, tokenizer, chunk, marks, device=device)
            for row, card_i, m in zip(logits, ids, chunk_m):
                vec = F.softmax(row[:m].float(), dim=0)
                p = vec.tolist()
                top = int(torch.argmax(vec).item())
                ent = 0.0
                for x in p:
                    if x > 0:
                        ent -= x * math.log(x)
                h = ent / math.log(m) if m > 1 else 0.0
                cards[card_i]["scorer"] = {
                    "H_norm": round(h, 6),
                    "top1": top,
                    "auto": bool(h <= theta),
                    "theta": theta,
                    "m": m,
                    "probs": [round(x, 6) for x in p],
                }
