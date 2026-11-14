# SOURCE: see pipeline/SOURCE.md
#!/usr/bin/env python3
"""abc-333 检测：B（backward 只收集问题）、C（draft 覆盖补问）、from_abc。

B：本仓库 detection/prompts 的 S1+S2+S3 + draft groups，只检出并收集澄清问题，
不出最终 SQL。Backward 能看到已有的 Forward 问题列表，只允许 add_question、
add_reading 或 skip，不能删除或改写 Forward 卡。

草稿：pipeline/presql_group/sql_pool.py（--dataset + --out）。
打分：python -m evaluator.ex（需另跑解析）。

环境变量：ABC_DATASET ABC_PARSER ABC_OUT ABC_PORTS；from_abc 还需 ABC_BASE_PRED。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASK = HERE.parents[1]
PROMPTS = HERE / "prompts"
COVER_PROMPT = PROMPTS / "06p_cover.md"
RECONCILE_PROMPT = PROMPTS / "06b_backward_reconcile.md"

# sanity-backward must not require a live ABC_OUT / vLLM
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "sanity-backward":
    os.environ.setdefault("ABC_DATASET", "bird_arcwise")
    os.environ.setdefault("ABC_PARSER", "base")
    os.environ.setdefault("ABC_OUT", "/tmp/backward_sanity_dummy")
    os.environ.setdefault("ABC_PORTS", "8000")

sys.path[:0] = [str(HERE.parent / "presql_group"), str(ASK)]

from sql_pool import (  # noqa: E402
    DS,
    OUT,
    PARSER,
    PORTS,
    golds,
    parser_prompt,
    parser_schema,
)
from pipeline.detection import three_stage as det  # noqa: E402
from pipeline.detection.run_common import n_asked as _n_asked  # noqa: E402
from utils.llm import LLM, parse_sql  # noqa: E402
from pipeline.runtime import RunContext, pred_row  # noqa: E402
from parsers.sql_parser_deepeye import format_parser_deepeye  # noqa: E402
from pipeline.gold_target import get_target_gold  # noqa: E402

STAGE_FILES = det.STAGE_FILES

os.environ["PAPER_EXP_LLM_MAX_TOKENS"] = "4096"
os.environ["PAPER_EXP_KEEP_BOTH"] = "1"
os.environ.pop("PAPER_EXP_SCOPE_FALLBACK", None)

_LOCAL = threading.local()
_ORIG_FILL = det._stage_fill


def _patch_local_prompts() -> None:
    """检出走本仓 three_stage；prompt 用 detection/prompts。"""
    det.REVIEW = PROMPTS
    if hasattr(det, "STAGE_FILES"):
        det.STAGE_FILES = STAGE_FILES
    for name in STAGE_FILES:
        path = PROMPTS / name
        if not path.is_file():
            raise SystemExit(f"missing prompt {path}")
    print(f"[prompts] REVIEW={PROMPTS} stages={list(STAGE_FILES)}", flush=True)


def _complete(self, prompt, tries: int = 3, temperature: float = 0):
    with self._trace_lock:
        self.traces.append(prompt)
    seed = 20261028 if "selected_labels" in (prompt or "") else 20261021
    kwargs = dict(
        model=self.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=4096,
        seed=seed,
        extra_body={"enable_thinking": False},
    )
    from utils.llm import _room_for_completion

    last = None
    for i in range(tries):
        try:
            resp = self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as exc:
            last = exc
            room = _room_for_completion(str(exc))
            if room is not None and room < int(kwargs.get("max_tokens") or 0):
                kwargs["max_tokens"] = room
                print(f"[llm] shrink max_tokens to {room}", flush=True)
                continue
            time.sleep(2 * (i + 1))
    print(f"[llm] give up: {last}", flush=True)
    return ""


def _stage_fill(ctx, stage_i: int, **slots: str) -> str:
    text = _ORIG_FILL(ctx, stage_i, **slots)
    block = getattr(_LOCAL, "block", "") or ""
    if block:
        text = text.rstrip() + "\n\n" + block
    return text


def draft_block(row: dict) -> str:
    lines = [
        "Draft execution groups.",
        "y-perp marks the group whose result matches the no-clarification SQL.",
    ]
    n = 0
    for g in row.get("groups") or []:
        fp = str(g.get("fp") or "")
        sql = str(g.get("sql") or "").strip()
        if not sql or fp.startswith("ERR"):
            continue
        n += 1
        mark = " [y-perp]" if g.get("is_y") else ""
        lines.append(f"Group {n}{mark}")
        lines.append("SQL:")
        lines.append(sql)
        lines.append("Preview: " + str(g.get("preview") or ""))
    return "\n".join(lines)


ALLOWED_BACKWARD_ACTIONS = ("add_question", "add_reading", "skip")
OFFICIAL_BACKWARD_PRED_SUFFIX = Path("detection") / "backward" / "b"


def _forward_pred_path() -> Path:
    env = (os.environ.get("ABC_FORWARD_PRED") or "").strip()
    if env:
        return Path(env)
    ds = os.environ.get("ABC_DATASET", "bird_arcwise")
    ds = {"bird": "bird_arcwise"}.get(ds, ds)
    return ASK / "outputs" / ds / "detection" / "forward" / "pred.jsonl"


def _is_official_backward_dest(dest: Path) -> bool:
    try:
        resolved = dest.resolve()
    except Exception:
        resolved = dest
    parts = resolved.parts
    # .../outputs/<dataset>/detection/backward/b
    return (
        len(parts) >= 4
        and parts[-1] == "b"
        and parts[-2] == "backward"
        and parts[-3] == "detection"
        and "outputs" in parts
    )


def forward_question_list(row: dict | None) -> list[dict]:
    """Serialize Forward cards as {span, type, candidates} for Backward to see."""
    if not row:
        return []
    raw = row.get("ask_cards") or (row.get("meta") or {}).get("ask_cards") or []
    out = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        span = str(c.get("span") or c.get("_phi_key") or "").strip()
        typ = str(c.get("ambig_type") or c.get("type") or "")
        cands = c.get("cands")
        if not span or not isinstance(cands, list) or len(cands) < 2:
            continue
        out.append({"span": span, "type": typ, "candidates": list(cands)})
    return out


def forward_list_block(fwd_list: list[dict]) -> str:
    return (
        "Existing Forward questions (already on the question list).\n"
        "Do not repeat a paraphrase or an identical question. "
        "You may only add a truly new question, or add a truly new reading to an existing question. "
        "If an idea is only a paraphrase with no new reading, skip it. "
        "Never delete or rewrite an existing Forward question.\n"
        "```json\n"
        + json.dumps(fwd_list, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _canon_cand(x) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, default=str)


def _cand_set(cands) -> frozenset:
    return frozenset(_canon_cand(x) for x in (cands or []))


def _base_span(span: str) -> str:
    import re
    s = str(span or "")
    tag_re = re.compile(
        r"\n\[(?:b\d*|cover\d*|fwd\d*|Project|Aggregate|Column|Value|Tie|Join|NULL|Scope|Attachment)\]\s*$",
        re.IGNORECASE,
    )
    while True:
        m = tag_re.search(s)
        if not m:
            return s.strip()
        s = s[: m.start()]


def _same_card(span: str, typ: str, cands, other: dict) -> bool:
    return (
        _base_span(span).casefold() == _base_span(str(other.get("span") or "")).casefold()
        and str(typ or "") == str(other.get("type") or other.get("ambig_type") or "")
        and _cand_set(cands) == _cand_set(other.get("candidates") or other.get("cands"))
    )


def proposals_from_cards(cards: list[dict]) -> list[dict]:
    out = []
    for i, c in enumerate(cards or []):
        if not isinstance(c, dict):
            continue
        out.append({
            "proposal_index": i,
            "span": str(c.get("span") or c.get("_phi_key") or ""),
            "type": str(c.get("ambig_type") or c.get("type") or ""),
            "candidates": list(c.get("cands") or []),
        })
    return out


def render_reconcile_prompt(fwd_list: list[dict], proposals: list[dict], prompt_text: str | None = None) -> str:
    text = prompt_text if prompt_text is not None else (
        RECONCILE_PROMPT.read_text(encoding="utf-8") if RECONCILE_PROMPT.is_file() else ""
    )
    return (
        text.replace("{forward_questions_json}", json.dumps(fwd_list, ensure_ascii=False, indent=2))
        .replace("{backward_proposals_json}", json.dumps(proposals, ensure_ascii=False, indent=2))
    )


def parse_backward_actions(raw: str) -> list[dict]:
    """Parse model output; drop anything that is not add_question / add_reading / skip."""
    if not raw or "{" not in raw:
        return []
    try:
        obj = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
    except Exception:
        return []
    items = obj.get("actions") if isinstance(obj, dict) and isinstance(obj.get("actions"), list) else []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        if action not in ALLOWED_BACKWARD_ACTIONS:
            # no delete, no rewrite, no unknown verbs
            continue
        rec = dict(item)
        rec["action"] = action
        out.append(rec)
    return out


def apply_backward_actions(
    fwd_list: list[dict],
    proposed_cards: list[dict],
    actions: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Apply add_question / add_reading / skip. Never mutates fwd_list (Forward stays unchanged)."""
    by_index: dict[int, dict] = {}
    for a in actions or []:
        if "proposal_index" not in a:
            continue
        try:
            idx = int(a["proposal_index"])
        except (TypeError, ValueError):
            continue
        by_index[idx] = a
    kept: list[dict] = []
    log: list[dict] = []
    for i, card in enumerate(proposed_cards or []):
        action = by_index.get(i)
        span = str(card.get("span") or card.get("_phi_key") or "")
        typ = str(card.get("ambig_type") or card.get("type") or "")
        cands = list(card.get("cands") or [])
        # safety net: exact copies of a Forward card are never emitted
        if any(_same_card(span, typ, cands, f) for f in fwd_list):
            kind = (action or {}).get("action") or "skip"
            log.append({"proposal_index": i, "action": "skip", "reason": "exact copy of a Forward card", "model_action": kind, "span": span})
            continue
        kind = (action or {}).get("action")
        if kind is None:
            # model omitted this proposal: keep only if it is not an exact copy (already handled)
            kind = "add_question"
            log.append({"proposal_index": i, "action": kind, "reason": "missing model action; default add_question", "span": span})
        elif kind == "skip":
            log.append({"proposal_index": i, "action": "skip", "reason": action.get("reason") or "skip", "span": span})
            continue
        if kind == "add_reading":
            target = str(action.get("target_span") or action.get("add_to_span") or span)
            new_cands = action.get("new_candidates") or action.get("new_cands") or []
            if not isinstance(new_cands, list):
                new_cands = []
            # drop cands already on the target Forward card
            target_fwd = next((f for f in fwd_list if _base_span(str(f.get("span") or "")).casefold() == _base_span(target).casefold() and str(f.get("type") or "") == typ), None)
            if target_fwd is None:
                # cannot attach; treat as a new question only if it is truly not a copy
                item = dict(card)
                item["b_action"] = "add_question"
                kept.append(item)
                log.append({"proposal_index": i, "action": "add_question", "reason": "add_reading target not found; kept as add_question", "span": span})
                continue
            already = _cand_set(target_fwd.get("candidates") or [])
            only_new = [x for x in (new_cands or cands) if _canon_cand(x) not in already]
            if not only_new:
                log.append({"proposal_index": i, "action": "skip", "reason": "add_reading had no new candidates", "span": span, "target_span": target})
                continue
            item = dict(card)
            item["b_action"] = "add_reading"
            item["add_to_span"] = str(target_fwd.get("span") or target)
            item["new_cands"] = only_new
            # keep union so the card remains valid (len>=2) if inspected alone
            item["cands"] = list(target_fwd.get("candidates") or []) + only_new
            kept.append(item)
            log.append({"proposal_index": i, "action": "add_reading", "target_span": item["add_to_span"], "n_new": len(only_new), "span": span})
            continue
        # add_question
        item = dict(card)
        item["b_action"] = "add_question"
        kept.append(item)
        log.append({"proposal_index": i, "action": "add_question", "span": span})
    return kept, log


