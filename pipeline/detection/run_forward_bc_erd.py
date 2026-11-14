#!/usr/bin/env python3
"""Forward ∪ B ∪ C，再串行挂 Existence → Difference → Relevance，一次作答打 EX。

Forward / Backward / Coverage 的卡全部保留，不按 span 去重合并；撞 span 时给后来源加后缀（[b] / [cover]）。同一来源内的完全重复仍会折叠。
组装之后再做精确去重：同一题、同一 base span（去掉末尾的 [b]/[cover]/[cover2]/类型标签，仅匹配键 casefold）、同一 ambig_type、候选项集合完全相同的卡，只保留 Forward；没有 Forward 时优先留 Backward，再留 Coverage。候选项按 canonical JSON 做集合相等，顺序无关。不同类型或候选集不完全相同的卡一律保留。

C 卡默认从 detection/coverage/cover_raw.jsonl 解析 new_questions（不再调 cover）。
三 check 顺序固定为 exist → diff → rel。

用法：
  python pipeline/detection/run_forward_bc_erd.py all
  python pipeline/detection/run_forward_bc_erd.py all --qc --port 8000
  python pipeline/detection/run_forward_bc_erd.py smoke --limit 2"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ASK = HERE.parents[1]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))

from pipeline.detection.run_common import card_key as _card_key, load_jsonl as _load_jsonl_by_id, score as _score, specs_to_cards

DEFAULT_FWD = ASK / "outputs" / "bird_arcwise" / "detection" / "forward" / "pred.jsonl"
DEFAULT_B = ASK / "outputs" / "bird_arcwise" / "detection" / "backward" / "b" / "pred.jsonl"
DEFAULT_COVER_RAW = (
    ASK / "outputs" / "bird_arcwise" / "detection" / "coverage" / "cover_raw.jsonl"
)
OUT_ROOT = ASK / "outputs" / "bird_arcwise" / "detection"
PROMPTS = HERE.parent / "checks" / "prompts"


def _valid(card: dict) -> bool:
    if not _card_key(card):
        return False
    if not isinstance(card.get("cands"), list) or len(card["cands"]) < 2:
        return False
    if not isinstance(card.get("choices"), list) or len(card["choices"]) < 2:
        return False
    return True


def _normalize_card(card: dict, source: str) -> dict | None:
    c = dict(card)
    span = str(c.get("span") or c.get("_phi_key") or "").strip()
    if not span:
        return None
    cands = c.get("cands")
    if not isinstance(cands, list) or len(cands) < 2:
        return None
    choices = c.get("choices")
    if not isinstance(choices, list) or len(choices) < 2:
        choices = [{"desc": str(x), "elements": [str(x)]} for x in cands]
    out = {
        "span": span,
        "_phi_key": str(c.get("_phi_key") or span),
        "ambig_type": str(c.get("ambig_type") or c.get("type") or ""),
        "cands": list(cands),
        "choices": list(choices),
        "interpretation": str(c.get("interpretation") or ""),
        "source": source,
        "batch": int(c.get("batch") or 0),
    }
    return out if _valid(out) else None


def _cards_from_row(row: dict | None, source: str) -> list[dict]:
    if not row:
        return []
    raw = row.get("ask_cards") or (row.get("meta") or {}).get("ask_cards") or []
    out = []
    for c in raw:
        if isinstance(c, dict):
            n = _normalize_card(c, source)
            if n:
                out.append(n)
    return out


def _specs_to_cards(specs: list) -> list[dict]:
    out = []
    for card in specs_to_cards(specs):
        n = _normalize_card(card, "coverage_c")
        if n:
            out.append(n)
    return out


def _parse_cover_new_questions(raw: str) -> list[dict]:
    if not raw or "{" not in raw:
        return []
    try:
        obj = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except Exception:
        return []
    specs = obj.get("new_questions") if isinstance(obj.get("new_questions"), list) else []
    return _specs_to_cards(specs)


def _unique_key(base: str, seen: set[str], tag: str) -> str:
    cand = f"{base}\n[{tag}]"
    if _card_key({"span": cand}) not in seen:
        return cand
    n = 2
    while True:
        cand = f"{base}\n[{tag}{n}]"
        if _card_key({"span": cand}) not in seen:
            return cand
        n += 1


TYPE_TAGS = {"Project", "Aggregate", "Column", "Value", "Tie", "Join", "NULL", "Scope", "Attachment"}
# trailing merge suffixes and type tags only; used for the match key, never rewritten onto a kept card
_TAG_RE = re.compile(
    r"\n\[(?:"
    r"b\d*|cover\d*|fwd\d*|"
    + "|".join(re.escape(t) for t in sorted(TYPE_TAGS, key=len, reverse=True))
    + r")\]\s*$",
    re.IGNORECASE,
)

PROTECTED_OUT_NAMES = {
    "erd_qc",
    "erd_qc_att_scope",
    "erd_qc_att_scope_valueclose",
    "erd",
    "erd_bc",
    "erd_coverage",
    "forward",
    "backward",
    "coverage",
    "forward_backward",
    "presql",
}


def _is_protected_out(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path
    name = resolved.name
    if name in PROTECTED_OUT_NAMES:
        return True
    # official coverage/qc dirs if they reappear under detection/
    if resolved.parent.name == "detection" and name.startswith("erd_qc"):
        # allow new siblings such as erd_qc_att_scope_valueclose_exactdedup
        return name in {
            "erd_qc",
            "erd_qc_att_scope",
            "erd_qc_att_scope_valueclose",
        } or name in PROTECTED_OUT_NAMES
    return False


def base_span_for_match(span: str) -> str:
    """Strip trailing [b]/[cover]/[cover2]/[fwd]/type tags for the match key only."""
    s = str(span or "")
    while True:
        m = _TAG_RE.search(s)
        if not m:
            return s.strip()
        s = s[: m.start()]


def canon_cand(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


def cand_set(cands) -> frozenset:
    return frozenset(canon_cand(x) for x in (cands or []))


def exact_dup_key(card: dict) -> tuple:
    span = str(card.get("span") or card.get("_phi_key") or "")
    typ = str(card.get("ambig_type") or card.get("type") or "")
    return (base_span_for_match(span).casefold(), typ, cand_set(card.get("cands")))


def _extend_choices(card: dict, new_cands: list) -> None:
    choices = card.get("choices")
    if not isinstance(choices, list):
        return
    have = {canon_cand(ch.get("elements") if isinstance(ch, dict) else ch) for ch in choices}
    for cand in new_cands:
        key = canon_cand([cand] if not isinstance(cand, list) else cand)
        alt = canon_cand(cand)
        if key in have or alt in have:
            continue
        choices.append({"desc": str(cand), "elements": [cand] if not isinstance(cand, list) else cand})
        have.add(key)


def apply_add_readings(fwd: list[dict], b: list[dict]) -> tuple[list[dict], list[dict], int]:
    """Union Backward add_reading candidates into the matching Forward card.

    Only fires when a Backward card has b_action/action == add_reading.
    Existing official B preds do not have this field, so they are unchanged.
    The Forward card's span is not rewritten. The Backward add_reading card is
    not kept as a separate card if the target Forward card is found.
    """
    index: dict[tuple, dict] = {}
    for card in fwd:
        k = (base_span_for_match(str(card.get("span") or card.get("_phi_key") or "")).casefold(),
             str(card.get("ambig_type") or card.get("type") or ""))
        index.setdefault(k, card)
    kept_b: list[dict] = []
    n_applied = 0
    for card in b:
        action = str(card.get("b_action") or card.get("action") or "").strip()
        if action != "add_reading":
            kept_b.append(card)
            continue
        target = str(card.get("add_to_span") or card.get("target_span") or card.get("span") or card.get("_phi_key") or "")
        typ = str(card.get("ambig_type") or card.get("type") or "")
        dest = index.get((base_span_for_match(target).casefold(), typ))
        if dest is None:
            kept_b.append(card)
            continue
        incoming = card.get("new_cands") or card.get("cands") or []
        if not isinstance(incoming, list):
            incoming = []
        existing = list(dest.get("cands") or [])
        have = cand_set(existing)
        added = []
        for cand in incoming:
            ck = canon_cand(cand)
            if ck not in have:
                existing.append(cand)
                have.add(ck)
                added.append(cand)
        if added:
            dest["cands"] = existing
            _extend_choices(dest, added)
            n_applied += 1
        # drop the Backward add_reading card even if all cands were already present
    return fwd, kept_b, n_applied


def exact_dedup_cards(cards: list[dict]) -> tuple[list[dict], dict]:
    """Drop exact Backward/Coverage copies of a kept card, preferring Forward.

    A duplicate is the same base span, same ambig_type, and identical candidate
    set. Different types are never merged. Same-type pairs with different cand
    sets are kept. Type tags are not stripped to collapse types.
    """
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, card in enumerate(cards):
        groups[exact_dup_key(card)].append(i)
    drop: set[int] = set()
    stats = {
        "n_exact_dup_groups": 0,
        "n_exact_dup_dropped": 0,
        "n_exact_dup_dropped_b": 0,
        "n_exact_dup_dropped_c": 0,
    }
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        sources = [str(cards[i].get("source") or "") for i in idxs]
        forwards = [i for i, s in zip(idxs, sources) if s == "forward"]
        if forwards:
            keep = set(forwards)
        else:
            backs = [i for i, s in zip(idxs, sources) if s == "backward_b"]
            covers = [i for i, s in zip(idxs, sources) if s == "coverage_c"]
            if backs:
                keep = {backs[0]}
            elif covers:
                keep = {covers[0]}
            else:
                keep = {idxs[0]}
        dropped = [i for i in idxs if i not in keep]
        if not dropped:
            continue
        stats["n_exact_dup_groups"] += 1
        for i in dropped:
            drop.add(i)
            stats["n_exact_dup_dropped"] += 1
            src = str(cards[i].get("source") or "")
            if src == "backward_b":
                stats["n_exact_dup_dropped_b"] += 1
            elif src == "coverage_c":
                stats["n_exact_dup_dropped_c"] += 1
    kept = [card for i, card in enumerate(cards) if i not in drop]
    return kept, stats


def merge_cards(fwd: list[dict], b: list[dict], c: list[dict]) -> tuple[list[dict], dict]:
    """Keep all F/B/C cards. Colliding spans get a suffix; exact dups within forward are folded.

    After assembly, drop Backward/Coverage copies that are exact duplicates of a
    kept card (same base span, same type, identical cand set), preferring Forward.
    """
    fwd = [dict(x) for x in fwd]
    b = [dict(x) for x in b]
    c = [dict(x) for x in c]
    fwd, b, n_add_reading = apply_add_readings(fwd, b)
    stats = {"n_fwd": len(fwd), "n_b": len(b), "n_c": len(c), "n_kept_b": 0, "n_kept_c": 0, "n_add_reading_applied": n_add_reading}
    merged: list[dict] = []
    seen: set[str] = set()
    for card in fwd:
        k = _card_key(card)
        if not k or k in seen:
            # even no-dedup across sources: still collapse exact dup within forward
            if not k:
                continue
            item = dict(card)
            new_span = _unique_key(item["span"], seen, "fwd")
            item["span"] = new_span
            item["_phi_key"] = new_span
            item["source"] = "forward"
            k = _card_key(item)
        else:
            item = dict(card)
            item["source"] = "forward"
        seen.add(k)
        merged.append(item)
    for card, tag, counter_key in (
        *((x, "backward_b", "n_kept_b") for x in b),
        *((x, "coverage_c", "n_kept_c") for x in c),
    ):
        item = dict(card)
        k = _card_key(item)
        if not k:
            continue
        if k in seen:
            item["cover_of"] = item.get("span")
            suffix = "b" if tag == "backward_b" else "cover"
            new_span = _unique_key(str(item.get("cover_of") or item["span"]), seen, suffix)
            item["span"] = new_span
            item["_phi_key"] = new_span
            k = _card_key(item)
        item["source"] = tag
        seen.add(k)
        merged.append(item)
        stats[counter_key] += 1
    merged, dup_stats = exact_dedup_cards(merged)
    stats.update(dup_stats)
    stats["n_kept_b"] = sum(1 for x in merged if x.get("source") == "backward_b")
    stats["n_kept_c"] = sum(1 for x in merged if x.get("source") == "coverage_c")
    return merged, stats


def cards_to_phi(cards: list[dict]) -> tuple[dict[str, list], dict[str, str], dict[str, str]]:
    phi: dict[str, list] = {}
    types: dict[str, str] = {}
    interps: dict[str, str] = {}
    for c in cards:
        key = str(c.get("_phi_key") or c.get("span") or "")
        if not key:
            continue
        phi[key] = list(c["cands"])
        if c.get("ambig_type"):
            types[key] = str(c["ambig_type"])
        if c.get("interpretation"):
            interps[key] = str(c["interpretation"])
    return phi, types, interps


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["smoke", "all", "score-only"])
    ap.add_argument("--forward", type=Path, default=DEFAULT_FWD)
    ap.add_argument("--backward-b", type=Path, default=DEFAULT_B)
    ap.add_argument("--cover-raw", type=Path, default=DEFAULT_COVER_RAW)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--ids", default="")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--fidelity", choices=["on", "off"], default="on")
    ap.add_argument(
        "--qc",
        action="store_true",
        help="exist→diff→rel 之后对剩余卡跑 06c_ours_qc_1bc，再 08 作答",
    )
    ap.add_argument(
        "--diff-types",
        default="Attachment,Scope",
        help="comma-separated Difference types, e.g. Attachment or Attachment,Scope",
    )
    ap.add_argument(
        "--dedup",
        choices=["none"],
        default="none",
        help="none = no span-merge (colliding spans get a suffix). "
        "Exact same-type same-cand duplicates are still dropped, preferring Forward.",
    )
    args = ap.parse_args()

    qc_tag = "_qc" if args.qc else ""
    erd_name = "erd" + qc_tag
    out_dir = args.out or (OUT_ROOT / erd_name)
    if args.cmd != "score-only" and _is_protected_out(out_dir):
        raise SystemExit(
            f"refusing to write into official result dir {out_dir}. "
            "Pick a new sibling directory."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "pred.jsonl"
    score_path = out_dir / "score_paper.json"
    summary_path = out_dir / "summary.json"

    if args.cmd == "score-only":
        print(json.dumps(_score(pred_path, score_path), ensure_ascii=False, indent=2))
        return

    if not args.forward.is_file():
        raise SystemExit(f"missing forward {args.forward}")
    if not args.backward_b.is_file():
        raise SystemExit(f"missing B {args.backward_b}")

    from pipeline.checks.runtime import ask_and_reparse, format_parser, load_golds
    from pipeline.checks import apply_existence, apply_relevance, apply_difference
    from utils.llm import LLM

    fwd = _load_jsonl_by_id(args.forward)
    bmap = _load_jsonl_by_id(args.backward_b)
    cover_by_id = _load_jsonl_by_id(args.cover_raw) if args.cover_raw.is_file() else {}
    golds = {g.id: g for g in load_golds("bird_arcwise")}

    want = {x.strip() for x in args.ids.split(",") if x.strip()} if args.ids else None
    qids = sorted(fwd)
    if want:
        qids = [q for q in qids if q in want]
    if args.limit is not None:
        # prefer ids that have B or C for smoke
        rich = [q for q in qids if q in bmap or q in cover_by_id]
        rest = [q for q in qids if q not in set(rich)]
        qids = (rich + rest)[: args.limit]

    done: set[str] = set()
    if args.resume and pred_path.is_file():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    elif pred_path.is_file() and not args.resume:
        pred_path.unlink()
        score_path.unlink(missing_ok=True)

    todo = [q for q in qids if q not in done]
    diff_types = {t.strip() for t in str(args.diff_types).split(",") if t.strip()}
    if not diff_types:
        raise SystemExit("empty --diff-types")

    print(
        f"[init] qc={int(bool(args.qc))} fidelity={args.fidelity} "
        f"diff_types={','.join(sorted(diff_types))} dedup={args.dedup}+exact "
        f"n_fwd={len(fwd)} n_b={len(bmap)} "
        f"n_cover_raw={len(cover_by_id)} todo={len(todo)} out={out_dir}",
        flush=True,
    )

    probe_tpl = (PROMPTS / "difference_probe.md").read_text(encoding="utf-8")
    check_tpl = (PROMPTS / "difference_check.md").read_text(encoding="utf-8")
    llm = LLM(url=f"http://127.0.0.1:{args.port}/v1")
    fmt = format_parser("erd_none")
    use_fidelity = args.fidelity == "on"
    lock = threading.Lock()
    t0 = time.time()

    def work(qid: str) -> dict:
        gold = golds[qid]
        fr = fwd[qid]
        br = bmap.get(qid)
        cr = cover_by_id.get(qid)
        fwd_cards = _cards_from_row(fr, "forward")
        b_cards = _cards_from_row(br, "backward_b")
        # cover_raw 里 n_c_cards>0 才表示当时因未覆盖而采纳了 new_questions
        if cr and int(cr.get("n_c_cards") or 0) > 0 and int(cr.get("n_uncovered") or 0) > 0:
            c_cards = _parse_cover_new_questions(cr.get("raw") or "")
        else:
            c_cards = []
        cards, mstats = merge_cards(fwd_cards, b_cards, c_cards)
        phi, types, interps = cards_to_phi(cards)
        healed: dict[str, Any] = {}

        phi, n_pe, n_he, tr_e = apply_existence(gold, phi, types, healed)
        phi, tr_d, n_dd = apply_difference(
            gold, phi, types, llm,
            probe_tpl=probe_tpl,
            check_tpl=check_tpl,
            use_fidelity=use_fidelity,
            target_types=diff_types,
            healed=healed,
        )
        n_rd = sum(1 for t in tr_d if t.get("action") == "resolve")
        phi, tr_r, n_dr, _base_exec = apply_relevance(gold, phi, types, llm, fmt)
        parsed = ask_and_reparse(
            gold, llm, fmt, phi, types, interps, healed=healed, use_qc=bool(args.qc),
        )
        arm = "fwd_b_erd_dedup_none" + ("_qc" if args.qc else "")
        return {
            "id": qid,
            "db_id": getattr(gold, "db_id", None) or fr.get("db_id"),
            "system": arm,
            "pipeline": f"exist_diff_rel{'_qc' if args.qc else ''}_none",
            "parser": "qwen_coder",
            "dedup": "none",
            "n_cards_merged": len(cards),
            "n_from_b": mstats["n_kept_b"],
            "n_from_c": mstats["n_kept_c"],
            "n_asked": parsed["n_asked"],
            "n_qc": parsed.get("n_qc") or 0,
            "no_qc": parsed.get("no_qc", True),
            "n_probes": int(n_pe) + len(tr_r) + len(tr_d),
            "n_healed": int(n_he),
            "n_dropped_rel": int(n_dr),
            "n_dropped_diff": int(n_dd),
            "n_resolved_diff": int(n_rd),
            "question_out": parsed["question_out"],
            "schema_out": parsed["schema_out"],
            "evidence_out": parsed["evidence_out"],
            "predicted_sql": parsed["predicted_sql"],
            "ask_cards": cards,
            "ask_cards_final": parsed.get("ask_cards_final") or [],
            "phi": phi,
            "span_types": types,
            "span_interps": interps,
            "meta": {
                "dedup": "none",
                "merge_stats": mstats,
                "existence_trace_n": len(tr_e),
                "difference_trace_n": len(tr_d),
                "relevance_trace_n": len(tr_r),
                "healed": healed,
                "checks": ["existence", "difference", "relevance"],
                "qc": bool(args.qc),
                "qc_prompt": "pipeline/detection/prompts/06c_ours_qc_1bc.md" if args.qc else None,
                "fidelity": use_fidelity,
                "diff_types": sorted(diff_types),
                "exact_dedup": True,
            },
        }

    with pred_path.open("a", encoding="utf-8") as f:
        for i, qid in enumerate(todo, 1):
            row = work(qid)
            with lock:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            print(
                f"  [{i}/{len(todo)}] {qid} cards={row['n_cards_merged']} "
                f"ask={row['n_asked']} qc={row.get('n_qc', 0)} "
                f"drop_rel={row['n_dropped_rel']} "
                f"drop_diff={row['n_dropped_diff']} "
                f"resolve_diff={row.get('n_resolved_diff') or 0} "
                f"+b{row['n_from_b']}+c{row['n_from_c']} "
                f"{(time.time()-t0)/60:.1f}m",
                flush=True,
            )

    rows = [json.loads(l) for l in pred_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    by_id = {r["id"]: r for r in rows}
    # ensure full set: if smoke/limit, only scored subset; for all, fill any missing from forward reuse? 
    if args.cmd == "all" and not want and args.limit is None:
        missing = [q for q in sorted(fwd) if q not in by_id]
        if missing:
            raise SystemExit(f"incomplete pred, missing {len(missing)} e.g. {missing[:3]}")
    rows = [by_id[k] for k in sorted(by_id)]
    pred_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    q_mean = sum(float(r.get("n_asked") or 0) for r in rows) / max(1, len(rows))
    metrics = _score(pred_path, score_path)
    none_score = DEFAULT_FWD.parent / "score_paper.json"
    baseline = {}
    if none_score.is_file():
        sm = json.loads(none_score.read_text()).get("summary") or {}
        ex = sm.get("ex") if isinstance(sm.get("ex"), dict) else {}
        baseline = {"ex": ex.get("ex"), "n_hit": ex.get("n_hit"), "n": ex.get("n")}
    summary = {
        "arm": "fwd_b_erd_dedup_none" + ("_qc" if args.qc else ""),
        "dedup": "none",
        "qc": bool(args.qc),
        "checks": ["existence", "difference", "relevance"],
        "fidelity": use_fidelity,
        "diff_types": sorted(diff_types),
        "exact_dedup": True,
        "n": len(rows),
        "Q_mean": q_mean,
        "Q_sum": sum(float(r.get("n_asked") or 0) for r in rows),
        "mean_cards_merged": sum(float(r.get("n_cards_merged") or 0) for r in rows) / max(1, len(rows)),
        "ex": metrics.get("ex"),
        "n_hit": metrics.get("n_hit"),
        "baseline_check_none": baseline,
        "delta_ex_vs_none": (
            (metrics.get("ex") - baseline["ex"])
            if metrics.get("ex") is not None and baseline.get("ex") is not None
            else None
        ),
        "elapsed_min": (time.time() - t0) / 60.0,
        "out": str(out_dir),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
