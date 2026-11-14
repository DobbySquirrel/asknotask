#!/usr/bin/env python3
"""Detection 消融（本地更新后的 06* prompt；**无** 07c/07d 探针 check）。

两档，都跑 06c QC：
  s123       S1+S2+S3
  oneprompt  单枪 06b_ours_detect_1bc_oneprompt.md

每次实验通过 RUN_TAG 使用新输出目录；默认不读取旧结果，
只有显式指定 --resume 才允许断点续跑。默认 workers=1。

用法（需本机 vLLM，默认 :8000 Qwen3-Coder）：
  # 每档先跑 1 题到 SQL+EX，确认链路
  python pipeline/detection/run_forward_ablation_v2.py smoke --id bird:62 --workers 1

  # 全量（确认稳定前请用 workers=1）
  python pipeline/detection/run_forward_ablation_v2.py all --workers 1
  python pipeline/detection/run_forward_ablation_v2.py s123 --workers 1

  # 断点续跑
  python pipeline/detection/run_forward_ablation_v2.py all --resume --workers 1
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# =========================
# Basic paths
# 本文件在 pipeline/detection/ 下：
#   HERE=detection, ASK=askornotask, PROMPTS=detection/prompts
# =========================

HERE = Path(__file__).resolve().parent
ASK = HERE.parents[1]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))
PROMPTS = HERE / "prompts"
ITEMS = ASK / "dataset" / "bird_arcwise" / "items.jsonl"

# 每次 Prompt 或代码发生重要变化时都要修改，禁止复用旧目录
RUN_TAG = "forward_ablation"

OUT_ROOT = (
    ASK / "outputs" / "bird_arcwise" / "predictions" / "qwen_coder" / RUN_TAG
)

LOG_DIR = OUT_ROOT / "logs"
MANIFEST = OUT_ROOT / "manifest.json"

ONEPROMPT = "06b_ours_detect_1bc_oneprompt.md"

QC_FILE = "06c_ours_qc_1bc.md"

ARMS = (
    "s123",
    "oneprompt",
)

ARM_ALIAS = {
    "s123": "s123",
    "s1s2s3": "s123",
    "three": "s123",
    "s123_bc": "s123",
    "three_bc": "s123",
    "bc": "s123",
    "oneprompt": "oneprompt",
    "one": "oneprompt",
    "oneprompt_bc": "oneprompt",
    "one_bc": "oneprompt",
}

# 检出引擎 = 本仓 pipeline/detection；不调用 frozen/compare
from pipeline.detection.three_stage import STAGE_FILES  # noqa: E402
from pipeline.detection.run_common import n_asked as _n_asked  # noqa: E402


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None

    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def _build_manifest(llm=None) -> dict:
    prompt_files = [
        PROMPTS / ONEPROMPT,
        *(PROMPTS / name for name in STAGE_FILES),
        PROMPTS / QC_FILE,
    ]

    manifest = {
        "run_tag": RUN_TAG,
        "dataset": "bird_arcwise",
        "arms": list(ARMS),
        "oneprompt": ONEPROMPT,
        "stage_files": list(STAGE_FILES),
        "qc_file": QC_FILE,
        "prompt_sha256": {
            str(path): _file_sha256(path)
            for path in prompt_files
        },
        "detect_seed": "20261021",
        "answer_seed": "20261028",
        "max_tokens": os.environ.get(
            "PAPER_EXP_LLM_MAX_TOKENS",
            "4096",
        ),
        "no_table": os.environ.get(
            "PAPER_EXP_NO_TABLE",
            "1",
        ),
        "workers": None,
        "model": getattr(llm, "model", None),
        "url": getattr(llm, "url", None),
        "created_at": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }

    return manifest


def _write_manifest(llm=None, workers: int | None = None) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    data = _build_manifest(llm)
    data["workers"] = workers

    with MANIFEST.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"[manifest] {MANIFEST}", flush=True)


def _install_runtime() -> None:
    os.environ.setdefault("PAPER_EXP_LLM_MAX_TOKENS", "4096")
    os.environ["PAPER_EXP_LLM_SEED_VALUE"] = "20261021"
    os.environ["PAPER_EXP_NO_TABLE"] = "1"
    os.environ.pop("PAPER_EXP_KEEP_BOTH", None)
    engine = HERE / "three_stage.py"
    if not engine.is_file():
        raise SystemExit(f"missing detect engine: {engine}")
    if not ITEMS.is_file():
        raise SystemExit(f"missing dataset items: {ITEMS}")
    import utils.llm as llm_mod

    if getattr(llm_mod.LLM.complete, "_paper_seed_patched", False):
        return
    orig = llm_mod.LLM.complete

    def complete(self, prompt, tries: int = 3, temperature: float = 0):
        if "selected_labels" in (prompt or ""):
            os.environ["PAPER_EXP_LLM_SEED_VALUE"] = "20261028"
        else:
            os.environ["PAPER_EXP_LLM_SEED_VALUE"] = "20261021"
        return orig(self, prompt, tries=tries, temperature=temperature)

    complete._paper_seed_patched = True  # type: ignore[attr-defined]
    llm_mod.LLM.complete = complete
    print(f"[runtime] pipeline detect={engine} items={ITEMS}", flush=True)
    print("[runtime] LLM seed patch: detect=20261021 sim=20261028", flush=True)


def _assert_prompts() -> None:
    need = [ONEPROMPT, QC_FILE, *STAGE_FILES]
    for name in need:
        path = PROMPTS / name
        if not path.is_file():
            raise SystemExit(f"missing prompt {path}")
        print(f"  ok {name}", flush=True)


def _load_py(name: str, path: Path):
    import importlib.util

    if not path.is_file():
        raise SystemExit(f"missing module {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _patch_detect_module():
    """本仓 pipeline/detection/three_stage + detection/prompts；关掉探针 check。"""
    from pipeline.detection import three_stage as det

    det.REVIEW = PROMPTS
    if hasattr(det, "STAGE_FILES"):
        det.STAGE_FILES = STAGE_FILES
    print(f"[prompts] REVIEW={det.REVIEW} NO_TABLE=1 checks=OFF", flush=True)
    _assert_prompts()
    return det


def _load_one_stage():
    mod = _load_py("ask_one_stage_v2", HERE / "one_stage.py")
    mod.ONE_SHOT = ONEPROMPT
    mod.PROMPTS = PROMPTS
    return mod


def _make_ctx(llm):
    from pipeline.runtime import RunContext

    return RunContext(
        llm=llm,
        rewrite_mode="evidence",
        no_qc=False,
        parser="base",
    )


def _load_golds(limit: int | None, ids: list[str]):
    from pipeline.checks.runtime import load_golds

    return load_golds("bird_arcwise", ids=ids or None, limit=limit)


def _format_parse(det_row, llm) -> str:
    from utils.llm import parse_sql
    import importlib.util

    qc = ASK / "parsers" / "qwen_coder.py"
    spec = importlib.util.spec_from_file_location("ask_qwen_coder_fwd", qc)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    prompt = mod.format_parser_base(
        det_row.schema_out or "",
        det_row.question_out or "",
        det_row.evidence_out or "",
    )
    return parse_sql(llm.complete(prompt)) or ""


def _run_metadata(arm: str, llm) -> dict:
    return {
        "system": arm,
        "pipeline": arm,
        "checks": False,
        "detect_seed": "20261021",
        "answer_seed": "20261028",
        "model": getattr(llm, "model", None),
        "llm_url": getattr(llm, "url", None),
        "detect_prompt": (
            ONEPROMPT
            if arm.startswith("oneprompt")
            else list(STAGE_FILES)
        ),
        "qc_prompt": QC_FILE,
        "no_qc": False,
        "run_tag": RUN_TAG,
    }


def _run_one(arm: str, gold, ctx, det, os_mod) -> dict:
    if arm.startswith("oneprompt"):
        os_mod.ONE_SHOT = ONEPROMPT
        row = os_mod.run_one_stage(gold, ctx)
        row.update(_run_metadata(arm=arm, llm=ctx.llm))
        row["detect_prompt"] = ONEPROMPT
        return row

    # s123：三阶段检出 + 06c
    det_row = det.detect_ours_1bc(gold, ctx)
    sql = _format_parse(det_row, ctx.llm)
    meta = dict(det_row.meta or {})
    return {
        "id": gold.id,
        "db_id": getattr(gold, "db_id", None),
        **_run_metadata(arm=arm, llm=ctx.llm),
        "parser": "qwen_coder",
        "question_out": det_row.question_out,
        "schema_out": det_row.schema_out,
        "evidence_out": det_row.evidence_out,
        "predicted_sql": sql,
        "n_asked": _n_asked(det_row),
        "n_answered": meta.get("n_answered"),
        "n_healed": int(meta.get("n_healed") or 0),
        "n_qc": int(meta.get("n_qc") or 0),
        "no_qc": False,
        "phi": meta.get("phi") or {},
        "ask_cards": meta.get("ask_cards") or [],
        "span_types": meta.get("span_types") or {},
        "meta": meta,
        "detect_prompts": list(STAGE_FILES),
        "qc_prompt": QC_FILE,
    }


def _done_ids(
    out: Path,
    *,
    resume: bool,
) -> set[str]:
    if not resume:
        return set()

    done: set[str] = set()

    if out.exists():
        for line_no, line in enumerate(
            out.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
                sample_id = row["id"]
            except Exception as e:
                raise RuntimeError(
                    f"Invalid JSON in {out}:{line_no}: {e}"
                ) from e

            if sample_id in done:
                raise RuntimeError(
                    f"Duplicate id in {out}: {sample_id}"
                )

            done.add(sample_id)

    return done


def _clear_arm_outputs(arm: str) -> None:
    """非 resume 时删掉该 arm 的旧 pred / shard / score，避免和新结果混写。"""
    out_dir = OUT_ROOT / arm
    if not out_dir.exists():
        return
    for path in [out_dir / "pred.jsonl", out_dir / "score_paper.json"]:
        path.unlink(missing_ok=True)
    for shard in out_dir.glob("pred.shard*.jsonl"):
        shard.unlink(missing_ok=True)


def _merge_shards(out: Path) -> None:
    by_id: dict[str, dict] = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                by_id[r["id"]] = r
    shards = sorted(out.parent.glob("pred.shard*.jsonl"))
    for shard in shards:
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            by_id.setdefault(r["id"], r)
    tmp = out.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in by_id.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(out)
    for shard in shards:
        shard.unlink(missing_ok=True)
    print(f"[merge] {out} n={len(by_id)}", flush=True)


def _score_ex(arm: str) -> dict:
    pred = OUT_ROOT / arm / "pred.jsonl"
    out_json = OUT_ROOT / arm / "score_paper.json"

    if not pred.exists():
        raise RuntimeError(
            f"Missing prediction file: {pred}"
        )

    # 严禁读取上一次旧结果
    out_json.unlink(missing_ok=True)

    rows = [
        json.loads(line)
        for line in pred.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if not rows:
        raise RuntimeError(
            f"Empty prediction file: {pred}"
        )

    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError(
            f"Duplicate ids in {pred}"
        )

    q = sum(
        float(row.get("n_asked") or 0)
        for row in rows
    ) / len(rows)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{arm}_ex.log"

    cmd = [
        sys.executable,
        "-u",
        "-m",
        "evaluator.ex",
        "--ds",
        "bird_arcwise",
        "--pred",
        str(pred),
        "--out",
        str(out_json),
        "--qid-key",
        "id",
        "--sql-key",
        "predicted_sql",
    ]

    print(
        f"[score] {' '.join(cmd)}",
        flush=True,
    )

    proc = subprocess.run(
        cmd,
        cwd=str(ASK),
        capture_output=True,
        text=True,
    )

    text = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode != 0:
        with log_path.open("w", encoding="utf-8") as f:
            f.write(text)

        raise RuntimeError(
            f"evaluator.ex failed for {arm}\n"
            f"returncode={proc.returncode}\n"
            f"{text}"
        )

    if not out_json.exists():
        raise RuntimeError(
            f"evaluator.ex succeeded but did not create {out_json}\n"
            f"{text}"
        )

    data = json.loads(
        out_json.read_text(encoding="utf-8")
    )

    # evaluator.ex: {n, ex: {gold: float, ...}, correct: {gold: int}, q, ...}
    gold_key = data.get("gold_key") or "gold"
    ex_map = data.get("ex") if isinstance(data.get("ex"), dict) else {}
    correct_map = data.get("correct") if isinstance(data.get("correct"), dict) else {}
    ex_value = ex_map.get(gold_key)
    n_hit = correct_map.get(gold_key)
    n_gold = data.get("n")
    blob = data

    summary = {
        "arm": arm,
        "n": len(rows),
        "Q": round(q, 4),
        "ex": ex_value,
        "n_hit": n_hit,
        "n_gold": n_gold,
        "score_exit": proc.returncode,
    }

    with log_path.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
            )
        )
        f.write("\n\n--- score.py output ---\n")
        f.write(text)

    print(
        f"[ex {arm}] "
        f"n={summary['n']} "
        f"EX={summary['ex']} "
        f"n_hit={summary['n_hit']} "
        f"Q={summary['Q']}",
        flush=True,
    )

    return summary


def _run_arm(
    arm: str,
    golds,
    llm,
    det,
    os_mod,
    *,
    resume: bool = False,
    shard_i: int | None = None,
    shard_n: int | None = None,
) -> Path:
    out_dir = OUT_ROOT / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    main_out = out_dir / "pred.jsonl"
    if shard_i is not None and shard_n is not None:
        out = out_dir / f"pred.shard{shard_i}.jsonl"
        tag = f"{arm}/s{shard_i}"
    else:
        out = main_out
        tag = arm
        if not resume:
            _clear_arm_outputs(arm)

    done = _done_ids(main_out, resume=resume)
    if out.exists() and out != main_out and resume:
        for line_no, line in enumerate(
            out.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue

            row = json.loads(line)
            sample_id = row["id"]

            if sample_id in done:
                raise RuntimeError(
                    f"Duplicate id across outputs: {sample_id}"
                )

            done.add(sample_id)

    work = []
    for i, gold in enumerate(golds):
        if shard_i is not None and shard_n is not None and (i % shard_n) != shard_i:
            continue
        if gold.id in done:
            continue
        work.append((i + 1, gold))

    ctx = _make_ctx(llm)
    n_new = 0
    t0 = time.time()
    mode = "a" if resume else "w"
    with out.open(mode, encoding="utf-8") as f:
        for idx, gold in work:
            print(f"[{tag} {idx}/{len(golds)}] {gold.id}", flush=True)
            row = _run_one(arm, gold, ctx, det, os_mod)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            n_new += 1
            sql = (row.get("predicted_sql") or "").replace("\n", " ")
            print(
                f"  n_asked={row.get('n_asked')} n_qc={row.get('n_qc')} "
                f"sql={sql[:160]}",
                flush=True,
            )
    print(
        f"[done {tag}] new={n_new} elapsed={(time.time()-t0)/60:.1f}min out={out}",
        flush=True,
    )
    return out


def _spawn_workers(arm: str, workers: int, extra_args: list[str], *, resume: bool = False) -> None:
    if not resume:
        _clear_arm_outputs(arm)

    script = str(Path(__file__).resolve())
    procs = []
    for i in range(workers):
        cmd = [
            sys.executable, "-u", script, arm,
            "--shard", f"{i}/{workers}",
            *extra_args,
        ]
        log = OUT_ROOT / arm / f"worker{i}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        print(f"[spawn] {' '.join(cmd)} > {log}", flush=True)
        procs.append(subprocess.Popen(
            cmd,
            cwd=str(ASK),
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
        ))
    codes = [p.wait() for p in procs]
    if any(c != 0 for c in codes):
        raise SystemExit(f"worker failed: {codes}")
    _merge_shards(OUT_ROOT / arm / "pred.jsonl")
    rows = [
        json.loads(l)
        for l in (OUT_ROOT / arm / "pred.jsonl").read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    q = sum(float(r.get("n_asked") or 0) for r in rows) / len(rows) if rows else 0.0
    print(f"[done {arm}] n={len(rows)} Q={q:.4f}", flush=True)
    _score_ex(arm)


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        raise SystemExit(0)

    arm_raw = args[0]
    extra = args[1:]
    limit = None
    ids: list[str] = []
    workers = 1
    resume = False
    shard_i = shard_n = None
    passthrough: list[str] = []
    i = 0
    while i < len(extra):
        if extra[i] == "--limit" and i + 1 < len(extra):
            limit = int(extra[i + 1]); passthrough += extra[i:i + 2]; i += 2
        elif extra[i] in {"--ids", "--id"} and i + 1 < len(extra):
            ids = [x.strip() for x in extra[i + 1].split(",") if x.strip()]
            passthrough += ["--ids", extra[i + 1]]; i += 2
        elif extra[i] == "--workers" and i + 1 < len(extra):
            workers = int(extra[i + 1]); i += 2
        elif extra[i] == "--resume":
            resume = True
            passthrough += ["--resume"]
            i += 1
        elif extra[i] == "--shard" and i + 1 < len(extra):
            a, b = extra[i + 1].split("/", 1)
            shard_i, shard_n = int(a), int(b); i += 2
        else:
            raise SystemExit(f"unknown arg {extra[i]}")

    if arm_raw == "smoke":
        arms = list(ARMS)
        if not ids:
            ids = ["bird:62"]
        workers = 1
        limit = None
    elif arm_raw in {"all", "four", "two"}:
        arms = list(ARMS)
    else:
        if arm_raw not in ARM_ALIAS:
            raise SystemExit(f"unknown arm {arm_raw}; choose {list(ARMS)}|smoke|all")
        arms = [ARM_ALIAS[arm_raw]]

    _install_runtime()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    if workers > 1 and shard_i is None:
        _write_manifest(workers=workers)
        for arm in arms:
            print(f"[parallel] arm={arm} workers={workers}", flush=True)
            _spawn_workers(arm, workers, passthrough, resume=resume)
        print("\n=== summary ===", flush=True)
        for arm in arms:
            p = OUT_ROOT / arm / "score_paper.json"
            if not p.exists():
                print(f"{arm}: (no score)", flush=True)
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            blob = data.get("summary") if isinstance(data.get("summary"), dict) else data
            ex = blob.get("ex") if isinstance(blob, dict) else None
            if isinstance(ex, dict):
                print(
                    f"{arm}: EX={ex.get('ex')} n_hit={ex.get('n_hit')}/{ex.get('n')}",
                    flush=True,
                )
            else:
                print(f"{arm}: {blob}", flush=True)
        return

    det = _patch_detect_module()
    os_mod = _load_one_stage()
    from utils.llm import LLM

    llm = LLM()
    print(f"[llm] {llm.model} @ {llm.url}", flush=True)
    golds = _load_golds(limit, ids)
    print(f"[data] bird n={len(golds)} shard={shard_i}/{shard_n} arms={arms}", flush=True)
    if shard_i is None:
        _write_manifest(llm=llm, workers=workers)
    for arm in arms:
        _run_arm(
            arm, golds, llm, det, os_mod,
            resume=resume, shard_i=shard_i, shard_n=shard_n,
        )
        if shard_i is None:
            rows = [
                json.loads(l)
                for l in (OUT_ROOT / arm / "pred.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            q = sum(float(r.get("n_asked") or 0) for r in rows) / len(rows) if rows else 0.0
            print(f"[done {arm}] n={len(rows)} Q={q:.4f}", flush=True)
            _score_ex(arm)


if __name__ == "__main__":
    main()