def _sanity_backward_contract() -> int:
    """Offline check: Forward list is in the prompt; only add_question / add_reading / skip are allowed."""
    fwd = [
        {
            "span": "build-up play passing",
            "type": "Column",
            "candidates": [
                {"Team_Attributes": ["buildUpPlayPassing"]},
                {"Team_Attributes": ["buildUpPlayPassingClass"]},
            ],
        },
        {
            "span": "would remain in his position and defense while the team attacked",
            "type": "Scope",
            "candidates": ["all related rows … defensive_work_rate = 'high'"],
        },
    ]
    proposals = [
        {"proposal_index": 0, "span": "build-up play passing", "type": "Column",
         "candidates": [{"Team_Attributes": ["buildUpPlayPassing"]}, {"Team_Attributes": ["buildUpPlayPassingClass"]}]},
        {"proposal_index": 1, "span": "overall rating", "type": "Column",
         "candidates": [{"Player_Attributes": ["overall_rating"]}, {"Player_Attributes": ["potential"]}]},
        {"proposal_index": 2, "span": "would remain in his position and defense while the team attacked", "type": "Scope",
         "candidates": ["all attributes … consistent with high defensive work rate"]},
        {"proposal_index": 3, "span": "build-up play passing", "type": "Column",
         "candidates": [{"Team_Attributes": ["buildUpPlayPassing"]}, {"Team_Attributes": ["buildUpPlayPassingClass"]}, {"Team_Attributes": ["buildUpPlaySpeed"]}]},
    ]
    prompt = render_reconcile_prompt(fwd, proposals, prompt_text=RECONCILE_PROMPT.read_text(encoding="utf-8") if RECONCILE_PROMPT.is_file() else "FWD {forward_questions_json}\nBWD {backward_proposals_json}")
    ok = True
    def check(cond, msg):
        nonlocal ok
        if not cond:
            print("FAIL:", msg)
            ok = False
        else:
            print("OK:", msg)

    check("Existing Forward questions" in prompt or "forward_questions" in prompt.lower() or "build-up play passing" in prompt, "prompt includes Forward list content")
    check("build-up play passing" in prompt and "Team_Attributes" in prompt, "prompt includes Forward span and candidates")
    check("add_question" in prompt and "add_reading" in prompt and "skip" in prompt, "prompt lists the three allowed actions")
    check("delete" in prompt.lower() and "Never delete" in prompt or "must not delete" in prompt.lower() or "Do not emit a delete" in prompt, "prompt forbids delete")
    # block also used during S1+S2+S3
    block = forward_list_block(fwd)
    check("build-up play passing" in block and "Never delete" in block, "stage-fill Forward block includes the list and no-delete rule")

    frozen_raw = """```json
{
  "actions": [
    {"proposal_index": 0, "action": "add_question", "span": "build-up play passing", "type": "Column", "candidates": []},
    {"proposal_index": 1, "action": "add_question", "span": "overall rating", "type": "Column"},
    {"proposal_index": 2, "action": "skip", "reason": "paraphrase, no new reading"},
    {"proposal_index": 3, "action": "add_reading", "target_span": "build-up play passing", "type": "Column", "new_candidates": [{"Team_Attributes": ["buildUpPlaySpeed"]}]},
    {"proposal_index": 1, "action": "delete", "span": "overall rating"}
  ]
}
```"""
    actions = parse_backward_actions(frozen_raw)
    kinds = [a["action"] for a in actions]
    check(kinds == ["add_question", "add_question", "skip", "add_reading"], f"delete stripped; kinds={kinds}")
    check("delete" not in kinds, "no delete action survives parsing")

    proposed_cards = [
        {"span": "build-up play passing", "ambig_type": "Column",
         "cands": [{"Team_Attributes": ["buildUpPlayPassing"]}, {"Team_Attributes": ["buildUpPlayPassingClass"]}]},
        {"span": "overall rating", "ambig_type": "Column",
         "cands": [{"Player_Attributes": ["overall_rating"]}, {"Player_Attributes": ["potential"]}]},
        {"span": "would remain in his position and defense while the team attacked", "ambig_type": "Scope",
         "cands": ["all attributes … consistent with high defensive work rate"]},
        {"span": "build-up play passing", "ambig_type": "Column",
         "cands": [{"Team_Attributes": ["buildUpPlayPassing"]}, {"Team_Attributes": ["buildUpPlayPassingClass"]}, {"Team_Attributes": ["buildUpPlaySpeed"]}]},
    ]
    kept, log = apply_backward_actions(fwd, proposed_cards, actions)
    actions_applied = [x["action"] for x in log]
    check(actions_applied[0] == "skip", f"exact Forward copy skipped even if model said add_question; got {actions_applied[0]}")
    check(any(x["action"] == "add_question" and x["span"] == "overall rating" for x in log), "new question kept")
    check(any(x["action"] == "skip" and "paraphrase" in str(x.get("reason") or "") for x in log), "paraphrase skipped, Forward not deleted")
    reading = [c for c in kept if c.get("b_action") == "add_reading"]
    check(len(reading) == 1 and reading[0].get("add_to_span") == "build-up play passing", "add_reading attached to Forward span")
    check(reading and any("buildUpPlaySpeed" in json.dumps(x) for x in reading[0].get("new_cands") or []), "add_reading carries only the new candidate")
    check(len(fwd) == 2 and fwd[0]["span"] == "build-up play passing", "Forward list was not rewritten")
    print("kept", json.dumps([{k: c.get(k) for k in ('span','ambig_type','b_action','add_to_span','new_cands')} for c in kept], ensure_ascii=False, indent=2))
    print("log", json.dumps(log, ensure_ascii=False, indent=2))
    if ok:
        print("SANITY BACKWARD CONTRACT: PASS")
        return 0
    print("SANITY BACKWARD CONTRACT: FAIL")
    return 1


