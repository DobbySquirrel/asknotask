"""checks 共用运行时：本仓库 gold、冻结 pred、只读 SQL 与结果指纹、问剩余卡并重解析、EX 打分。"""
from __future__ import annotations

from collections import Counter
import json
import math
import re
import sqlite3
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from schema_text import GoldItem

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.detection.common import gold_evidence

DATASET_ALIAS = {
    "bird": "bird_arcwise",
    "bird_arcwise": "bird_arcwise",
    "ambrosia": "ambrosia",
    "clam": "clambsql",
    "clambs": "clambsql",
    "clambsql": "clambsql",
    "birdtrain": "birdtrain",
}


def normalize_dataset(name: str) -> str:
    key = (name or "").strip().lower()
    if key not in DATASET_ALIAS:
        raise SystemExit(f"unknown dataset {name!r}; expected {sorted(set(DATASET_ALIAS))}")
    return DATASET_ALIAS[key]


CHECK_NONE_DIR = REPO / "outputs" / "bird_arcwise" / "detection" / "forward"
DEFAULT_PRED = CHECK_NONE_DIR / "pred.jsonl"
DEFAULT_SCORE = CHECK_NONE_DIR / "score_paper.json"
SQL_TIMEOUT = 20.0
ROW_LIMIT = 50000


def resolve_db_path(gold) -> Path | None:
    raw = getattr(gold, "db_path", None) or ""
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = REPO / raw
    return path if path.is_file() else None


def json_canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def sql_cell(value):
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, float):
        return {"float": repr(value)} if not math.isfinite(value) else round(value, 6)
    return value


def _is_readonly_sql(sql: str) -> bool:
    text = (sql or "").strip().rstrip(";")
    return bool(re.match(r"^\s*(SELECT|WITH)\b", text, re.I))


