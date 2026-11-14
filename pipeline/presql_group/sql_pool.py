#!/usr/bin/env python3
"""SQL 池生成：按 DC / Skeleton / ICL 采样候选 SQL，再按执行结果分组。

用法：
  python pipeline/presql_group/sql_pool.py --dataset bird_arcwise --out DIR
  python pipeline/presql_group/sql_pool.py --dataset birdtrain --out DIR --few-shot

输入是数据集里的问题、evidence 和 schema；ICL 的 few-shot 用 --few-shot 打开。
每路默认 2 条（--per），另生成一条温度 0 的未澄清 SQL，用于分组对照。
输出 DIR/drafts.jsonl 与 DIR/groups.jsonl。

可选：--ports 8000,8100（也可用环境变量 ABC_PORTS），--per 2（也可用 ABC_PER_PATH）。

生成用提示词在 pipeline/presql_group/prompts/。检测见 pipeline/detection/coverage.py；打分见 pipeline/scorer/。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ASK = Path(__file__).resolve().parents[2]
if str(ASK) not in sys.path:
    sys.path.insert(0, str(ASK))

PROMPTS = Path(__file__).resolve().parent / "prompts"
FEW = Path(__file__).resolve().parent / "bird_dev_few_shots.json"

from evaluator.ex import fingerprint  # noqa: E402
from pipeline.checks.runtime import load_golds  # noqa: E402
from schema_text import schema_clear_text, schema_map_for_prompt, schema_numbered_rich  # noqa: E402
from utils.llm import LLM, parse_sql  # noqa: E402

RESULT = re.compile(r"<result>\s*(.*?)\s*</result>", re.S | re.I)
METHODS = ("DC", "Skeleton", "ICL")


def _read_prompt(name: str) -> str:
    path = PROMPTS / name
    if not path.is_file():
        raise FileNotFoundError(f"缺少提示词 {path}")
    return path.read_text(encoding="utf-8")


def format_parser_base(schema_with_content: str, question: str, evidence: str = "") -> str:
    return (
        _read_prompt("parser_base.md")
        .replace("[SCHEMA_WITH_CONTENT]", schema_with_content or "")
        .replace("[EVIDENCE]", evidence.strip() if evidence and str(evidence).strip() else "NULL")
        .replace("[QUESTION]", question or "")
    )


def format_prompt(method: str, schema: str, question: str, evidence: str, few_shot_examples=None) -> str:
    names = {"DC": "birdtrain_dc.md", "Skeleton": "birdtrain_skeleton.md", "ICL": "birdtrain_icl.md"}
    if method not in names:
        raise ValueError(f"未知路径: {method}")
    text = _read_prompt(names[method])
    if method == "ICL":
        examples = few_shot_examples or []
        few = "\n".join(
            f"- Example {i + 1}:\nQuestion: {ex['question']}\nSQL: {ex['sql']}"
            for i, ex in enumerate(examples)
        )
        text = text.replace("{FEW_SHOT_EXAMPLES}", few)
    return (
        text.replace("{DATABASE_SCHEMA}", schema or "")
        .replace("{QUESTION}", question or "")
        .replace("{HINT}", evidence or "")
    )


def load_items(dataset: str) -> dict:
    return {g.id: g for g in load_golds(dataset)}


def item_schema(gold, cache: dict) -> str:
    key = gold.db_path or gold.db_id or ""
    if key in cache:
        return cache[key]
    text = schema_numbered_rich(gold)
    cache[key] = text
    return text


def chat(port: int, prompt: str, temperature: float, seed: int | None) -> str:
    llm = chat.pool[port]
    kwargs = dict(
        model=llm.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=4096,
        extra_body={"enable_thinking": False},
    )
    if seed is not None:
        kwargs["seed"] = seed
    from utils.llm import _room_for_completion

    for _ in range(3):
        try:
            resp = llm.client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            found = RESULT.search(text)
            if found:
                return found.group(1).strip()
            return parse_sql(text) or ""
        except Exception as exc:
            room = _room_for_completion(str(exc))
            if room is not None and room < int(kwargs.get("max_tokens") or 0):
                kwargs["max_tokens"] = room
                print(f"[llm] shrink max_tokens to {room}", flush=True)
                continue
            print(f"[llm] {type(exc).__name__}: {exc}", flush=True)
            return ""
    return ""


chat.pool = {}


def _run_sql(sql: str, db: str, timeout_s: float = 15.0) -> tuple[bool, str, list]:
    if not sql or not str(sql).strip():
        return False, "empty", []
    try:
        conn = sqlite3.connect(db, timeout=timeout_s)
    except sqlite3.Error as exc:
        return False, f"connect: {exc}", []
    deadline = time.monotonic() + timeout_s
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    try:
        rows = conn.execute(sql).fetchall()
        return True, "", list(rows)
    except sqlite3.OperationalError as exc:
        msg = "timeout" if "interrupted" in str(exc) else str(exc)
        return False, msg, []
    except Exception as exc:
        return False, str(exc), []
    finally:
        conn.set_progress_handler(None, 0)
        conn.close()


def preview(sql: str, db: str) -> tuple[str, str]:
    ok, err, rows = _run_sql(sql, db, timeout_s=15)
    if not ok:
        if "timeout" in err.lower() or "超时" in err:
            return "ERR:timeout", "返回很多行"
        return f"ERR:{err or 'failed'}", "执行失败"
    fp = fingerprint(rows)
    n = len(rows or [])
    bits = []
    seen = set()
    for row in rows or []:
        if not row or row[0] is None:
            continue
        cell = str(row[0])
        if cell in seen:
            continue
        seen.add(cell)
        bits.append(cell)
        if len(bits) == 3:
            break
    text = f"返回 {n} 行"
    if bits:
        text += "，例如 " + "、".join(bits)
    return fp, text


def load_few_shots() -> tuple[dict, list]:
    if not FEW.is_file():
        raise FileNotFoundError(f"缺少 few-shot 文件 {FEW}")
    few = json.loads(FEW.read_text(encoding="utf-8"))
    fallback = few.get("0") or next(iter(few.values()))
    return few, fallback


def few_for(qid: str, few: dict, fallback: list) -> list:
    tail = qid.rsplit(":", 1)[-1]
    return few.get(tail) or few.get(qid) or fallback


def method_prompt(schema: str, question: str, evidence: str, method: str, few_shot_examples=None) -> str:
    if method == "never":
        return format_parser_base(schema, question, evidence)
    if method in {"DC", "Skeleton", "ICL"}:
        return format_prompt(method, schema, question, evidence, few_shot_examples)
    raise ValueError(f"未知路径: {method}")


def parse_ports(text: str) -> list[int]:
    ports = [int(p) for p in text.split(",") if p.strip()]
    if not ports:
        raise ValueError("至少要有一个端口")
    return ports


def cmd_drafts(dataset: str, out: Path, ports: list[int], per: int, few_shot: bool) -> None:
    os.environ.setdefault("PAPER_EXP_LLM_MAX_TOKENS", "4096")
    t0 = time.time()
    print(
        f"草稿开跑：dataset={dataset}，DC / Skeleton / ICL 各 {per} 条，温度 0.7，不传种子。"
        f"{'ICL 带 few-shot。' if few_shot else 'ICL 不带 few-shot。'}"
        "另有一条温度 0 的不澄清 SQL。",
        flush=True,
    )
    for port in ports:
        chat.pool[port] = LLM(url=f"http://127.0.0.1:{port}/v1")
    few, fallback = load_few_shots() if few_shot else ({}, [])
    box = load_items(dataset)
    done = {}
    out.mkdir(parents=True, exist_ok=True)
    path = out / "drafts.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row["sqls"] = [s for s in (row.get("sqls") or []) if str(s).strip()]
            done[(row["qid"], row["path"])] = row
    jobs = []
    schemas: dict[str, str] = {}
    need = {"never": 1, "DC": per, "Skeleton": per, "ICL": per}
    for qid, gold in box.items():
        schema = item_schema(gold, schemas)
        question = gold.question or ""
        evidence = str((gold.meta or {}).get("evidence") or "")
        examples = few_for(qid, few, fallback) if few_shot else []
        prompts = {
            "never": method_prompt(schema, question, evidence, "never"),
            "DC": method_prompt(schema, question, evidence, "DC"),
            "Skeleton": method_prompt(schema, question, evidence, "Skeleton"),
            "ICL": method_prompt(schema, question, evidence, "ICL", examples),
        }
        for method, prompt in prompts.items():
            have = done.get((qid, method))
            if have and len([s for s in have.get("sqls") or [] if s.strip()]) >= need[method]:
                continue
            jobs.append((qid, method, prompt, need[method]))
    print(f"待采样 {len(jobs)}，已有 {len(done)} 组", flush=True)
    lock = threading.Lock()

    def work(spec):
        i, (qid, method, prompt, n) = spec
        have = [s for s in ((done.get((qid, method)) or {}).get("sqls") or []) if str(s).strip()]
        port = ports[i % len(ports)]
        temp = 0.0 if method == "never" else 0.7
        seed = 20261021 if method == "never" else None
        tries = 0
        while len(have) < n and tries < n + 2:
            tries += 1
            got = chat(port, prompt, temp, seed)
            if got.strip():
                have.append(got)
        return {"qid": qid, "path": method, "sqls": have[:n]}

    with path.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=len(ports) * 4) as pool:
        futs = [pool.submit(work, (i, job)) for i, job in enumerate(jobs)]
        n = 0
        for fut in as_completed(futs):
            row = fut.result()
            with lock:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                done[(row["qid"], row["path"])] = row
            n += 1
            if n % 40 == 0 or n == len(jobs):
                print(f"  草稿 {n}/{len(jobs)} {(time.time() - t0) / 60:.1f} min", flush=True)
    by = {}
    for (qid, method), row in done.items():
        by.setdefault(qid, {}).setdefault(method, []).extend(row.get("sqls") or [])
    groups_path = out / "groups.jsonl"
    with groups_path.open("w", encoding="utf-8") as handle:
        for qid, parts in sorted(by.items()):
            gold = box[qid]
            db = gold.db_path or ""
            ysql = next((s for s in parts.get("never") or [] if s.strip()), "")
            y_fp, _ = preview(ysql, db) if ysql else ("", "")
            buckets = {}
            n_draft = 0
            for method in METHODS:
                for sql in parts.get(method) or []:
                    if not str(sql).strip():
                        continue
                    n_draft += 1
                    fp, text = preview(sql, db)
                    if fp.startswith("ERR"):
                        continue
                    buckets.setdefault(fp, {
                        "sql": sql,
                        "fp": fp,
                        "preview": text,
                        "is_y": fp == y_fp and bool(y_fp) and not y_fp.startswith("ERR"),
                    })
            groups = list(buckets.values())
            differ = any(not g["is_y"] for g in groups) and bool(groups)
            handle.write(json.dumps({
                "qid": qid,
                "n_draft": n_draft,
                "differ": differ,
                "groups": groups,
            }, ensure_ascii=False) + "\n")
    print(f"分组 {groups_path} {(time.time() - t0) / 60:.1f} min", flush=True)


# 下面这些是给 detection/coverage.py 和 scorer 用的兼容接口，
# 不作为 SQL 池的入口。后续实验入口改掉后可以再删。
_ABC333 = None


def _abc333():
    """abc333 的环境只在 coverage / score 时加载。"""
    global _ABC333
    if _ABC333 is not None:
        return _ABC333
    ds = os.environ["ABC_DATASET"]
    parser = os.environ["ABC_PARSER"]
    out = Path(os.environ["ABC_OUT"])
    ports = parse_ports(os.environ.get("ABC_PORTS", "8000,8100,8200,8300,8400,8500,8600,8700"))
    per_path = int(os.environ.get("ABC_PER_PATH", "2"))
    os.environ.setdefault("PAPER_EXP_LLM_MAX_TOKENS", "4096")
    _ABC333 = {
        "DS": ds,
        "PARSER": parser,
        "OUT": out,
        "PORTS": ports,
        "PER_PATH": per_path,
        "METHODS": METHODS,
    }
    return _ABC333


def __getattr__(name: str):
    if name in {"DS", "PARSER", "OUT", "PORTS", "PER_PATH", "METHODS"}:
        return _abc333()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def draft_schema(gold) -> str:
    """deepeye / BIRD 用编号 schema；base 解析器用短 schema 文本。"""
    cfg = _abc333()
    if cfg["DS"] == "bird" or cfg["PARSER"] == "deepeye":
        return schema_numbered_rich(gold)
    return schema_clear_text(schema_map_for_prompt(gold))


def parser_schema(gold, schema_out: str = "") -> str:
    """deepeye 解析器不用改写留下的短列名。base 仍用 schema_out。"""
    if _abc333()["PARSER"] == "deepeye":
        return draft_schema(gold)
    return schema_out or ""


def golds() -> dict:
    return load_items(_abc333()["DS"])


def parser_prompt(schema: str, question: str, evidence: str) -> str:
    return format_parser_base(schema, question, evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 SQL 池并按执行结果分组。")
    parser.add_argument(
        "--dataset",
        required=True,
        help="本仓库数据集名：bird_arcwise（也可写 bird）、birdtrain、ambrosia、clambsql",
    )
    parser.add_argument("--out", required=True, type=Path, help="输出目录，写入 drafts.jsonl 与 groups.jsonl")
    parser.add_argument("--few-shot", action="store_true", help="给 ICL 填入本目录的 BIRD few-shot 例子")
    parser.add_argument(
        "--ports",
        default=os.environ.get("ABC_PORTS", "8000,8100"),
        help="LLM 端口，逗号分隔",
    )
    parser.add_argument(
        "--per",
        type=int,
        default=int(os.environ.get("ABC_PER_PATH", "2")),
        help="DC / Skeleton / ICL 每路条数",
    )
    args = parser.parse_args()
    cmd_drafts(args.dataset, args.out, parse_ports(args.ports), args.per, args.few_shot)


if __name__ == "__main__":
    main()