def cmd_b() -> None:
    """Backward：draft 门控 → S1+S2+S3 只收集问题（无最终 SQL）。

    Backward is given the existing Forward question list and may only add a
    truly new question, add a truly new reading to an existing card, or skip.
    There is no delete action. Forward cards are never rewritten or removed.
    """
    _patch_local_prompts()
    LLM.complete = _complete
    det._stage_fill = _stage_fill
    t0 = time.time()
    groups = {}
    for line in (OUT / "groups.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("differ"):
            groups[row["qid"]] = row
    dest = OUT / "b"
    if _is_official_backward_dest(dest) and not (os.environ.get("ABC_ALLOW_OVERWRITE_OFFICIAL_B") or "").strip():
        raise SystemExit(
            f"refusing to write official Backward dest {dest}. "
            "Point ABC_OUT at a new sibling directory (and copy or symlink groups.jsonl), "
            "or set ABC_ALLOW_OVERWRITE_OFFICIAL_B=1 if you really mean it."
        )
    dest.mkdir(parents=True, exist_ok=True)
    pred_path = dest / "pred.jsonl"
    fwd_path = _forward_pred_path()
    fwd_map: dict[str, dict] = {}
    if fwd_path.is_file():
        for line in fwd_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                qid = str(row.get("id") or row.get("qid") or "")
                if qid:
                    fwd_map[qid] = row
        print(f"[backward] forward list from {fwd_path} n={len(fwd_map)}", flush=True)
    else:
        print(f"[backward] warning: no Forward pred at {fwd_path}; Backward will not see a Forward list", flush=True)
    if not RECONCILE_PROMPT.is_file():
        raise SystemExit(f"missing Backward reconcile prompt {RECONCILE_PROMPT}")
    reconcile_tpl = RECONCILE_PROMPT.read_text(encoding="utf-8")
    done = set()
    if pred_path.exists():
        for line in pred_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line).get("id"))
    box = golds()
    todo = [qid for qid in groups if qid in box and qid not in done]
    print(
        f"B 开跑（只收集问题）：不一致 {len(groups)}，待跑 {len(todo)}。"
        f"估时大约 {max(10, len(todo) // 8)} 分钟。",
        flush=True,
    )
    urls = [f"http://127.0.0.1:{p}/v1" for p in PORTS]
    llms = [LLM(url=url) for url in urls]
    lock = threading.Lock()

    def work(spec):
        i, qid = spec
        gold = box[qid]
        gold.gold_sql = get_target_gold(qid)
        gold.gold_sqls = []
        fwd_list = forward_question_list(fwd_map.get(qid))
        block = draft_block(groups[qid])
        if fwd_list:
            block = block + "\n\n" + forward_list_block(fwd_list)
        _LOCAL.block = block
        llm = llms[i % len(llms)]
        ctx = RunContext(
            llm=llm,
            rewrite_mode="evidence",
            no_qc=True,
            parser=PARSER,
        )
        found = det.detect_ours_1bc(gold, ctx)
        proposed = list(((found.meta or {}).get("ask_cards") if found.meta else None) or [])
        proposals = proposals_from_cards(proposed)
        recon_raw = ""
        actions: list[dict] = []
        if proposed:
            recon_prompt = render_reconcile_prompt(fwd_list, proposals, prompt_text=reconcile_tpl)
            recon_raw = llm.complete(recon_prompt) or ""
            actions = parse_backward_actions(recon_raw)
        kept, action_log = apply_backward_actions(fwd_list, proposed, actions)
        if found.meta is not None:
            found.meta["ask_cards"] = kept
            found.meta["backward_actions"] = action_log
        row = pred_row(gold, found, "", PARSER)
        row["ask_cards"] = kept
        row["n_asked"] = len(kept)
        row["detect_prompt"] = list(STAGE_FILES) + ["06b_backward_reconcile.md"]
        row["pipeline"] = "backward_questions_only"
        row["backward_actions"] = action_log
        row["backward_reconcile_raw"] = recon_raw
        row["n_forward_seen"] = len(fwd_list)
        return row

    with pred_path.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=len(PORTS) * 4) as pool:
        futs = [pool.submit(work, (i, qid)) for i, qid in enumerate(todo)]
        n = 0
        for fut in as_completed(futs):
            row = fut.result()
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
            n += 1
            if n % 20 == 0 or n == len(todo):
                print(f"  B {n}/{len(todo)} {(time.time() - t0) / 60:.1f} min", flush=True)
    print(f"B 写出 {pred_path} {(time.time() - t0) / 60:.1f} min", flush=True)