def exec_readonly_sql(
    db_path: Path,
    sql: str,
    timeout: float = SQL_TIMEOUT,
    row_limit: int = ROW_LIMIT,
) -> dict:
    """执行只读 SELECT/WITH。成功时带 rows，调用方自行算指纹后再 pop 掉。"""
    result: dict[str, Any] = {"sql": sql, "ok": False, "db_path": str(db_path)}
    started = time.monotonic()
    conn = None
    try:
        if not _is_readonly_sql(sql):
            raise ValueError("Only SELECT or WITH queries are accepted")
        uri = "file:" + urllib.parse.quote(str(db_path.resolve()), safe="/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.execute("PRAGMA query_only=ON")
        allowed = {
            sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
            getattr(sqlite3, "SQLITE_RECURSIVE", 33),
        }
        conn.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        conn.set_progress_handler(lambda: int(time.monotonic() - started > timeout), 10000)
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(row_limit + 1)
        columns = [d[0] for d in cursor.description or []]
        result["columns"] = columns
        result["n_rows"] = len(rows)
        if len(rows) > row_limit:
            result["error"] = "row_limit_exceeded; truncated results cannot establish equality"
            result["truncated"] = True
        else:
            result["ok"] = True
            result["rows"] = rows
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if conn is not None:
            conn.close()
    result["elapsed_s"] = time.monotonic() - started
    return result


def run_sql(db_path: Path, sql: str, timeout: float = SQL_TIMEOUT, row_limit: int = ROW_LIMIT) -> dict:
    """执行只读 SQL，并用同一套指纹比较结果：列数 + 行多重集，不含列名或类型。

    空表或全 NULL 记为 vacuous，不能当作相等证据。
    """
    result = exec_readonly_sql(db_path, sql, timeout=timeout, row_limit=row_limit)
    rows = result.pop("rows", [])
    if result.get("ok"):
        bag = Counter(json_canonical([sql_cell(c) for c in row]) for row in rows)
        result["fingerprint"] = json_canonical({
            "n_cols": len(result.get("columns") or []),
            "bag": sorted(bag.items()),
        })
        if not rows:
            result["vacuous"] = True
            result["vacuous_kind"] = "empty"
        elif all(all(c is None for c in row) for row in rows):
            result["vacuous"] = True
            result["vacuous_kind"] = "all_null"
        else:
            result["vacuous"] = False
    return result


def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").strip().rstrip(";")).lower()


def sqls_literally_same(a: str, b: str) -> bool:
    return bool((a or "").strip() and (b or "").strip() and normalize_sql(a) == normalize_sql(b))


def _looks_like_expression(ident: str) -> bool:
    s = (ident or "").strip().strip('"').strip("'").strip("`").strip("[]")
    if "(" in s or ")" in s:
        return True
    if re.search(
        r"\b(CASE|WHEN|CAST|COALESCE|NULLIF|IFNULL|strftime|substr|ROUND|SUM|COUNT|AVG|MIN|MAX)\b",
        s,
        re.I,
    ):
        return True
    return bool(re.search(r"[+\*/%]", s))


def _missing_ident(error: str) -> str | None:
    m = re.search(r"no such (?:column|table):\s*(.+?)\s*$", error or "", re.I | re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def unquote_packed_expressions(sql: str, error: str = "") -> str | None:
    """If a quoted identifier is actually an expression, unquote it. Return new SQL or None."""
    text = sql or ""
    changed = text
    names: list[str] = []
    missing = _missing_ident(error)
    if missing:
        names.append(missing)
    for match in re.finditer(r'"([^"]+)"|`([^`]+)`|\[([^\]]+)\]', text):
        names.append(match.group(1) or match.group(2) or match.group(3))
    seen: set[str] = set()
    for name in names:
        if not name or name in seen or not _looks_like_expression(name):
            continue
        seen.add(name)
        for wrapped in (f'"{name}"', f"`{name}`", f"[{name}]"):
            if wrapped in changed:
                changed = changed.replace(wrapped, name)
    return changed if changed != text else None


_REPAIR_SQL_PROMPT = """# Task
A previous SQL query failed to execute. Fix executability only. Do not change the interpretation this SQL is meant to implement.

# Instructions
1. Use only tables and columns from the schema.
2. Fix the execution error (syntax, missing column or table, quoting, aggregates, or ambiguity).
3. Keep the same meaning and the same candidate binding. Do not rewrite the query to answer the original question in a different way.
4. Do not add or remove LIMIT unless the previous SQL already had one.
5. Reply with only the corrected SQL, no comments.

# Input
## Database Schema:
{schema}

## Question:
{question}

## Evidence / candidate interpretation to preserve:
{evidence}

## Previous SQL:
{sql}

## Execution Result:
{error}

Corrected SQL:
"""


def repair_sql_once(
    llm,
    *,
    schema: str,
    sql: str,
    error: str,
    question: str = "",
    evidence: str = "",
) -> str:
    """One-round execution repair. Does not revise a successful (including vacuous) query."""
    from utils.llm import parse_sql

    prompt = (
        _REPAIR_SQL_PROMPT
        .replace("{schema}", schema or "")
        .replace("{question}", question or "")
        .replace("{evidence}", evidence or "NULL")
        .replace("{sql}", sql or "")
        .replace("{error}", error or "")
    )
    fn = llm.complete
    try:
        text = fn(prompt, max_tokens=2048) or ""
    except TypeError:
        text = fn(prompt) or ""
    return (parse_sql(text) or "").strip()


def run_sql_with_repair(
    db_path: Path,
    sql: str,
    llm,
    *,
    schema: str,
    question: str = "",
    evidence: str = "",
    repair: bool = True,
) -> dict:
    """Execute; on failure try deterministic unquote, then one LLM repair. Never revise vacuous successes."""
    result = run_sql(db_path, sql)
    result["sql"] = sql
    result["original_sql"] = sql
    result["repaired"] = False
    result["unquoted"] = False
    if result.get("ok") or not repair:
        return result

    first_error = result.get("error") or ""
    sql_for_repair = sql
    unquoted = unquote_packed_expressions(sql, first_error)
    if unquoted and unquoted.strip() != sql.strip():
        ex2 = run_sql(db_path, unquoted)
        if ex2.get("ok"):
            ex2["sql"] = unquoted
            ex2["original_sql"] = sql
            ex2["repaired"] = False
            ex2["unquoted"] = True
            ex2["pre_repair_error"] = first_error
            return ex2
        sql_for_repair = unquoted
        first_error = ex2.get("error") or first_error

    fixed = repair_sql_once(
        llm,
        schema=schema,
        sql=sql_for_repair,
        error=first_error,
        question=question,
        evidence=evidence,
    )
    result["repair_attempted"] = True
    result["repaired_sql"] = fixed
    if unquoted and unquoted.strip() != sql.strip():
        result["unquoted_sql"] = unquoted
        result["unquoted"] = True
    if not fixed or sqls_literally_same(fixed, sql_for_repair):
        return result
    if not _is_readonly_sql(fixed):
        result["repair_rejected"] = "not_readonly"
        return result
    ex3 = run_sql(db_path, fixed)
    ex3["sql"] = fixed
    ex3["original_sql"] = sql
    ex3["repaired"] = True
    ex3["unquoted"] = bool(unquoted and unquoted.strip() != sql.strip())
    ex3["pre_repair_error"] = first_error
    ex3["repaired_sql"] = fixed
    return ex3


def resolve_pred(path: Path) -> Path:
    path = path.resolve()
    if path.name == "score_paper.json":
        cand = path.parent / "pred.jsonl"
        if not cand.is_file():
            raise SystemExit(f"score next to missing pred: {cand}")
        return cand
    if path.is_dir():
        cand = path / "pred.jsonl"
        if not cand.is_file():
            raise SystemExit(f"missing {cand}")
        return cand
    if not path.is_file():
        raise SystemExit(f"missing pred {path}")
    return path


def load_freeze(pred: Path) -> dict[str, dict]:
    frozen: dict[str, dict] = {}
    for line in pred.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        meta = dict(row.get("meta") or {})
        for k in ("phi", "span_types", "span_interps", "ask_cards"):
            if k in row and not meta.get(k):
                meta[k] = row[k]
        phi = {k: list(v) for k, v in (meta.get("phi") or {}).items()}
        types = dict(meta.get("span_types") or {})
        interps = dict(meta.get("span_interps") or {})
        for c in meta.get("ask_cards") or row.get("ask_cards") or []:
            sp = c.get("_phi_key") or c.get("span")
            if sp and c.get("ambig_type"):
                types.setdefault(sp, str(c["ambig_type"]))
            if sp and c.get("interpretation"):
                interps.setdefault(sp, str(c["interpretation"]))
        frozen[row["id"]] = {
            "phi": phi,
            "span_types": types,
            "span_interps": interps,
            "baseline_sql": row.get("predicted_sql") or "",
            "baseline_n_asked": int(row.get("n_asked") or 0),
            "question_out": row.get("question_out"),
            "schema_out": row.get("schema_out"),
            "evidence_out": row.get("evidence_out"),
            "source_row": {
                k: row[k] for k in row
                if k not in {"meta", "detect_prompts", "phi", "ask_cards", "span_types"}
            },
        }
    print(f"[freeze] {len(frozen)} from {pred}", flush=True)
    return frozen


def baseline_score(score_path: Path | None) -> dict:
    if score_path is None or not score_path.is_file():
        return {}
    data = json.loads(score_path.read_text(encoding="utf-8"))
    blob = data.get("summary") if isinstance(data.get("summary"), dict) else data
    ex = blob.get("ex") if isinstance(blob, dict) else None
    if isinstance(ex, dict):
        return {"ex": ex.get("ex"), "n_hit": ex.get("n_hit"), "n": ex.get("n") or blob.get("n_gold")}
    return {}


def format_parser(tag: str = "checks"):
    import importlib.util

    path = REPO / "parsers" / "qwen_coder.py"
    spec = importlib.util.spec_from_file_location(f"ask_qwen_coder_{tag}", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.format_parser_base


def done_ids(out: Path) -> set[str]:
    done: set[str] = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    return done


def ask_and_reparse(
    gold,
    llm,
    format_parser_base,
    phi_prime: dict,
    span_types: dict,
    span_interps: dict,
    *,
    healed: dict | None = None,
    use_qc: bool = False,
) -> dict[str, Any]:
    """对剩余 ≥2 的卡全问，把 healed 拼进澄清，再改写并解析 SQL。

    use_qc=True 时先用 detection/prompts/06c_ours_qc_1bc.md 把候选写成澄清选项。
    """
    import pipeline.detection.three_stage as det
    from simulator.human_simulator.standard import PickResult
    from utils.llm import parse_sql
    from simulator.compose import apply_rewrite
    from schema_text import schema_clear_text, schema_map_for_prompt, schema_numbered_rich

    types = dict(span_types or {})
    interps = dict(span_interps or {})
    healed = healed or {}
    smap = schema_map_for_prompt(gold)
    schema = schema_clear_text(smap)
    schema_llm = schema_numbered_rich(gold)
    ev = gold_evidence(gold) or ""
    q = gold.question or ""

    n_qc = 0
    if use_qc:
        phi_ask = {
            span: list(cands)
            for span, cands in phi_prime.items()
            if span not in healed and isinstance(cands, list) and len(cands) >= 2
        }
        cards, n_qc = det._qc_cards(
            llm, q, phi_ask, 0, healed,
            no_qc=False,
            span_types=types,
            span_interps=interps,
            schema_content=schema_llm,
            evidence=ev or "NULL",
        )
        asked = {str(c.get("_phi_key") or c.get("span") or "") for c in cards}
    else:
        cards = []
        asked = set()
        for span, cands in phi_prime.items():
            if span in healed or not isinstance(cands, list) or len(cands) < 2:
                continue
            asked.add(span)
            cards.append({
                "span": det._display_span(span),
                "_phi_key": span,
                "cands": cands,
                "choices": det._raw_choices(cands),
                "ambig_type": str(types.get(span) or ""),
                "interpretation": str(interps.get(span) or ""),
                "batch": 0,
                "qc": {"clarification_question": det._display_span(span), "skipped_qc": True},
            })
    tokens, clarification = det._ask_human_cards(
        gold, llm, cards, q, schema_llm, ev or "NULL", types, interps,
    )
    for span, cand in healed.items():
        if span in asked:
            continue
        tokens.append(det._mk_token(
            span, [cand], 0, cand, False, "self_heal",
            span_types=types, span_interps=interps,
        ))
        clarification[span] = cand
    pick = PickResult(simulator="ours_1bc_08", tokens=tokens, ambiguity_clarification=clarification)
    q_out, s_out, e_out = apply_rewrite(
        "evidence",
        question=q,
        schema_str=schema,
        schema_map=smap,
        mapping=det.phi_to_mapping(phi_prime),
        pick=pick,
        evidence=ev,
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
        "n_qc": n_qc,
        "ask_cards_final": cards,
        "no_qc": not use_qc,
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_golds(dataset: str = "bird_arcwise", ids: list[str] | None = None, limit: int | None = None) -> list[GoldItem]:
    ds = normalize_dataset(dataset)
    gold_path = REPO / "dataset" / ds / "gold.jsonl"
    if not gold_path.is_file():
        raise SystemExit(f"missing {gold_path}")
    items = {str(r.get("qid") or r.get("id")): r for r in _read_jsonl(REPO / "dataset" / ds / "items.jsonl")}
    golds: list[GoldItem] = []
    n_no_q = 0
    for row in _read_jsonl(gold_path):
        qid = str(row.get("qid") or row.get("id") or "")
        extra = items.get(qid) or {}
        golds_sql = row.get("gold") or extra.get("gold_sqls") or []
        if isinstance(golds_sql, str):
            golds_sql = [golds_sql]
        gold_sql = extra.get("gold_sql") or (golds_sql[0] if golds_sql else None)
        question = str(extra.get("question") or row.get("question") or "")
        evidence = extra.get("evidence") if "evidence" in extra else row.get("evidence") or ""
        if not question:
            n_no_q += 1
        gold = GoldItem(
            id=qid,
            dataset=ds,
            db_id=str(row.get("db_id") or extra.get("db_id") or ""),
            question=question,
            db_path=str(row.get("db_path") or extra.get("db_path") or ""),
            dialect="sqlite",
            gold_sql=gold_sql,
            gold_sqls=list(golds_sql),
            meta={"evidence": evidence or "", "intended": row.get("intended"), "split": extra.get("split") or row.get("split") or ""},
        )
        resolved = gold.resolved_db_path()
        if resolved:
            gold.db_path = resolved
        golds.append(gold)
    if ids:
        want = set(ids)
        golds = [g for g in golds if g.id in want or any(g.id.endswith(":" + w) for w in want)]
    if limit is not None:
        golds = golds[:limit]
    if n_no_q:
        print(
            f"[golds] {ds}: {len(golds)} loaded, {n_no_q} without question "
            f"(add dataset/{ds}/items.jsonl with question/evidence)",
            flush=True,
        )
    else:
        print(f"[golds] {ds}: {len(golds)} loaded", flush=True)
    return golds


def score_pred(dataset: str, pred: Path, out_json: Path) -> dict:
    from evaluator.ex import score

    ds = normalize_dataset(dataset)
    pred = Path(pred).resolve()
    out_json = Path(out_json).resolve()
    if not pred.is_file():
        raise SystemExit(f"missing pred {pred}")
    data = score(ds, pred)
    gold_key = data.get("gold_key") or "gold"
    ex_map = data.get("ex") or {}
    ex_val = ex_map.get(gold_key)
    n_hit = (data.get("correct") or {}).get(gold_key)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    slim = dict(data)
    out_json.write_text(json.dumps(slim, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = _read_jsonl(pred)
    q = sum(float(r.get("n_asked") or 0) for r in rows) / len(rows) if rows else 0.0
    probes = sum(float(r.get("n_probes") or 0) for r in rows) / len(rows) if rows else 0.0
    healed = sum(float(r.get("n_healed") or 0) for r in rows) / len(rows) if rows else 0.0
    return {
        "n": data.get("n"),
        "ex": ex_val,
        "n_hit": n_hit,
        "gold_key": gold_key,
        "Q": round(q, 4),
        "probes": round(probes, 4),
        "healed": round(healed, 4),
    }


def normalize_pred_and_score(pred: Path, baseline: Path | None) -> tuple[Path, Path | None]:
    pred = Path(pred)
    if pred.suffix == ".json" and pred.name == "score_paper.json":
        if baseline is None:
            baseline = pred
        pred = pred.parent / "pred.jsonl"
    return pred, baseline


def resolve_baseline_score(pred_path: Path, baseline_score_path: Path | None) -> Path | None:
    if baseline_score_path is not None:
        return Path(baseline_score_path)
    cand = pred_path.parent / "score_paper.json"
    if cand.is_file():
        return cand
    return DEFAULT_SCORE if DEFAULT_SCORE.is_file() else None


def open_frozen_run(
    *,
    pred_path: Path,
    out_dir: Path,
    ids: list[str],
    limit: int | None,
    resume: bool,
    dataset: str = "bird_arcwise",
) -> tuple[Path, dict, list, list, Path]:
    pred_path = resolve_pred(pred_path)
    frozen = load_freeze(pred_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pred = out_dir / "pred.jsonl"
    done = done_ids(out_pred) if resume else set()
    if not resume and out_pred.exists():
        out_pred.unlink()
        done = set()
    golds = load_golds(dataset, ids=ids or None, limit=limit)
    work = [g for g in golds if g.id in frozen and g.id not in done]
    return pred_path, frozen, golds, work, out_pred


def score_against_baseline(dataset: str, out_pred: Path, out_dir: Path, baseline_score_path: Path | None):
    metrics = score_pred(dataset, out_pred, out_dir / "score_paper.json")
    base = baseline_score(baseline_score_path)
    delta = (
        (metrics["ex"] - base["ex"])
        if isinstance(metrics.get("ex"), (int, float)) and isinstance(base.get("ex"), (int, float))
        else None
    )
    return metrics, base, delta


def parse_flag_args(
    argv: list[str],
    *,
    default_out: Path | None = None,
    extras: dict[str, tuple[str, int, Callable]] | None = None,
) -> dict[str, Any]:
    extras = extras or {}
    pred = DEFAULT_PRED
    baseline = DEFAULT_SCORE if DEFAULT_SCORE.is_file() else None
    out = default_out
    limit = None
    ids: list[str] = []
    resume = False
    extra_vals: dict[str, Any] = {}
    i = 0
    while i < len(argv):
        if argv[i] == "--pred" and i + 1 < len(argv):
            pred = Path(argv[i + 1]); i += 2
        elif argv[i] == "--baseline-score" and i + 1 < len(argv):
            baseline = Path(argv[i + 1]); i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out = Path(argv[i + 1]); i += 2
        elif argv[i] == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1]); i += 2
        elif argv[i] == "--ids" and i + 1 < len(argv):
            ids = [x.strip() for x in argv[i + 1].split(",") if x.strip()]; i += 2
        elif argv[i] == "--resume":
            resume = True; i += 1
        elif argv[i] in extras:
            key, n, fn = extras[argv[i]]
            if i + n >= len(argv):
                raise SystemExit(f"{argv[i]} needs {n} value(s)")
            extra_vals[key] = fn(*argv[i + 1:i + 1 + n])
            i += 1 + n
        else:
            raise SystemExit(f"unknown arg {argv[i]}")
    pred, baseline = normalize_pred_and_score(pred, baseline)
    return {
        "pred": pred,
        "baseline": baseline,
        "out": out,
        "limit": limit,
        "ids": ids,
        "resume": resume,
        **extra_vals,
    }

