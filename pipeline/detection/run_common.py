"""detection 实验脚本共用的读写与打分辅助。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ASK = Path(__file__).resolve().parents[2]


def n_asked(det_row) -> int:
    meta = det_row.meta or {}
    if meta.get("n_asked") is not None:
        return int(meta["n_asked"])
    pick = det_row.pick
    if pick is not None and getattr(pick, "tokens", None):
        n = sum(1 for t in pick.tokens if getattr(t, "source", "") == "human_08")
        if n:
            return n
    return len(meta.get("ask_cards") or [])


def load_jsonl(path: Path) -> dict[str, dict]:
    """按 id/qid 读 jsonl。文件不存在时返回空字典。"""
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = str(row.get("id") or row.get("qid") or "")
        if qid:
            out[qid] = row
    return out


def card_key(card: dict, *, phrase: bool = False) -> str:
    raw = card.get("_phi_key") or card.get("span") or ""
    if phrase and not raw:
        raw = card.get("phrase") or ""
    return str(raw).strip().lower()


def specs_to_cards(specs: list) -> list[dict]:
    """把 coverage 的 new_questions 规格转成 ask cards。"""
    cards = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        phrase = str(spec.get("phrase") or "").strip()
        typ = str(spec.get("type") or "").strip()
        readings = [str(x).strip() for x in (spec.get("readings") or []) if str(x).strip()]
        if not phrase or len(readings) < 2:
            continue
        readings = readings[:4]
        cards.append(
            {
                "span": phrase,
                "_phi_key": phrase,
                "ambig_type": typ,
                "cands": readings,
                "choices": [{"desc": t, "elements": [t]} for t in readings],
                "interpretation": "",
                "source": "coverage_c",
                "batch": 9,
            }
        )
    return cards

def score(pred: Path, out_json: Path) -> dict[str, Any]:
    out_json.unlink(missing_ok=True)
    cmd = [
        sys.executable, "-u", "-m", "evaluator.ex",
        "--ds", "bird_arcwise",
        "--pred", str(pred),
        "--out", str(out_json),
        "--qid-key", "id",
        "--sql-key", "predicted_sql",
    ]
    print(f"[score] {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(ASK), capture_output=True, text=True)
    text = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"evaluator.ex failed\n{text}")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    gold_key = data.get("gold_key") or "gold"
    ex_map = data.get("ex") if isinstance(data.get("ex"), dict) else {}
    correct_map = data.get("correct") if isinstance(data.get("correct"), dict) else {}
    rows = [json.loads(l) for l in pred.read_text(encoding="utf-8").splitlines() if l.strip()]
    q = sum(float(r.get("n_asked") or 0) for r in rows) / max(1, len(rows))
    return {
        "n": data.get("n") or len(rows),
        "ex": ex_map.get(gold_key),
        "n_hit": correct_map.get(gold_key),
        "Q": q,
        "raw_tail": text[-500:],
    }