def cmd_c() -> None:
    from simulator.human_simulator.standard import (
        _merge_chosen,
        format_human_prompt,
        parse_simulator_response,
    )
    from simulator.compose import render_mapping_snippet
    from schema_text import schema_numbered_rich
    from pipeline.detection.three_stage import _mk_token

    if not COVER_PROMPT.is_file():
        raise SystemExit(f"missing cover prompt {COVER_PROMPT}")
    prompt_text = COVER_PROMPT.read_text(encoding="utf-8")
    print(f"[prompts] cover={COVER_PROMPT}", flush=True)
    t0 = time.time()
    amap, bmap, gmap = {}, {}, {}
    for line in (OUT / "a/pred.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            amap[row["id"]] = row
    bpath = OUT / "b/pred.jsonl"
    if bpath.exists():
        for line in bpath.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                bmap[row["id"]] = row
    for line in (OUT / "groups.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            gmap[row["qid"]] = row
    box = golds()
    llms = [LLM(url=f"http://127.0.0.1:{p}/v1") for p in PORTS]

    def clar_items(text: str):
        marker = "User clarification:"
        i = (text or "").find(marker)
        if i < 0:
            return text or "", []
        blob = text[i + len(marker):].strip()
        if not blob or blob == "{}":
            return text[:i], []
        try:
            return text[:i], json.loads(blob)
        except json.JSONDecodeError:
            return text[:i], []

    def card_views(cards):
        out = []
        for i, c in enumerate(cards):
            readings = []
            for ch in c.get("choices") or []:
                if isinstance(ch, dict):
                    readings.append(ch.get("desc") or str(ch.get("elements")))
                else:
                    readings.append(str(ch))
            out.append({"id": i, "span": c.get("span"), "type": c.get("ambig_type"), "readings": readings})
        return out

    def groups_of(row):
        out = []
        n = 0
        for g in (row or {}).get("groups") or []:
            sql = str(g.get("sql") or "").strip()
            fp = str(g.get("fp") or "")
            if not sql or fp.startswith("ERR"):
                continue
            n += 1
            out.append({
                "group_id": n,
                "same_as_no_clarification": bool(g.get("is_y")),
                "sql": sql,
                "preview": g.get("preview") or "",
            })
        return out

    def ask_item(llm, gold, question, evidence, phrase, typ, options):
        from pipeline.scorer.decide import enabled as _scorer_on, apply_to_cards
        raw_opts = [{"text": t, "raw_id": t} for t in options]
        gold.gold_sql = get_target_gold(gold.id)
        card = {
            "span": phrase, "ambig_type": typ, "cands": options,
            "choices": [{"desc": t, "elements": [t]} for t in options],
            "interpretation": "",
        }
        if _scorer_on():
            apply_to_cards(gold, [card], evidence if evidence != "NULL" else "")
            info = card.get("scorer") or {}
            top = int(info.get("top1") or 0)
            if info.get("auto") and 0 <= top < len(options):
                selected = [options[top]]
                chosen = _merge_chosen(selected)
                tok = _mk_token(phrase, options, 0, chosen, False, "scorer", card=card, selected=selected)
                return {
                    "nl_span": tok.token,
                    "type": tok.ambig_type,
                    "interpretation": (tok.interpretation or "").strip(),
                    "mapping_snippet": render_mapping_snippet(tok.ambig_type, tok.chosen),
                    "choice": chosen,
                    "auto": True,
                    "scorer": info,
                }
        prompt, index_map = format_human_prompt(
            question=question,
            schema=schema_numbered_rich(gold),
            gold_sql=gold.gold_sql or "NULL",
            evidence=evidence or "NULL",
            raw_options=raw_opts,
        )
        selected = parse_simulator_response(llm.complete(prompt), index_map, "ours")
        if selected == "Others" or selected == ["Others"]:
            return None
        chosen = _merge_chosen(selected)
        tok = _mk_token(phrase, options, 0, chosen, False, "human_08", card=card, selected=selected)
        return {
            "nl_span": tok.token,
            "type": tok.ambig_type,
            "interpretation": (tok.interpretation or "").strip(),
            "mapping_snippet": render_mapping_snippet(tok.ambig_type, tok.chosen),
            "choice": chosen,
        }

    def pack(head, rows):
        body = "User clarification: " + ("{}" if not rows else json.dumps(rows, ensure_ascii=False))
        if head and not head.endswith("\n"):
            return head + "\n" + body
        return head + body

    qids = [qid for qid in amap if qid in box]
    print(f"C 开跑：{len(qids)} 题，只做 A+B+C 覆盖补问。", flush=True)

    def work(i, qid):
        llm = llms[i % len(llms)]
        a = amap[qid]
        b = bmap.get(qid)
        gold = box[qid]
        question = gold.question or ""
        ahead, a_items = clar_items(a.get("evidence_out") or "")
        _, b_items = clar_items((b or {}).get("evidence_out") or "")
        ev = str((gold.meta or {}).get("evidence") or "").strip()
        draft = groups_of(gmap.get(qid))
        differing = [g["group_id"] for g in draft if not g["same_as_no_clarification"]]
        cards = list(a.get("ask_cards") or []) + list((b or {}).get("ask_cards") or [])
        prompt = (
            prompt_text + "\n# Inputs\nQuestion: " + question
            + "\nEvidence:\n" + (ev or "NULL")
            + "\nQuestions:\n" + json.dumps(card_views(cards), ensure_ascii=False, indent=2)
            + "\nDraft groups:\n" + json.dumps(draft, ensure_ascii=False, indent=2)
        )
        raw = llm.complete(prompt)
        try:
            obj = json.loads(raw[raw.find("{") : raw.rfind("}") + 1]) if "{" in raw else {}
        except Exception:
            obj = {}
        covered = obj.get("covered") if isinstance(obj.get("covered"), list) else []
        new_raw = obj.get("new_questions") if isinstance(obj.get("new_questions"), list) else []
        uncovered = []
        for group_id in differing:
            hit = next((c for c in covered if c.get("group_id") == group_id), None)
            if not (hit and hit.get("question_id") is not None and hit.get("option_index") is not None):
                uncovered.append(group_id)
        kept = []
        for spec in (new_raw if uncovered else []):
            if not isinstance(spec, dict):
                continue
            readings = [str(x).strip() for x in (spec.get("readings") or []) if str(x).strip()]
            if len(readings) < 2:
                continue
            kept.append({
                "phrase": str(spec.get("phrase") or "").strip(),
                "type": str(spec.get("type") or "").strip(),
                "readings": readings[:4],
            })
        asked = []
        c_cards = []
        for spec in kept:
            item = ask_item(llm, gold, question, ev or "NULL", spec["phrase"], spec["type"], spec["readings"])
            if item:
                asked.append(item)
                c_cards.append({
                    "phrase": spec["phrase"],
                    "type": spec["type"],
                    "readings": spec["readings"],
                    "interpretation": item.get("interpretation") or "",
                    "choice": item.get("choice"),
                })
        base_items = list(a_items) + list(b_items)
        evidence = pack(ahead, base_items + asked) if asked else pack(ahead, base_items)
        return {
            "id": qid,
            "raw": raw,
            "asked": sum(1 for x in asked if not x.get("auto")),
            "c_cards": c_cards,
            "evidence": evidence,
            "changed": bool(asked),
            "schema": parser_schema(gold, a.get("schema_out") or ""),
            "question": a.get("question_out") or question,
        }

    done = []
    with ThreadPoolExecutor(max_workers=len(PORTS) * 2) as pool:
        futs = [pool.submit(work, i, qid) for i, qid in enumerate(qids)]
        n = 0
        for fut in as_completed(futs):
            done.append(fut.result())
            n += 1
            if n % 20 == 0 or n == len(qids):
                print(f"  C {n}/{len(qids)} {(time.time() - t0) / 60:.1f} min", flush=True)
    by_id = {r["id"]: r for r in done}
    cards_path = OUT / "c" / "cards.jsonl"
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    cards_path.write_text("".join(
        json.dumps({"id": r["id"], "cards": r.get("c_cards") or []}, ensure_ascii=False) + "\n"
        for r in sorted(done, key=lambda r: r["id"])
    ), encoding="utf-8")

    def parse_one(i, schema, question, evidence):
        text = llms[i % len(llms)].complete(parser_prompt(schema, question, evidence))
        return parse_sql(text) or ""

    ab = {}
    ab_jobs = []
    for qid, a in amap.items():
        b = bmap.get(qid)
        ahead, aitems = clar_items(a.get("evidence_out") or "")
        bitems = []
        if b:
            _, bitems = clar_items(b.get("evidence_out") or "")
        if not bitems:
            ab[qid] = a
            continue
        ab_jobs.append((qid, a, pack(ahead, aitems + bitems)))
    with ThreadPoolExecutor(max_workers=len(PORTS) * 4) as pool:
        futs = {
            pool.submit(parse_one, i, parser_schema(box[qid], row.get("schema_out") or ""), row.get("question_out") or "", ev): (qid, row, ev)
            for i, (qid, row, ev) in enumerate(ab_jobs)
        }
        for fut in as_completed(futs):
            qid, row, ev = futs[fut]
            out = dict(row)
            out["evidence_out"] = ev
            out["predicted_sql"] = fut.result()
            ab[qid] = out
    rows = []
    c_jobs = []
    for qid in sorted(amap):
        rec = by_id.get(qid)
        if not rec or not rec["changed"]:
            rows.append(ab.get(qid, amap[qid]))
            continue
        c_jobs.append(rec)
    with ThreadPoolExecutor(max_workers=len(PORTS) * 4) as pool:
        futs = {
            pool.submit(parse_one, i, rec["schema"], rec["question"], rec["evidence"]): rec
            for i, rec in enumerate(c_jobs)
        }
        parsed = {}
        for fut in as_completed(futs):
            rec = futs[fut]
            a = amap[rec["id"]]
            out = dict(a)
            out["evidence_out"] = rec["evidence"]
            out["predicted_sql"] = fut.result()
            b_asked = int((bmap.get(rec["id"]) or {}).get("n_asked") or 0)
            out["n_asked"] = int(a.get("n_asked") or 0) + b_asked + rec["asked"]
            parsed[rec["id"]] = out
    rows.extend(parsed[qid] for qid in sorted(parsed))
    rows.sort(key=lambda r: r["id"])
    pred = OUT / "c" / "pred.jsonl"
    pred.parent.mkdir(parents=True, exist_ok=True)
    pred.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"C 写出 {pred} {(time.time() - t0) / 60:.1f} min。打分请跑 python -m evaluator.ex --ds <数据集> --pred <pred.jsonl>", flush=True)


def cmd_from_abc() -> None:
    """DeepEye 不再重做检测。直接用 base 的 A+B+C 证据，只换解析器提示词和 schema。"""
    src = Path(os.environ["ABC_BASE_PRED"])
    t0 = time.time()
    rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    box = golds()
    pred = OUT / "c" / "pred.jsonl"
    pred.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict] = {}
    if pred.exists():
        for line in pred.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("id") and (row.get("predicted_sql") or "").strip():
                    done[row["id"]] = row
    todo = [row for row in rows if row.get("id") not in done]
    print(f"DeepEye 接受 A+B+C：来源 {src}，已有 {len(done)}，待出 SQL {len(todo)}", flush=True)
    llms = [LLM(url=f"http://127.0.0.1:{port}/v1") for port in PORTS]
    lock = threading.Lock()

    def work(spec):
        i, row = spec
        gold = box[row["id"]]
        schema = parser_schema(gold, "")
        question = row.get("question_out") or gold.question or ""
        evidence = row.get("evidence_out") or ""
        text = llms[i % len(llms)].complete(format_parser_deepeye(schema, question, evidence))
        out = dict(row)
        out["predicted_sql"] = parse_sql(text) or ""
        out["parser"] = "deepeye"
        return out

    with pred.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=len(PORTS) * 4) as pool:
        futs = [pool.submit(work, (i, row)) for i, row in enumerate(todo)]
        n = 0
        for fut in as_completed(futs):
            out = fut.result()
            with lock:
                handle.write(json.dumps(out, ensure_ascii=False) + "\n")
                handle.flush()
                done[out["id"]] = out
            n += 1
            if n % 20 == 0 or n == len(todo):
                print(f"  SQL {n}/{len(todo)} {(time.time() - t0) / 60:.1f} min", flush=True)
    ordered = [done[row["id"]] for row in rows if row.get("id") in done]
    pred.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    print(f"DeepEye 写出 {pred} {(time.time() - t0) / 60:.1f} min。打分请跑 python -m evaluator.ex --ds <数据集> --pred <pred.jsonl>", flush=True)


