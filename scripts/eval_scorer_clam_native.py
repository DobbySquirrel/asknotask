#!/usr/bin/env python3
"""Scorer on CLAMBSQL native clarification options (not sim-user labels).

Setup
-----
- Input: question, schema, evidence=None (never clarification_context),
  native span/options from gold_ambiguity.
- Invisible at inference: gold SQL, clear_ambiguity / gold option, clarification_context.
- Model: frozen LoRA at outputs/scorer/checkpoint; θ* from BIRD-train val (no re-tune on CLAM).
- Label: native clear_ambiguity; hit-any over gold_indices (CLAM has one gold each).
- Train/θ data: BIRD-train only; CLAM never used.

Metrics: full-sample top-1 accuracy, Auto coverage @ θ*, Auto accuracy @ θ*,
with counts; breakdown by ambig_type (dataset raw + scorer type).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import torch
from torch.nn import functional as F

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from pipeline.scorer.paths import MODEL, REPO, WORK, clambsql_json, theta_star
from pipeline.scorer import train as tj
from pipeline.scorer.prompt import user_message

CLAM_JSON = clambsql_json()
ADAPTER = WORK / "checkpoint"
THETA = theta_star()  # birdtrain val / select_theta, overridable with SCORER_THETA
OUT = REPO / "outputs/analysis/scorer_clam_native"

TYPE_MAP = {
    "column": "Column",
    "table": "Column",
    "join": "Join",
    "aggregate": "Aggregate",
    "vague": "Project",
    "attachment": "Attachment",
    "scope": "Scope",
}


def parse_amb(raw):
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = raw.strip()
        return json.loads(raw) if raw else {}
    if isinstance(raw, dict) and "query" in raw and "match" in raw:
        q, m = raw["query"], raw["match"]
        if isinstance(q, str):
            q = json.loads(q) if q.strip() else {}
        if isinstance(m, str):
            m = json.loads(m) if m.strip() else {}
        return {"query": q or {}, "match": m or {}}
    return raw


def canon(x) -> str:
    if isinstance(x, (dict, list)):
        return json.dumps(x, ensure_ascii=False, sort_keys=True)
    return str(x)


def match_opts(table_dicts):
    out = []
    for d in table_dicts:
        if isinstance(d, dict):
            parts = []
            for t, cols in d.items():
                for c in cols or []:
                    parts.append(f"{t}.{c}")
            desc = "Map to " + " + ".join(parts) if parts else canon(d)
            out.append({"description": desc, "binding": canon(d), "raw": d})
        else:
            out.append({"description": str(d), "binding": str(d), "raw": d})
    return out


def query_opts(interps):
    return [{"description": str(s), "binding": str(s), "raw": s} for s in interps]


def gold_idxs(opts, clear_val):
    hits = [i for i, o in enumerate(opts) if o["raw"] == clear_val]
    if hits:
        return hits
    c = canon(clear_val)
    return [i for i, o in enumerate(opts) if canon(o["raw"]) == c]


def build_cards() -> tuple[list[dict], dict]:
    data = json.loads(CLAM_JSON.read_text(encoding="utf-8"))
    cards = []
    skip = Counter()
    for r in data:
        amb = parse_amb(r.get("gold_ambiguity"))
        clear = parse_amb(r.get("clear_ambiguity"))
        if not isinstance(clear, dict):
            clear = {}
        if not (isinstance(amb, dict) and ("query" in amb or "match" in amb)):
            skip["bad_amb"] += 1
            continue
        qmap = amb.get("query") or {}
        mmap = amb.get("match") or {}
        typ = TYPE_MAP[r["ambig_type"]]
        schema = r.get("schema_with_content") or r.get("schema_without_content") or ""
        base = {
            "qid": f"clambsql:{r['index']}",
            "db_id": r["db_id"],
            "ambig_type_raw": r["ambig_type"],
            "type": typ,
            "question": r["question"],
            "schema": schema,
            "evidence": "",  # do not leak clarification_context
        }
        for span, interps in (qmap or {}).items():
            opts = query_opts(interps or [])
            if len(opts) < 2:
                skip["lt2_query"] += 1
                continue
            if span not in clear:
                skip["no_clear_query"] += 1
                continue
            g = gold_idxs(opts, clear[span])
            if not g:
                skip["clear_miss_query"] += 1
                continue
            cards.append({
                **base,
                "span": span,
                "kind": "query",
                "options": [{"description": o["description"], "binding": o["binding"]} for o in opts],
                "gold_indices": g,
                "m": len(opts),
            })
        for span, tdicts in (mmap or {}).items():
            opts = match_opts(tdicts or [])
            if len(opts) < 2:
                skip["lt2_match"] += 1
                continue
            if span not in clear:
                skip["no_clear_match"] += 1
                continue
            g = gold_idxs(opts, clear[span])
            if not g:
                skip["clear_miss_match"] += 1
                continue
            cards.append({
                **base,
                "span": span,
                "kind": "match",
                "options": [{"description": o["description"], "binding": o["binding"]} for o in opts],
                "gold_indices": g,
                "m": len(opts),
            })
    meta = {
        "n_questions_raw": len(data),
        "n_cards": len(cards),
        "n_qids": len({c["qid"] for c in cards}),
        "skip": dict(skip),
        "gold_match_policy": "hit_any_acceptable_option",
        "note": (
            "CLAM clear_ambiguity yields one gold option per card in practice; "
            "agree if top1 ∈ gold_indices. Evidence always empty (clarification_context leaks the answer)."
        ),
        "theta_star": THETA,
        "theta_source": "birdtrain val select_theta (not re-tuned on CLAM)",
        "adapter": str(ADAPTER),
        "train_data": "birdtrain cards only (outputs/scorer/train_set.jsonl)",
    }
    return cards, meta


def make_prompt(card: dict, max_schema_chars: int = 12000) -> str:
    # Keep prompts inside MIG 2g.20gb; training also truncates long contexts.
    schema = card["schema"] or ""
    if len(schema) > max_schema_chars:
        schema = schema[:max_schema_chars] + "\n...[schema truncated]..."
    return user_message(
        db_id=card["db_id"],
        question=card["question"],
        evidence=card["evidence"],
        schema=schema,
        span=card["span"],
        ambig_type=card["type"],
        options=card["options"],
    )


def score(cards: list[dict]) -> list[dict]:
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL), trust_remote_code=True)
    marks = tj.letter_ids(tokenizer)
    base = AutoModelForCausalLM.from_pretrained(
        str(MODEL), torch_dtype=torch.bfloat16, trust_remote_code=True, attn_implementation="sdpa",
    )
    model = PeftModel.from_pretrained(base, str(ADAPTER)).cuda()
    model.eval()

    out_path = OUT / "per_card.jsonl"
    done = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                done[item["card_id"]] = item

    pending = []
    for i, card in enumerate(cards):
        cid = f"{card['qid']}::{card['span']}::{card['kind']}"
        card["card_id"] = cid
        if cid not in done:
            pending.append((i, card))

    print(f"score todo {len(pending)} done {len(done)}", flush=True)
    handle = out_path.open("a", encoding="utf-8")
    with torch.inference_mode():
        for i, (_, card) in enumerate(pending):
            text = make_prompt(card)
            picked = tj.batch_logits(model, tokenizer, [text], marks)
            logit = picked[0]
            m = int(card["m"])
            vec = [float(x) for x in F.softmax(logit[:m].float(), dim=-1)]
            top = max(range(m), key=lambda j: (vec[j], -j))
            h = -sum(x * math.log(x) for x in vec if x > 0) / math.log(m)
            gold = list(card["gold_indices"])
            item = {
                "card_id": card["card_id"],
                "qid": card["qid"],
                "db_id": card["db_id"],
                "ambig_type_raw": card["ambig_type_raw"],
                "type": card["type"],
                "span": card["span"],
                "kind": card["kind"],
                "m": m,
                "probs": vec,
                "H_norm": h,
                "top1": top,
                "gold_indices": gold,
                "hit": top in gold,
                "auto": h <= THETA,
            }
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            done[card["card_id"]] = item
            if (i + 1) % 50 == 0 or i + 1 == len(pending):
                handle.flush()
                torch.cuda.empty_cache()
                print(f"  {i + 1}/{len(pending)}", flush=True)
    handle.close()
    return [done[c["card_id"]] for c in cards]


def summarize(scored: list[dict], meta: dict) -> dict:
    def pack(rows: list[dict]) -> dict:
        n = len(rows)
        hit = sum(1 for r in rows if r["hit"])
        auto = [r for r in rows if r["auto"]]
        auto_hit = sum(1 for r in auto if r["hit"])
        return {
            "n": n,
            "top1_correct": hit,
            "top1_acc": (hit / n) if n else None,
            "n_auto": len(auto),
            "auto_coverage": (len(auto) / n) if n else None,
            "auto_correct": auto_hit,
            "auto_acc": (auto_hit / len(auto)) if auto else None,
        }

    by_raw = {}
    for key in sorted({r["ambig_type_raw"] for r in scored}):
        by_raw[key] = pack([r for r in scored if r["ambig_type_raw"] == key])
    by_type = {}
    for key in sorted({r["type"] for r in scored}):
        by_type[key] = pack([r for r in scored if r["type"] == key])

    # H histogram
    bins = [0] * 10
    for r in scored:
        h = r["H_norm"]
        b = 9 if h >= 1 else min(9, max(0, int(h * 10)))
        bins[b] += 1

    doc = {
        **meta,
        "overall": pack(scored),
        "by_ambig_type_raw": by_raw,
        "by_scorer_type": by_type,
        "H_norm_decile_counts": bins,
    }
    return doc


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not CLAM_JSON.is_file():
        raise SystemExit(
            f"缺少 CLAMBSQL 原始标注: {CLAM_JSON}。把 clambsql.json 放到 dataset/clambsql/ 或设置 CLAM_JSON。"
        )
    cards, meta = build_cards()
    (OUT / "cards_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # save prompts without gold for audit (gold_indices stripped from prompt path only)
    audit = []
    for c in cards[:3]:
        audit.append({"card_id": f"{c['qid']}::{c['span']}::{c['kind']}", "prompt_head": make_prompt(c)[:600]})
    (OUT / "prompt_samples.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("cards", meta["n_cards"], "qids", meta["n_qids"], "skip", meta["skip"], flush=True)
    scored = score(cards)
    doc = summarize(scored, meta)
    (OUT / "summary.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    o = doc["overall"]
    print(
        f"OVERALL top1 {o['top1_correct']}/{o['n']}={o['top1_acc']:.4f} "
        f"auto {o['n_auto']}/{o['n']} cov={o['auto_coverage']:.4f} "
        f"auto_acc {o['auto_correct']}/{o['n_auto']}={o['auto_acc']}",
        flush=True,
    )
    for k, v in doc["by_ambig_type_raw"].items():
        print(
            f"  raw:{k} top1 {v['top1_correct']}/{v['n']} "
            f"auto {v['auto_correct']}/{v['n_auto']} cov={v['auto_coverage']:.3f}",
            flush=True,
        )
    print("DONE", OUT / "summary.json", flush=True)


if __name__ == "__main__":
    main()
