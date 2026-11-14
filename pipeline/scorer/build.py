#!/usr/bin/env python3
"""从 outputs/ 里的检出或检查 pred.jsonl 生成打分器训练卡。

用法：
  python -m pipeline.scorer.build --pred outputs/<ds>/.../pred.jsonl --ds birdtrain

可重复传入 --pred，把多份结果合在一起。标签来自金标 SQL（checker）
以及 pred 里模拟用户的作答。有官方 train/val 划分时按划分写出；
否则按数据库做 --val-frac 留出验证集。
结果默认写到 outputs/scorer/build/，不会覆盖官方的 train_set.jsonl / val_set.jsonl。
若要覆盖官方卡，请显式传入 --out outputs/scorer。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# So `python pipeline/scorer/build.py` works the same as `python -m pipeline.scorer.build`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.checks.runtime import load_golds
from pipeline.scorer.card_id import card_id, unique_ids
from pipeline.scorer.checker import choose
from pipeline.gold_target import get_target_gold
from pipeline.scorer.labels import distribute
from pipeline.scorer.paths import BUILD, MODEL
from pipeline.scorer.prompt import user_message
from pipeline.scorer import schema as sch
from schema_text import schema_rich


def _evidence_items(text: str) -> list:
    marker = "User clarification:"
    i = (text or "").find(marker)
    if i < 0:
        return []
    blob = text[i + len(marker):].strip()
    if not blob or blob == "{}":
        return []
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _choice_keys(choice) -> set[str]:
    if not isinstance(choice, dict):
        text = str(choice).strip()
        return {text} if text else set()
    bag = {
        str(choice.get("desc") or "").strip(),
        str(choice.get("interpretation") or "").strip(),
    }
    for element in choice.get("elements") or []:
        if not isinstance(element, (dict, list)):
            bag.add(str(element).strip())
    return {item for item in bag if item}


def _match_choice(item: dict, choices: list) -> int | None:
    keys = [str(item.get("interpretation") or "").strip()]
    snippet = item.get("mapping_snippet")
    if isinstance(snippet, str):
        keys.append(snippet.strip())
    elif isinstance(snippet, list):
        keys.extend(str(x).strip() for x in snippet if not isinstance(x, (dict, list)))
    keys = [key for key in keys if key]
    for i, choice in enumerate(choices):
        if _choice_keys(choice) & set(keys):
            return i
    return None


def cards_from_pred(row: dict, source: str) -> list[dict]:
    ev_items = _evidence_items(row.get("evidence_out") or "")
    out = []
    for index, card in enumerate(row.get("ask_cards") or []):
        choices = card.get("choices") or []
        options = []
        for choice in choices:
            if isinstance(choice, dict):
                options.append(str(choice.get("desc") or ""))
            else:
                options.append(str(choice))
        if len(options) < 2:
            continue
        span = card.get("span") or ""
        typ = card.get("ambig_type") or card.get("type") or ""
        hits = [
            item for item in ev_items
            if item.get("nl_span") == span and (item.get("type") or "") == typ
        ]
        sim = _match_choice(hits[0], choices) if hits else None
        raw = ""
        if hits:
            raw = str(hits[0].get("interpretation") or "")
        out.append({
            "ask_index": index,
            "source": card.get("source") or source,
            "span": span,
            "type": typ,
            "options": options,
            "choices": choices,
            "sim_index": sim,
            "sim_answer_raw": raw or None,
        })
    return out


def _tokenizer():
    path = Path(str(MODEL))
    if not (path.is_file() or (path / "config.json").is_file()):
        print(f"未找到基座模型 {path}，schema 长度按字符近似，可用 SCORER_MODEL 指定", flush=True)
        return None
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(str(path), trust_remote_code=True)
    except Exception as exc:
        print(f"加载分词器失败（{exc}），schema 长度按字符近似", flush=True)
        return None


def _n_tokens(tokenizer):
    if tokenizer is None:
        return lambda text: (len(text) + 3) // 4

    def count(text: str) -> int:
        try:
            ids = tokenizer.apply_chat_template(
                [{"role": "user", "content": text}],
                add_generation_prompt=True,
                enable_thinking=False,
                tokenize=True,
            )
        except TypeError:
            ids = tokenizer.apply_chat_template(
                [{"role": "user", "content": text}],
                add_generation_prompt=True,
                tokenize=True,
            )
        if hasattr(ids, "input_ids"):
            ids = ids["input_ids"]
        return len(list(ids))

    return count


def _assign_split(made: list[dict], golds: dict, val_frac: float) -> None:
    official = 0
    for row in made:
        gold = golds.get(row["qid"])
        split = str(((getattr(gold, "meta", None) or {}).get("split") if gold is not None else "") or "")
        row["split"] = split if split in {"train", "val"} else ""
        if row["split"]:
            official += 1
    if official:
        for row in made:
            if not row["split"]:
                row["split"] = "drop"
        print(f"使用官方划分：train/val 标记 {official}/{len(made)} 张卡", flush=True)
        return
    # Hold out by database so the same db does not appear on both sides.
    by_db: dict[str, list[dict]] = defaultdict(list)
    for row in made:
        by_db[str(row.get("db") or "")].append(row)
    names = sorted(by_db)
    n_val = max(1, int(round(len(names) * val_frac))) if names and val_frac > 0 else 0
    val_dbs = set(names[:n_val])
    for db, rows in by_db.items():
        split = "val" if db in val_dbs else "train"
        for row in rows:
            row["split"] = split
    print(f"无官方划分，按库留出验证集：val_dbs={len(val_dbs)}/{len(names)} val_frac={val_frac}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="从 outputs/ 的 pred.jsonl 生成打分器训练卡")
    ap.add_argument("--pred", type=Path, action="append", required=True, help="检出或检查的 pred.jsonl，可重复")
    ap.add_argument("--ds", required=True, help="gold 数据集名，如 birdtrain、bird_arcwise")
    ap.add_argument("--out", type=Path, default=BUILD, help="写出 train_set.jsonl / val_set.jsonl 的目录，默认 outputs/scorer/build")
    ap.add_argument("--val-frac", type=float, default=0.1, help="没有官方划分时，按库留出的验证比例")
    ap.add_argument("--tag", default="", help="写入 source 字段的标签，默认用 pred 所在目录名")
    args = ap.parse_args()
    if args.ds in {"bird_arcwise", "ambrosia", "clambsql"}:
        print(
            f"注意：{args.ds} 通常是评测集。训练打分器请优先用 birdtrain 上的检出或检查结果。",
            flush=True,
        )

    golds = {g.id: g for g in load_golds(args.ds)}
    tokenizer = _tokenizer()
    n_tokens = _n_tokens(tokenizer)
    rich_cache: dict[str, dict] = {}
    type_cache: dict[str, dict] = {}
    made: list[dict] = []
    raw_ids: list[str] = []

    for pred_path in args.pred:
        source = args.tag or pred_path.parent.name
        print(f"读 {pred_path}  tag={source}", flush=True)
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row.get("id") or row.get("qid") or "")
            gold = golds.get(qid)
            if gold is None:
                continue
            gold_sql = get_target_gold(qid) or str(getattr(gold, "gold_sql", "") or "")
            db_path = gold.db_path or ""
            if db_path not in rich_cache:
                try:
                    rich_cache[db_path] = schema_rich(gold, with_examples=True)
                except Exception:
                    rich_cache[db_path] = {}
            if db_path not in type_cache:
                type_cache[db_path] = sch.column_types(db_path)
            evidence = str((gold.meta or {}).get("evidence") or "")
            for card in cards_from_pred(row, source):
                if not (2 <= len(card["options"]) <= 26):
                    continue
                gold_set = []
                for idx in choose(gold.question, gold_sql, card["options"]):
                    if idx not in gold_set:
                        gold_set.append(idx)
                target, kind = distribute(len(card["options"]), card["sim_index"], gold_set)
                opts = []
                for i, text in enumerate(card["options"]):
                    choice = card["choices"][i] if i < len(card["choices"]) and isinstance(card["choices"][i], dict) else {}
                    binding = (
                        json.dumps(choice.get("elements"), ensure_ascii=False)
                        if choice.get("elements")
                        else "none"
                    )
                    opts.append({"description": text, "binding": binding})
                wanted = sch.tables_in(card["options"], card["choices"])
                rows = sch.schema_rows(rich_cache[db_path], type_cache[db_path], wanted)
                if not rows:
                    rows = sch.schema_rows(rich_cache[db_path], type_cache[db_path], set())
                sch.mark_bound(rows, card["choices"])

                def count(text: str, card=card, opts=opts) -> int:
                    return n_tokens(user_message(
                        gold.db_id or "", gold.question or "", evidence, text,
                        card["span"], card["type"], opts,
                    ))

                schema, truncated = sch.fit_schema(rows, count)
                content = user_message(
                    gold.db_id or "", gold.question or "", evidence, schema,
                    card["span"], card["type"], opts,
                )
                cid = card_id(qid, card["ask_index"], card["type"], card["span"])
                raw_ids.append(cid)
                made.append({
                    "card_id": cid,
                    "qid": qid,
                    "db": gold.db_id or "",
                    "split": "",
                    "source": card["source"],
                    "type": card["type"],
                    "m": len(card["options"]),
                    "messages": [{"role": "user", "content": content}],
                    "target": target,
                    "label_kind": kind,
                    "sim_answer_raw": card["sim_answer_raw"],
                    "truncated": truncated,
                })

    ids = unique_ids(raw_ids)
    for row, cid in zip(made, ids):
        row["card_id"] = cid
    _assign_split(made, golds, args.val_frac)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, split in (("train_set.jsonl", "train"), ("val_set.jsonl", "val")):
        rows = [row for row in made if row["split"] == split]
        path = args.out / name
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(name, len(rows), "kind", {k: sum(1 for r in rows if r["label_kind"] == k) for k in sorted({r["label_kind"] for r in rows})}, flush=True)
    dropped = sum(1 for row in made if row["split"] not in {"train", "val"})
    if dropped:
        print(f"未写入（无划分）{dropped} 张卡", flush=True)
    print("DONE", args.out / "train_set.jsonl", args.out / "val_set.jsonl", flush=True)


if __name__ == "__main__":
    main()