def _run(script: Path, *args: str) -> int:
    return subprocess.call([sys.executable, str(script), *args])


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "drafts":
        script = HERE.parent / "presql_group" / "sql_pool.py"
        print(f"SQL 池已合并到 {script}，转调统一入口", flush=True)
        sys.exit(_run(
            script,
            "--dataset", os.environ["ABC_DATASET"],
            "--out", os.environ["ABC_OUT"],
            "--ports", os.environ.get("ABC_PORTS", "8000,8100,8200,8300,8400,8500,8600,8700"),
            "--per", os.environ.get("ABC_PER_PATH", "2"),
        ))
    if cmd == "score":
        ds = os.environ.get("ABC_DATASET", "bird_arcwise")
        ds = {"bird": "bird_arcwise"}.get(ds, ds)
        pred = Path(os.environ["ABC_OUT"]) / "c" / "pred.jsonl"
        out = pred.parent / "eval.json"
        print(f"打分走 evaluator.ex：{pred} -> {out}", flush=True)
        sys.exit(subprocess.call(
            [sys.executable, "-m", "evaluator.ex", "--ds", ds, "--pred", str(pred), "--out", str(out)],
            cwd=str(ASK),
        ))
    if cmd == "sanity-backward":
        raise SystemExit(_sanity_backward_contract())
    {"b": cmd_b, "c": cmd_c, "from_abc": cmd_from_abc}[cmd]()
