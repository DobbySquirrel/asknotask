"""CLEAR 检出后处理：规则修正 + Vagueness LLM + Human type-2 重检。不改 repos/CLEAR。

官方 MappingCorrector.correct_mapping_file(mode='all') 的 elif 只会改 query、改不到 match；
这里按论文意图两路都改。Vagueness 官方 de_vague_file 调了不存在的 de_vague_data，这里调 de_vague_data_llm。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_CLEAR = Path(__file__).resolve().parents[2] / "repos" / "CLEAR"
if str(_CLEAR) not in sys.path:
    sys.path.insert(0, str(_CLEAR))

try:
    from src.stop_words import get_stop_words, get_symbols
except Exception:  # pragma: no cover
    def get_stop_words():
        return set()

    def get_symbols():
        return {",", ".", "?", "'", '"', "!", "(", ")", "/", ";"}


VAGUE_PROMPT = '''### Ambiguity Resolution Task
    When you are performing a text-to-SQL task, you encounter ambiguity during schema linking.
    For the provided ambiguous question and keyword, select the appropriate option to clarify the keyword.
    Each option consists of the option number, the column name, and the column meaning.
    Each option can contain multiple columns, separated by a newline.
    Follow these rules:
    1. Single choice and multiple choice are both allowed.
    2. Respond with the option number.
    3. If some options are all suitable for the keyword, respond with "and", such as [1] and [2] and ...
    4. If some options are either suitable for the keyword, respond with "or", such as [1] or [2] or ...
    5. You can also respond with the combination of "and" and "or", such as ([2] or [3]) and [1] or ...

    Question: [QUESTION]

    Keyword: [TOKEN]

    Options:
    [OPTIONS]

    Answer: '''


def as_dict(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def filter_match(match: Any) -> dict:
    amb = as_dict(match)
    out: dict[str, list] = {}
    for token, options in amb.items():
        if not isinstance(options, list):
            continue
        kept = []
        for table_dict in options:
            if not isinstance(table_dict, dict):
                continue
            td = {}
            for table, columns in table_dict.items():
                if not isinstance(columns, list):
                    columns = [columns] if isinstance(columns, str) else []
                columns = list(dict.fromkeys(columns))
                if columns:
                    td[table] = columns
            if td and td not in kept:
                kept.append(td)
        if len(kept) >= 2:
            out[token] = kept
    return out


def tokenize_question(sentence: str) -> list[str]:
    raw = re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", sentence or "")
    out, skip = [], False
    for i, tok in enumerate(raw):
        if skip:
            skip = False
            continue
        if tok == "-" and out and i + 1 < len(raw):
            out[-1] = out[-1] + "-" + raw[i + 1]
            skip = True
        elif tok.startswith("#") and out:
            out[-1] += tok.strip("#")
        else:
            out.append(tok)
    return out


def _query_type(qmap: dict) -> Optional[str]:
    for token, interps in qmap.items():
        if not isinstance(interps, list):
            continue
        for p in interps:
            if str(p).startswith("for each") or str(p).startswith("common to all"):
                return "scope"
            for p2 in interps:
                if "and" in str(p2).split() or "or" in str(p2).split():
                    return "attachment"
    return None


def convert_attach(question: str, qmap: dict) -> dict:
    if _query_type(qmap) != "attachment" or not qmap:
        return qmap
    token = next(iter(qmap))
    interpretations = qmap[token]
    new: dict[str, list] = {}
    for attachment_word in ("and", "or"):
        for p in interpretations:
            if attachment_word not in str(p).split():
                continue
            e1 = str(p).split(attachment_word)[0].strip()
            e2 = str(p).split(attachment_word)[1].strip()
            if f"{p} {token}" in question:
                e_token = f"{p} {token}"
                new[e_token] = [
                    f"{e2} {token} {attachment_word} {e1} {token}",
                    f"{e2} {token} {attachment_word} {e1}",
                ]
            elif f"{token} {p}" in question:
                e_token = f"{token} {p}"
                new[e_token] = [
                    f"{token} {e1} {attachment_word} {token} {e2}",
                    f"{e2} {attachment_word} {e2} {token}",
                ]
    return new or qmap


def correct_query(question: str, query_map: Any) -> dict:
    qmap = as_dict(query_map)
    if not qmap:
        return {}
    token = next(iter(qmap))
    if token not in (question or ""):
        return {}
    interps = qmap[token]
    if not isinstance(interps, list) or len(interps) < 2:
        return {}
    ambig_type = _query_type({token: interps})
    if ambig_type == "scope":
        new = []
        for scope_word in ("each", "every", "all"):
            if scope_word not in token.split():
                continue
            token_n = token[token.find(scope_word) :].strip()
            entity = token_n[token_n.find(scope_word) + len(scope_word) :].strip()
            for p in interps:
                ps = str(p)
                if ps.startswith(f"for {scope_word}") or ps.startswith("for each"):
                    p = f"for each {entity} individually"
                elif ps.startswith("common to all"):
                    p = " ".join(f"common to all {' '.join(entity.split()[:-1])} {ps.split()[-1]}".split())
                new.append(p)
            return {token_n: new} if new else {}
        return {}
    if ambig_type == "attachment":
        for w in ("and", "or"):
            if w in token.split():
                return {token: interps}
        return convert_attach(question, qmap)
    return {}


def sqlite_primary_keys(db_path: str) -> dict[str, list[str]]:
    path = Path(db_path or "")
    if not db_path or not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        for (table,) in tables:
            if not table or str(table).startswith("sqlite_"):
                continue
            cols = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            pks = [row[1] for row in cols if row[5]]
            if pks:
                out[table] = pks
    except Exception:
        return {}
    finally:
        conn.close()
    return out


def extend_primary_keys(primary_keys: dict, schema_map: dict[str, list[str]]) -> dict:
    pks = {t: list(v) for t, v in (primary_keys or {}).items()}
    for table, columns in (schema_map or {}).items():
        pks.setdefault(table, [])
        for column in columns:
            if (column.lower().endswith("_id") or column.endswith("Id") or column.lower() == "id") and column not in pks[table]:
                pks[table].append(column)
    return pks


def _pks_required(primary_keys: dict, question: str) -> dict:
    required = {}
    for table, cols in (primary_keys or {}).items():
        hit = [c for c in cols if c.replace("_", " ").lower() in (question or "").lower()]
        if hit:
            required[table] = hit
    return required


def _score_fn():
    from ..human_simulator.official_clear import _retriever

    return _retriever()


def _top1(query: str, cands: list[str], score_fn) -> str:
    if not cands:
        return query
    best, best_s = cands[0], -1.0
    for c in cands:
        s = float(score_fn(query, c))
        if s > best_s:
            best, best_s = c, s
    return best


def interp_lookup(
    schema_map: dict[str, list[str]],
    interps: Optional[dict[str, dict[str, str]]] = None,
) -> dict[str, dict[str, str]]:
    if interps:
        return interps
    out: dict[str, dict[str, str]] = {}
    for table, cols in (schema_map or {}).items():
        out[table] = {c: f'{c}: In table "{table}". {c}.' for c in cols}
    return out


def correct_match(
    question: str,
    match_map: Any,
    schema_map: dict[str, list[str]],
    db_path: str = "",
    interps: Optional[dict[str, dict[str, str]]] = None,
) -> dict:
    amb = filter_match(match_map)
    new: dict[str, list] = {}
    for token, options in amb.items():
        kept = []
        for table_dict in options:
            td = {}
            for table, columns in table_dict.items():
                ok = [c for c in columns if table in schema_map and c in (schema_map.get(table) or [])]
                if ok:
                    td[table] = ok
            if td:
                kept.append(td)
        if len(kept) < 2:
            continue
        token_new = ref_question_span(question, token)
        new[token_new] = kept
    out = filter_match(new)
    pks = extend_primary_keys(sqlite_primary_keys(db_path), schema_map)
    if not pks:
        return out
    required = _pks_required(pks, question)
    mmap2 = json.loads(json.dumps(out))
    for token, options in list(mmap2.items()):
        for i, table_dict in enumerate(options):
            for table, columns in list(table_dict.items()):
                for column in list(columns):
                    if column in (pks.get(table) or []):
                        if table not in required or column not in required[table]:
                            mmap2[token][i][table].remove(column)
    return filter_match(mmap2)


def _option_lines(options: list, interps: dict[str, dict[str, str]]) -> str:
    chunks = []
    for i, option_tuple in enumerate(options):
        lines = []
        for option in option_tuple:
            if "." not in str(option):
                lines.append(str(option))
                continue
            table, column = str(option).split(".", 1)
            lines.append((interps.get(table) or {}).get(column) or str(option))
        chunks.append(f"[{i + 1}] " + "\n\t".join(lines))
    return "\n".join(chunks) + "\n"


def _to_list(schema_tuple: list) -> list:
    options = []
    for table_dict in schema_tuple:
        row = []
        if isinstance(table_dict, dict):
            for table, cols in table_dict.items():
                for c in cols if isinstance(cols, list) else [cols]:
                    row.append(f"{table}.{c}")
        options.append(row)
    return options


def _to_tuple(options: list) -> list:
    out = []
    for option_tuple in options:
        td: dict[str, list] = {}
        for col in option_tuple:
            if "." not in str(col):
                continue
            t, c = str(col).split(".", 1)
            td.setdefault(t, []).append(c)
        if td:
            out.append(td)
    return out


def parse_vague_choice(res: str, options: list) -> list:
    try:
        if "(" in res:
            idx = [int(x) - 1 for x in re.findall(r"\[(.*?)\]", res)]
            return [options[i] for i in idx if 0 <= i < len(options)] or options
        options_new = []
        for sub_res in res.split("or"):
            if not re.search(r"\[(.*?)\]", sub_res):
                continue
            if "and" in sub_res:
                list_and = []
                for part in sub_res.split("and"):
                    m = re.findall(r"\[(.*?)\]", part)
                    if not m:
                        continue
                    idx = int(m[0]) - 1
                    if 0 <= idx < len(options):
                        options_new.append(options[idx])
                        list_and.extend(options[idx])
                if list_and:
                    options_new.append(list_and)
            else:
                idx = int(re.findall(r"\[(.*?)\]", sub_res)[0]) - 1
                if idx == len(options):
                    return options
                if 0 <= idx < len(options):
                    options_new.append(options[idx])
        return options_new or options
    except Exception:
        return options


def _vote(texts: list[str]) -> str:
    cleaned = [t.strip() for t in texts if str(t).strip()]
    if not cleaned:
        return ""
    return Counter(cleaned).most_common(1)[0][0]


def ref_question_span(question: str, h: str) -> str:
    """MC-Rule 5：h ← Ref(Q, h)，Q 的原文子序列，不对齐到单个词。"""
    q = question or ""
    hs = " ".join(str(h or "").split("_")).strip()
    if not hs:
        return str(h or "")
    if hs in q:
        return hs
    low = q.lower()
    i = low.find(hs.lower())
    if i >= 0:
        return q[i : i + len(hs)]
    qtoks = tokenize_question(q)
    best, best_n = hs, 0
    for n in range(len(qtoks), 0, -1):
        for j in range(len(qtoks) - n + 1):
            span = "".join(qtoks[j : j + n]) if all(len(t) == 1 for t in qtoks[j : j + n]) else " ".join(qtoks[j : j + n])
            # 连续原文：从首 token 在 Q 中的位置切到末 token
            raw = q[q.lower().find(qtoks[j].lower()) :] if qtoks[j] else ""
            # 用问句里从第 j 个 token 起的原文切片
            try:
                start = low.find(qtoks[j].lower())
                end = low.find(qtoks[j + n - 1].lower(), start) + len(qtoks[j + n - 1])
                span = q[start:end] if start >= 0 and end > start else " ".join(qtoks[j : j + n])
            except Exception:
                span = " ".join(qtoks[j : j + n])
            sl = span.lower()
            if sl in hs.lower() or hs.lower() in sl:
                if n > best_n:
                    best, best_n = span, n
        if best_n:
            break
    return best


def _n_cols(table_dict: dict) -> int:
    n = 0
    for cols in table_dict.values():
        n += len(cols) if isinstance(cols, list) else 1
    return n


def _col_values(db_path: str, table: str, column: str, limit: int = 100) -> list:
    path = Path(db_path or "")
    if not db_path or not path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL ORDER BY "{column}" LIMIT {int(limit)}'
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _option_values(table_dict: dict, db_path: str) -> list:
    out = []
    for table, cols in (table_dict or {}).items():
        for c in cols if isinstance(cols, list) else [cols]:
            out.append(_col_values(db_path, table, c, 100))
    return out


def _value_sim(v1: list, v2: list) -> float:
    if not v1 or not v2:
        return 0.0
    if v1 == v2:
        return 1.0
    s1, s2 = {str(x) for x in v1}, {str(x) for x in v2}
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def vd_flag(opts: list, db_path: str = "", delta: float = 0.9) -> Optional[bool]:
    """True=vague，False=非 vague，None=未判定。VD-2 / VD-3。不看 gold。"""
    dicts = [d for d in (opts or []) if isinstance(d, dict)]
    if len(dicts) < 2:
        return None
    counts = {_n_cols(d) for d in dicts}
    if len(counts) != 1:
        return True
    if not db_path:
        return None
    for i in range(len(dicts) - 1):
        a, b = _option_values(dicts[i], db_path), _option_values(dicts[i + 1], db_path)
        if not a or not b or not a[0] or not b[0]:
            continue
        flat_a = [x for row in a for x in (row if isinstance(row, list) else [row])]
        flat_b = [x for row in b for x in (row if isinstance(row, list) else [row])]
        if _value_sim(flat_a, flat_b) > delta:
            return False
    return None


def add_union_interpretations(match: Any) -> dict:
    """论文 VD-Rule 1：Vagueness 时 Add(s_i ∪ s_j)，不删原选项。"""
    mmap = filter_match(match)
    out: dict[str, list] = {}
    for token, opts in mmap.items():
        merged: dict[str, list] = {}
        for table_dict in opts:
            if not isinstance(table_dict, dict):
                continue
            for table, columns in table_dict.items():
                cl = columns if isinstance(columns, list) else [columns]
                merged.setdefault(table, [])
                for c in cl:
                    if c not in merged[table]:
                        merged[table].append(c)
        new = list(opts)
        if merged and merged not in new:
            new.append(merged)
        out[token] = new
    return filter_match(out)


def de_vague_match(
    llm,
    parse_json,
    question: str,
    match_map: Any,
    schema_map: dict,
    n_vote: int = 1,
    interps: Optional[dict[str, dict[str, str]]] = None,
    db_path: str = "",
    delta: float = 0.9,
) -> dict:
    mmap = filter_match(match_map)
    if not mmap:
        return mmap
    out: dict[str, list] = {}
    for token, opts in mmap.items():
        flag = vd_flag(opts, db_path=db_path, delta=delta)
        if flag is False:
            out[token] = opts
        else:
            out[token] = add_union_interpretations({token: opts}).get(token, opts)
    return filter_match(out)


def revision_notes(pick, match_map: dict) -> list[str]:
    notes = []
    msg = getattr(pick, "msg", None) or {}
    match = as_dict(match_map)
    for token, rec in msg.items():
        if not isinstance(rec, dict) or rec.get("type") != 2:
            continue
        tds = match.get(token) or []
        notes.append(
            f'There are no ambiguities regarding the "{token}" mentioned in the question when considering '
            + " and ".join(str(x) for x in tds)
            + "."
        )
    return notes


def postprocess_mapping(
    question: str,
    mapping: dict,
    schema_map: dict[str, list[str]],
    db_path: str = "",
    llm=None,
    parse_json=None,
    n_vote: int = 1,
    do_vague: bool = True,
    interps: Optional[dict[str, dict[str, str]]] = None,
) -> dict:
    query = correct_query(question, mapping.get("query") or {})
    match = correct_match(
        question, mapping.get("match") or {}, schema_map, db_path, interps=interps
    )
    if do_vague and llm is not None:
        match = de_vague_match(
            llm,
            parse_json,
            question,
            match,
            schema_map,
            n_vote=n_vote,
            interps=interps,
            db_path=db_path,
            delta=0.9,
        )
    return {"query": query, "match": match}
