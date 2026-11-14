#!/usr/bin/env python3
"""Forward+B + Coverage(C)：在 forward_backward 结果上跑 draft 覆盖补问，再打 EX。

默认：
  base    = outputs/.../detection/forward_backward/pred.jsonl
  groups  = outputs/.../detection/backward/groups.jsonl
  cover   = pipeline/detection/prompts/06p_cover.md
  out     = outputs/.../detection/forward_backward_coverage/

流程：
  - 无 differ 的题：直接复用 forward+B
  - 有 differ：用现有 ask_cards + draft groups 跑 06p_cover
  - 若有未覆盖组且产出新题：转成卡，cards = (fwd∪B) ∪ C_new → 08 全答 → evidence 改写 → SQL
  - 否则复用 forward+B

用法：
  python pipeline/detection/run_forward_backward_coverage.py smoke --limit 2
  python pipeline/detection/run_forward_backward_coverage.py all --workers 1
  python pipeline/detection/run_forward_backward_coverage.py all --resume --workers 1
"""
from __future__ import annotations

import argparse
import json
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

from pipeline.checks.runtime import format_parser
from pipeline.detection.run_common import card_key, load_jsonl as _load_jsonl, score as _score, specs_to_cards as _specs_to_cards

def _card_key(card: dict) -> str:
    return card_key(card, phrase=True)


DEFAULT_BASE = ASK / "outputs" / "bird_arcwise" / "detection" / "forward_backward" / "pred.jsonl"
DEFAULT_GROUPS = ASK / "outputs" / "bird_arcwise" / "detection" / "backward" / "groups.jsonl"
COVER_PROMPT = HERE / "prompts" / "06p_cover.md"
OUT_ROOT = ASK / "outputs" / "bird_arcwise" / "detection" / "forward_backward_coverage"


def _load_golds() -> dict[str, Any]:
    from pipeline.checks.runtime import load_golds

    return {g.id: g for g in load_golds("bird_arcwise")}


def _valid_card(card: dict) -> bool:
    if not _card_key(card):
        return False
    if not isinstance(card.get("cands"), list) or len(card.get("cands") or []) < 2:
        return False
    if not isinstance(card.get("choices"), list) or len(card.get("choices") or []) < 2:
        return False
    return True


def _cards_of(row: dict) -> list[dict]:
    raw = row.get("ask_cards") or (row.get("meta") or {}).get("ask_cards") or []
    return [dict(c) for c in raw if isinstance(c, dict) and _valid_card(c)]


def _card_type(card: dict) -> str:
    return str(card.get("ambig_type") or "").strip()


def _cand_norm(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    if text.startswith("{") or text.startswith("["):
        try:
            import ast
            parsed = ast.literal_eval(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    return text


def _sync_choices(card: dict) -> None:
    choices = []
    for item in card.get("cands") or []:
        if isinstance(item, dict):
            choices.append({"desc": json.dumps(item, ensure_ascii=False), "elements": [item]})
        else:
            choices.append({"desc": str(item), "elements": [item]})
    card["choices"] = choices


def _union_readings(dst: dict, src: dict) -> int:
    seen = {_cand_norm(item) for item in (dst.get("cands") or [])}
    cands = list(dst.get("cands") or [])
    added = 0
    for item in src.get("cands") or []:
        key = _cand_norm(item)
        if key in seen:
            continue
        seen.add(key)
        cands.append(item)
        added += 1
    if added:
        dst["cands"] = cands
        _sync_choices(dst)
        dst["cover_merged"] = True
    return added


def _append_cover_card(merged: list[dict], seen: set[str], card: dict) -> int:
    orig = str(card.get("span") or card.get("_phi_key") or "").strip()
    key = _card_key(card)
    if key in seen:
        card["cover_of"] = orig
        new_span = f"{orig}\n[cover]"
        n = 2
        while _card_key({"span": new_span}) in seen:
            new_span = f"{orig}\n[cover{n}]"
            n += 1
        card["span"] = new_span
        card["_phi_key"] = new_span
        key = _card_key(card)
    seen.add(key)
    card["source"] = "coverage_c"
    merged.append(card)
    return 1


def _merge_cards(base_cards: list, c_cards: list, policy: str = "combine") -> tuple[list[dict], dict]:
    """policy=add: 旧行为，撞 span 就给 C 加 [cover] 再问一张。
    policy=combine: 同 span 且同类型时把读法合并进原卡，不再额外提问；
    不同类型仍作为新卡追加（必要时加 [cover] 后缀）。"""
    if policy not in {"add", "combine"}:
        raise ValueError(f"unknown C merge policy: {policy}")
    merged: list[dict] = []
    seen: set[str] = set()
    for card in base_cards or []:
        key = _card_key(card)
        if not key or key in seen or not _valid_card(card):
            continue
        seen.add(key)
        merged.append(dict(card))
    stats = {"n_added": 0, "n_merged_into": 0, "n_new_readings": 0}
    for raw in c_cards or []:
        if not _valid_card(raw):
            continue
        card = dict(raw)
        if policy == "combine":
            typ = _card_type(card)
            hit = next((item for item in merged if _card_key(item) == _card_key(card) and _card_type(item) == typ), None)
            if hit is not None:
                added = _union_readings(hit, card)
                stats["n_merged_into"] += 1
                stats["n_new_readings"] += added
                continue
        stats["n_added"] += _append_cover_card(merged, seen, card)
    return merged, stats


def _merge_phi(base: dict, cards: list[dict]) -> dict[str, list]:
    out: dict[str, list] = {}
    for span, cands in (base or {}).items():
        if isinstance(cands, list) and len(cands) >= 2:
            out[str(span)] = list(cands)
    for c in cards:
        key = c.get("_phi_key") or c.get("span")
        if not key or not isinstance(c.get("cands"), list) or len(c["cands"]) < 2:
            continue
        # C 卡（含 [cover] 消歧后）一律写入
        out[str(key)] = list(c["cands"])
    return out


def _groups_of(row: dict | None) -> list[dict]:
    out = []
    n = 0
    for g in (row or {}).get("groups") or []:
        sql = str(g.get("sql") or "").strip()
        fp = str(g.get("fp") or "")
        if not sql or fp.startswith("ERR"):
            continue
        n += 1
        out.append(
            {
                "group_id": n,
                "same_as_no_clarification": bool(g.get("is_y")),
                "sql": sql,
                "preview": g.get("preview") or "",
            }
        )
    return out


def _card_views(cards: list[dict]) -> list[dict]:
    out = []
    for i, c in enumerate(cards):
        readings = []
        for ch in c.get("choices") or []:
            if isinstance(ch, dict):
                readings.append(ch.get("desc") or str(ch.get("elements")))
            else:
                readings.append(str(ch))
        out.append(
            {
                "id": i,
                "span": c.get("span"),
                "type": c.get("ambig_type"),
                "readings": readings,
            }
        )
    return out


def _parse_cover_json(raw: str) -> dict:
    if not raw or "{" not in raw:
        return {}
    try:
        return json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except Exception:
        return {}




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
    phi_use = _merge_phi(phi, cards)
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = str((gold.meta or {}).get("evidence") or "") or "NULL"
    q = gold.question or ""

    tokens, clarification = det._ask_human_cards(
        gold, llm, cards, q, schema_llm, ev, types, interps,
    )
    pick = PickResult(simulator="fwd_b_c_08", tokens=tokens, ambiguity_clarification=clarification)
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



def _cards_signature(cards: list[dict]) -> set[tuple]:
    out = set()
    for card in cards or []:
        norms = tuple(sorted(_cand_norm(item) for item in (card.get("cands") or [])))
        out.add((_card_key(card), _card_type(card), norms))
    return out


def cmd_replay_combine(args) -> None:
    """只改 C 卡合并方式：复用已有 cover_raw，不重新生成 Coverage 问题。
    对有 C 卡的题按 combine 合并后重答；其余题复用旧 coverage pred。
    """
    reuse_pred = args.reuse_pred or (OUT_ROOT / "pred.jsonl")
    cover_raw = args.cover_raw or (OUT_ROOT / "cover_raw.jsonl")
    default_out = ASK / "outputs" / "bird_arcwise" / "detection" / "forward_backward_coverage_combine"
    out_dir = Path(args.out) if args.out is not None else default_out
    # safety: never overwrite the original coverage results
    if out_dir.resolve() == OUT_ROOT.resolve():
        out_dir = default_out
    if not args.base.is_file():
        raise SystemExit(f"missing base pred: {args.base}")
    if not reuse_pred.is_file():
        raise SystemExit(f"missing reuse pred: {reuse_pred}")
    if not cover_raw.is_file():
        raise SystemExit(f"missing cover_raw: {cover_raw}")
    if out_dir.resolve() == reuse_pred.parent.resolve():
        raise SystemExit(f"refusing to overwrite {reuse_pred.parent}")

    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "pred.jsonl"
    score_path = out_dir / "score_paper.json"
    summary_path = out_dir / "summary.json"
    if pred_path.exists() or score_path.exists():
        raise SystemExit(f"refusing to overwrite existing experiment at {out_dir}")

    base = _load_jsonl(args.base)
    reuse = _load_jsonl(reuse_pred)
    covers = _load_jsonl(cover_raw)
    golds = _load_golds()
    from utils.llm import LLM
    format_parser_base = format_parser("fbc")
    llm0 = LLM(url=f"http://127.0.0.1:{args.port}/v1")

    todo = []
    copy_fb = []
    copy_old = []
    plan = []
    for qid, crow in covers.items():
        if int(crow.get("n_c_cards") or 0) <= 0 or int(crow.get("n_uncovered") or 0) <= 0:
            continue
        if qid not in base or qid not in golds:
            continue
        obj = _parse_cover_json(crow.get("raw") or "")
        new_raw = obj.get("new_questions") if isinstance(obj.get("new_questions"), list) else []
        c_cards = _specs_to_cards(new_raw)
        if not c_cards:
            continue
        base_cards = _cards_of(base[qid])
        cards, mstats = _merge_cards(base_cards, c_cards, policy="combine")
        rec = {"id": qid, "cards": cards, "mstats": mstats, "phi": (base[qid].get("phi") or (base[qid].get("meta") or {}).get("phi") or {})}
        if _cards_signature(cards) == _cards_signature(base_cards):
            copy_fb.append(rec)
        else:
            todo.append(rec)
        plan.append({"id": qid, **mstats, "n_cards": len(cards), "n_base": len(base_cards), "rerun": rec in todo})

    for qid in reuse:
        if qid in {r["id"] for r in todo} or qid in {r["id"] for r in copy_fb}:
            continue
        copy_old.append(qid)

    print(
        f"[replay-combine] reuse={len(copy_old)} copy_fb={len(copy_fb)} rerun={len(todo)} out={out_dir}",
        flush=True,
    )
    (out_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def pack_from(src: dict, qid: str, cards: list | None, mstats: dict | None, got: dict | None) -> dict:
        row = dict(src)
        row["system"] = "forward_backward_coverage_combine"
        row["pipeline"] = "forward_plus_b_plus_c_combine"
        row["c_merge"] = "combine"
        if mstats is not None:
            row["n_from_c"] = mstats.get("n_added") or 0
            row["n_c_merged_into"] = mstats.get("n_merged_into") or 0
            row["n_c_new_readings"] = mstats.get("n_new_readings") or 0
            row["merged_c"] = bool((mstats.get("n_added") or 0) or (mstats.get("n_merged_into") or 0))
        if got is not None:
            row.update(got)
        if cards is not None and got is None:
            row["ask_cards"] = cards
            row["n_asked"] = len(cards)
        return row

    t0 = time.time()
    rows_out: dict[str, dict] = {}
    for qid in copy_old:
        rows_out[qid] = pack_from(reuse[qid], qid, None, {"n_added": 0, "n_merged_into": 0, "n_new_readings": 0}, None)
        rows_out[qid]["merged_c"] = False
        rows_out[qid]["replay"] = "reuse_old"
    for rec in copy_fb:
        qid = rec["id"]
        rows_out[qid] = pack_from(base[qid], qid, rec["cards"], rec["mstats"], None)
        rows_out[qid]["pipeline"] = "forward_backward_reuse_after_combine_subset"
        rows_out[qid]["replay"] = "copy_fb"
        rows_out[qid]["coverage_checked"] = True
    with pred_path.open("w", encoding="utf-8") as handle:
        for qid in sorted(rows_out):
            handle.write(json.dumps(rows_out[qid], ensure_ascii=False) + "\n")

    for i, rec in enumerate(todo, 1):
        qid = rec["id"]
        gold = golds[qid]
        got = _run_merged(gold, rec["cards"], rec["phi"], llm0, format_parser_base)
        row = pack_from(base[qid], qid, rec["cards"], rec["mstats"], got)
        row["coverage_checked"] = True
        row["replay"] = "rerun"
        row["baseline_n_asked"] = (reuse.get(qid) or {}).get("n_asked")
        rows_out[qid] = row
        with pred_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            f"  [{i}/{len(todo)}] {qid} cards={row.get('n_asked')} "
            f"merged_into={rec['mstats']['n_merged_into']} added={rec['mstats']['n_added']} "
            f"new_readings={rec['mstats']['n_new_readings']} {(time.time()-t0)/60:.1f}m",
            flush=True,
        )

    ordered = [rows_out[k] for k in sorted(rows_out)]
    if len(ordered) != len(reuse):
        missing = sorted(set(reuse) - set(rows_out))
        raise SystemExit(f"incomplete replay, missing {len(missing)} e.g. {missing[:5]}")
    pred_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered), encoding="utf-8")

    q_mean = sum(float(r.get("n_asked") or 0) for r in ordered) / max(1, len(ordered))
    metrics = _score(pred_path, score_path)
    old_sum = {}
    old_summary = reuse_pred.parent / "summary.json"
    if old_summary.is_file():
        old_sum = json.loads(old_summary.read_text(encoding="utf-8"))
    summary = {
        "arm": "forward_backward_coverage_combine",
        "c_merge": "combine",
        "reuse_pred": str(reuse_pred),
        "cover_raw": str(cover_raw),
        "n": len(ordered),
        "n_rerun": len(todo),
        "n_copy_fb": len(copy_fb),
        "n_reuse_old": len(copy_old),
        "n_c_merged_into": sum(int(r.get("n_c_merged_into") or 0) for r in ordered),
        "n_c_added": sum(int(r.get("n_from_c") or 0) for r in ordered),
        "n_c_new_readings": sum(int(r.get("n_c_new_readings") or 0) for r in ordered),
        "Q_mean": q_mean,
        "Q_sum": sum(float(r.get("n_asked") or 0) for r in ordered),
        "ex": metrics.get("ex"),
        "n_hit": metrics.get("n_hit"),
        "baseline_coverage_add": {
            "ex": old_sum.get("ex"),
            "n_hit": old_sum.get("n_hit"),
            "Q_mean": old_sum.get("Q_mean"),
            "n": old_sum.get("n"),
        },
        "elapsed_min": (time.time() - t0) / 60.0,
        "out": str(out_dir),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["smoke", "all", "score-only", "replay-combine"])
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE, help="forward_backward pred.jsonl")
    ap.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    ap.add_argument("--out", type=Path, default=OUT_ROOT)
    ap.add_argument("--limit", type=int, default=None, help="最多处理多少道 differ 题")
    ap.add_argument("--ids", default="")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--c-merge",
        choices=["add", "combine"],
        default="combine",
        help="combine: 同类型读法合并进原卡（默认）；add: 旧行为，C 卡单独再问",
    )
    ap.add_argument("--reuse-pred", type=Path, default=None, help="replay-combine: 旧的 coverage pred.jsonl")
    ap.add_argument("--cover-raw", type=Path, default=None, help="replay-combine: 已有 cover_raw.jsonl")
    args = ap.parse_args()
    if args.cmd == "replay-combine":
        cmd_replay_combine(args)
        return

    if not args.base.is_file():
        raise SystemExit(f"missing base pred: {args.base}")
    if not args.groups.is_file():
        raise SystemExit(f"missing groups: {args.groups}")
    if not COVER_PROMPT.is_file():
        raise SystemExit(f"missing cover prompt: {COVER_PROMPT}")

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "pred.jsonl"
    score_path = out_dir / "score_paper.json"
    summary_path = out_dir / "summary.json"
    cover_log = out_dir / "cover_raw.jsonl"

    if args.cmd == "score-only":
        metrics = _score(pred_path, score_path)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return

    base = _load_jsonl(args.base)
    gmap: dict[str, dict] = {}
    for line in args.groups.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        gmap[str(row.get("qid") or row.get("id"))] = row

    golds = _load_golds()
    want = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids else None
    cover_tpl = COVER_PROMPT.read_text(encoding="utf-8")

    differ_ids = [qid for qid in sorted(base) if (gmap.get(qid) or {}).get("differ")]
    todo_all = list(differ_ids)
    if want:
        todo_all = [q for q in todo_all if q in want]
    if args.limit is not None:
        todo_all = todo_all[: args.limit]

    done: set[str] = set()
    if args.resume and pred_path.is_file():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            qid = row["id"]
            # differ 题必须带 coverage_checked
            if qid in set(differ_ids) and not row.get("coverage_checked"):
                continue
            done.add(qid)
    elif pred_path.is_file() and not args.resume:
        pred_path.unlink()
        score_path.unlink(missing_ok=True)
        cover_log.unlink(missing_ok=True)

    lock = threading.Lock()

    def _write(row: dict) -> None:
        with lock:
            with pred_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            done.add(row["id"])

    # init：先写入非 differ 的 base 复用行
    if not args.resume or not pred_path.exists():
        n_copy = 0
        with pred_path.open("w", encoding="utf-8") as f:
            for qid, row in sorted(base.items()):
                if qid in set(differ_ids):
                    continue
                out = dict(row)
                out["pipeline"] = "forward_backward_reuse"
                out["coverage_checked"] = False
                out["n_from_c"] = 0
                out["merged_c"] = False
                f.write(json.dumps(out, ensure_ascii=False) + "\n")
                done.add(qid)
                n_copy += 1
        print(
            f"[init] reused non-differ {n_copy}; differ {len(differ_ids)}; "
            f"this run cover-check {len(todo_all)}",
            flush=True,
        )
        cover_log.write_text("", encoding="utf-8")
    else:
        keep = []
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row["id"] in set(differ_ids) and not row.get("coverage_checked"):
                continue
            keep.append(row)
        pred_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep),
            encoding="utf-8",
        )
        done = {r["id"] for r in keep}
        print(
            f"[resume] kept {len(done)}; differ {len(differ_ids)}; "
            f"left {sum(1 for q in todo_all if q not in done)}",
            flush=True,
        )

    todo = [q for q in todo_all if q not in done]
    print(
        f"[cover] differ={len(todo_all)} todo={len(todo)} port={args.port} workers={args.workers}",
        flush=True,
    )

    from utils.llm import LLM

    format_parser_base = format_parser("fbc")
    llm0 = LLM(url=f"http://127.0.0.1:{args.port}/v1")
    t0 = time.time()
    stats = {"n_new_c": 0, "n_merged_c": 0, "n_reuse_fb": 0}

    def work(qid: str) -> dict:
        br = base[qid]
        gold = golds[qid]
        base_cards = _cards_of(br)
        draft = _groups_of(gmap.get(qid))
        differing = [g["group_id"] for g in draft if not g["same_as_no_clarification"]]
        q = gold.question or ""
        ev = str((gold.meta or {}).get("evidence") or "").strip() or "NULL"
        prompt = (
            cover_tpl
            + "\n# Inputs\nQuestion: "
            + q
            + "\nEvidence:\n"
            + ev
            + "\nQuestions:\n"
            + json.dumps(_card_views(base_cards), ensure_ascii=False, indent=2)
            + "\nDraft groups:\n"
            + json.dumps(draft, ensure_ascii=False, indent=2)
        )
        raw = llm0.complete(prompt)
        obj = _parse_cover_json(raw)
        covered = obj.get("covered") if isinstance(obj.get("covered"), list) else []
        new_raw = obj.get("new_questions") if isinstance(obj.get("new_questions"), list) else []
        uncovered = []
        for group_id in differing:
            hit = next((c for c in covered if c.get("group_id") == group_id), None)
            if not (hit and hit.get("question_id") is not None and hit.get("option_index") is not None):
                uncovered.append(group_id)
        c_cards = _specs_to_cards(new_raw if uncovered else [])
        with lock:
            with cover_log.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "id": qid,
                            "n_differ": len(differing),
                            "n_uncovered": len(uncovered),
                            "n_new_specs": len(new_raw or []),
                            "n_c_cards": len(c_cards),
                            "raw": raw,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        if not c_cards:
            out = dict(br)
            out["pipeline"] = "forward_backward_reuse"
            out["coverage_checked"] = True
            out["n_from_c"] = 0
            out["merged_c"] = False
            out["n_uncovered_groups"] = len(uncovered)
            return out

        cards, mstats = _merge_cards(base_cards, c_cards, policy=getattr(args, 'c_merge', 'combine'))
        n_c = mstats['n_added']
        phi = br.get("phi") or (br.get("meta") or {}).get("phi") or {}
        got = _run_merged(gold, cards, phi, llm0, format_parser_base)
        return {
            "id": qid,
            "db_id": getattr(gold, "db_id", None) or br.get("db_id"),
            "system": "forward_backward_coverage",
            "pipeline": "forward_plus_b_plus_c",
            "parser": "qwen_coder",
            "merged": True,
            "merged_c": True,
            "coverage_checked": True,
            "n_from_c": n_c,
            "n_from_b": br.get("n_from_b"),
            "n_base_cards": len(base_cards),
            "n_uncovered_groups": len(uncovered),
            "baseline_n_asked": br.get("n_asked"),
            **got,
            "meta": {
                "base_source": str(args.base),
                "groups_source": str(args.groups),
                "n_from_c": n_c,
            },
        }

    if todo:
        workers = max(1, min(args.workers, 1 if args.port else args.workers))
        if workers == 1:
            for i, qid in enumerate(todo, 1):
                row = work(qid)
                _write(row)
                if row.get("merged_c"):
                    stats["n_merged_c"] += 1
                    stats["n_new_c"] += int(row.get("n_from_c") or 0)
                else:
                    stats["n_reuse_fb"] += 1
                print(
                    f"  [{i}/{len(todo)}] {qid} "
                    f"{'C+' + str(row.get('n_from_c')) if row.get('merged_c') else 'reuse_fb'} "
                    f"cards={row.get('n_asked')} "
                    f"{(time.time() - t0) / 60:.1f}m",
                    flush=True,
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = {pool.submit(work, q): q for q in todo}
                for i, fut in enumerate(as_completed(futs), 1):
                    row = fut.result()
                    _write(row)
                    print(f"  [{i}/{len(todo)}] {row['id']} cards={row.get('n_asked')}", flush=True)

    rows = [json.loads(l) for l in pred_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_id = {r["id"]: r for r in rows}
    rows = [by_id[k] for k in sorted(by_id)]
    pred_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    q_mean = sum(float(r.get("n_asked") or 0) for r in rows) / max(1, len(rows))
    q_sum = sum(float(r.get("n_asked") or 0) for r in rows)
    n_merged_c = sum(1 for r in rows if r.get("merged_c"))
    print(
        f"[Q] n={len(rows)} sum={q_sum:.0f} mean={q_mean:.4f} "
        f"merged_c={n_merged_c} cover_new_cards={stats['n_new_c']}",
        flush=True,
    )

    metrics = _score(pred_path, score_path)
    fb_summary = args.base.parent / "summary.json"
    baseline = {}
    if fb_summary.is_file():
        blob = json.loads(fb_summary.read_text(encoding="utf-8"))
        baseline = {
            "ex": blob.get("ex"),
            "n_hit": blob.get("n_hit"),
            "n": blob.get("n"),
            "Q_mean": blob.get("Q_mean"),
            "arm": blob.get("arm"),
        }
    none_score = ASK / "outputs" / "bird_arcwise" / "check_ab1_r2" / "check_none" / "score_paper.json"
    none_base = {}
    if none_score.is_file():
        sm = json.loads(none_score.read_text(encoding="utf-8")).get("summary") or {}
        ex = sm.get("ex") if isinstance(sm.get("ex"), dict) else {}
        none_base = {"ex": ex.get("ex"), "n_hit": ex.get("n_hit"), "n": ex.get("n")}

    summary = {
        "arm": "forward_backward_coverage",
        "base": str(args.base),
        "groups": str(args.groups),
        "n": len(rows),
        "n_differ": len(differ_ids),
        "n_merged_with_c": n_merged_c,
        "n_new_c_cards": stats["n_new_c"],
        "Q_sum": q_sum,
        "Q_mean": q_mean,
        "ex": metrics.get("ex"),
        "n_hit": metrics.get("n_hit"),
        "baseline_forward_backward": baseline,
        "baseline_check_none": none_base,
        "delta_ex_vs_fb": (
            (metrics.get("ex") - baseline["ex"])
            if metrics.get("ex") is not None and baseline.get("ex") is not None
            else None
        ),
        "delta_ex_vs_none": (
            (metrics.get("ex") - none_base["ex"])
            if metrics.get("ex") is not None and none_base.get("ex") is not None
            else None
        ),
        "elapsed_min": (time.time() - t0) / 60.0,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
