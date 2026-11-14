# SOURCE: see pipeline/SOURCE.md
"""Existence check：Column / Join / Value / NULL / Aggregate / Project / Tie。

目标：先剪「客观不存在」的候选，再做主键剪枝与 Column 值重叠；剪光则整卡 DropCard（含 Join，不撤销）。
- Column / Join / Tie：核 table.col；缺一剔整条候选
- Project（多列 dict）：只剔不存在的列，保留剩余列；一列不剩才丢候选；T.* 展开为明确列后再去掉未提及主键
- Aggregate：只能核纯列名绑定；公式（比较、CASE、函数等）一律 keep，不把表达式整段当成缺列丢掉；仅当留下非主键度量时才去掉未提及主键
- Column / Join：问句未点名的正式主键（PRAGMA 主键或指向主键的外键）整条去掉；Date/year 列不走主键剪枝；问句在要 ID 时不剪；剪光且候选指向不同表时整卡保留（歧义是哪张表的标识）；若剪光且候选是同一张表指向不同维表的互斥外键，也整卡保留；同一条关系的两端仍 Drop。仅当其余候选被客观否证（缺列、枚举中不存在）时才 AutoResolve；因主键剪枝或公式未解析才剩下一条则不 Auto，把不确定的候选放回再问。点名含查库：列自身或外键指向维表中的区分性取值出现在问句里则不剪
- Column 值重叠：只做跨表；列名相近且取值 Jaccard > 0.9 时去掉冗余侧；同名跨表列不合并；原列与 min_/max_/avg_/sum_ 等预聚合列不合并；问句提及程度相同时两留
- Value：本文件自带查库逻辑；剥包裹引号；数字禁止 LIKE 改写/enum 误丢；非同字面量禁止 LIKE 改写；已含 SQL 通配符或日期格式的字面量不走 enum_absent；缺列去重不算 Auto；不做主键剪枝；年份字面量若已有安全的日期 year_prefix，丢掉其他列上不安全的度量/ID 命中；同列同值的数字写法、同列同一天的日期写法合并后再决定 Auto
- NULL：本文件自带查库逻辑（列是否可空）
- Project 空列列表（{Table: []}）视为无效，不进 Auto；phi key 的 \n[Type] 后缀在 span_types 缺失时可补类型
- Scope / Attachment / Tie：不进主键剪枝与值重叠；Scope / Attachment 不进 Existence
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_TYPES = {"Column", "Join", "Aggregate", "Project", "Tie"}
DB_TYPES = {"Value", "NULL"}
EXIST_TYPES = SCHEMA_TYPES | DB_TYPES

IDENT = re.compile(r"^[A-Za-z_][\w]*$")
QUAL = re.compile(r"^([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)$")
SPAN_TYPE_SUFFIX = re.compile(r"\n\[([A-Za-z]+)\]\s*$")


_FORMULA_MARK = re.compile(
    r"(?i)(?:>=|<=|<>|!=|==|[<>]|\bCASE\b|\bWHEN\b|\bTHEN\b|\bELSE\b|\bEND\b"
    r"|\bBETWEEN\b|\bAND\b|\bOR\b|\bNOT\b|\bIS\s+(?:NOT\s+)?NULL\b"
    r"|\bLIKE\b|\bIN\s*\(|\bCAST\s*\(|[()/*+]|="
    r"|\bSUM\b|\bCOUNT\b|\bAVG\b|\bMIN\b|\bMAX\b|\bCOALESCE\b|\bNULLIF\b)"
)
_DATE_LITERAL = re.compile(
    r"^(?:\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?|\d{8})$"
)


def _is_formula_text(text: str) -> bool:
    """比较运算、CASE/函数或算术表达式，不是单一列名。"""
    s = (text or "").strip().strip("'\"").strip("`").strip("[]")
    if not s:
        return False
    if _FORMULA_MARK.search(s):
        return True
    return False


def _walk_strings(cand: Any):
    if isinstance(cand, str):
        yield cand
    elif isinstance(cand, dict):
        for k, v in cand.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(cand, list):
        for x in cand:
            yield from _walk_strings(x)


def _cand_tables(cand: Any) -> set[str]:
    tables: set[str] = set()
    for table, _col in _parse_col_bindings(cand):
        if table:
            tables.add(str(table).lower())
    if isinstance(cand, dict):
        for key in cand:
            name = str(key)
            if "." in name:
                name = name.split(".", 1)[0]
            name = name.strip()
            if name:
                tables.add(name.lower())
    return tables


def _pk_prune_is_cross_table(cands: list) -> bool:
    """剪光后若候选指向至少两张表，歧义是哪张表的标识，不能 DropCard。"""
    tables: set[str] = set()
    for cand in cands or []:
        tables |= _cand_tables(cand)
    return len(tables) >= 2


def _is_sql_wildcard_literal(val: Any) -> bool:
    s = str(val) if val is not None else ""
    if "%" in s:
        return True
    return bool("_" in s and re.search(r"\d", s))


def _is_date_like_literal(val: Any) -> bool:
    s = str(val).strip() if val is not None else ""
    return bool(_DATE_LITERAL.fullmatch(s))


ENUM_N_DISTINCT = 20
_SQL_TIMEOUT_S = 60.0
_SCHEMA_SKIP = {"sqlite_sequence", "sqlite_master", "sqlite_stat1", "sqlite_stat4"}


class ProbeAbort(Exception):
    pass


@lru_cache(maxsize=32)
def _load_schema(db_path: str) -> dict[str, dict[str, str]]:
    path = Path(db_path or "")
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
            if r[0] and str(r[0]).lower() not in _SCHEMA_SKIP
        ]
        for table in names:
            cols = conn.execute(f"PRAGMA table_info({_qident(table)})").fetchall()
            out[table] = {row[1]: (row[2] or "") for row in cols if row[1]}
    finally:
        conn.close()
    return out


def _resolve_ident(schema: dict[str, dict[str, str]], table: str, col: str | None) -> tuple[str, str] | None:
    tkey = next((t for t in schema if t.lower() == str(table).lower()), None)
    if tkey is None or not col:
        return None
    ckey = next((c for c in schema[tkey] if c.lower() == str(col).lower()), None)
    if ckey is None:
        return None
    return tkey, ckey


def _open_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=500")
    return conn


def _exec_sql(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple = (),
    n: int = 8,
    timeout_s: float | None = None,
) -> list[tuple]:
    deadline = time.time() + (_SQL_TIMEOUT_S if timeout_s is None else float(timeout_s))
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 100)
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchmany(n)
        return [tuple(r) for r in rows]
    except sqlite3.OperationalError as e:
        msg = str(e)
        if "interrupted" in msg.lower() or time.time() >= deadline:
            raise ProbeAbort("timeout") from e
        raise ProbeAbort(msg) from e
    except Exception as e:
        raise ProbeAbort(str(e)) from e
    finally:
        conn.set_progress_handler(None, 0)


# ---- PK prune / value-overlap (no gold) ----
VD_JACCARD = 0.9
_PK_CACHE: dict[str, dict[tuple[str, str], str]] = {}
_FK_CACHE: dict[str, dict[tuple[str, str], tuple[str, str]]] = {}
_TABLE_COLS_CACHE: dict[str, dict[str, tuple[str, list[tuple[str, str]]]]] = {}
_TABLE_VALS_CACHE: dict[tuple[str, str], list[str] | None] = {}
_VAL_MENTION_CACHE: dict[tuple[str, str, str, str], bool] = {}
_VAL_CACHE: dict[tuple[str, str, str], frozenset | None] = {}
_CAMEL_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+")
_DATE_YEAR_PARTS = {
    "date", "year", "month", "yearmonth", "datetime", "timestamp", "time",
    "birthday", "dob",
}
_ASKS_IDS = re.compile(
    r"(?i)\b(?:[A-Za-z]+ ){0,3}(?:ids?|identifiers?|primary keys?)\b"
)
_ENTITY = (
    r"patients?|users?|cards?|drivers?|heroes?|superheroes?"
    r"|members?|atoms?|players?"
)
_ASKS_NUMBER_ID = re.compile(
    r"(?i)\b(?:with\s+)?(?:the\s+)?(?:numbers?|no\.?|code|ids?)\s+[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\b"
)
_ASKS_LIST_ENTITY = re.compile(
    rf"(?i)\b(?:list|show|give|find|provide|which|what are|name the)\b.{{0,48}}\b(?:all\s+)?(?:the\s+)?(?:{_ENTITY})\b"
)
_ASKS_HOW_MANY_ENTITY = re.compile(
    rf"(?i)\bhow many\s+(?:{_ENTITY})\b"
)
_SPELL = {
    "colour": ("color", "colours", "colors", "coloured", "colored"),
    "color": ("colour", "colours", "colors", "coloured", "colored"),
    "colours": ("colour", "color", "colors"),
    "colors": ("colour", "color", "colours"),
}
_DROP_NAME_TOKENS = {"id", "pk", "the", "of", "to", "a", "an"}


def _name_parts(name: str) -> list[str]:
    raw = str(name or "").split(".")[-1].replace("-", " ").replace("_", " ")
    parts: list[str] = []
    for tok in raw.split():
        found = _CAMEL_PARTS.findall(tok)
        parts.extend(found if found else [tok])
    return [p for p in parts if p]


def _morphs(tok: str) -> set[str]:
    t = (tok or "").lower()
    if not t:
        return set()
    out = {t}
    if t in _SPELL:
        out.update(_SPELL[t])
    if len(t) >= 3:
        out.add(t + "s")
        out.add(t + "es")
        if t.endswith("y") and len(t) >= 4:
            out.add(t[:-1] + "ies")
        if t.endswith("e"):
            out.add(t + "d")
            out.add(t[:-1] + "ing")
        else:
            out.add(t + "ed")
            if not t.endswith("ing"):
                out.add(t + "ing")
        if t.endswith(("er", "or")) and len(t) >= 5:
            stem = t[:-2]
            out.update({stem, stem + "ed", stem + "ing", t[:-1]})
        if t.endswith("ed") and len(t) >= 5:
            out.add(t[:-2])
            out.add(t[:-1])
        if t.endswith("s") and not t.endswith("ss") and len(t) >= 4:
            out.add(t[:-1])
            if t.endswith("es") and len(t) >= 5:
                out.add(t[:-2])
            if t.endswith("ies") and len(t) >= 6:
                out.add(t[:-3] + "y")
    return {x for x in out if x}


def _in_question(question: str, phrase: str) -> bool:
    pl = (phrase or "").lower().strip()
    if not pl or not question:
        return False
    if len(pl) <= 2:
        return bool(re.search(
            r"(?i)(?:^|[^A-Za-z0-9])" + re.escape(pl) + r"(?:[^A-Za-z0-9]|$)",
            question,
        ))
    return pl in question.lower()


def mention_status(question: str, table: str, col: str) -> str:
    """mentioned / soft_base / table_only / unmentioned / unknown."""
    if not (question or "").strip():
        return "unknown"
    name = str(col or "").split(".")[-1]
    variants = [name, name.replace("_", " ")]
    parts = _name_parts(name)
    if parts:
        variants.append(" ".join(parts))
        variants.append("_".join(parts))
    seen: set[str] = set()
    for v in variants:
        vl = v.lower().strip()
        if not vl or vl in seen:
            continue
        seen.add(vl)
        if _in_question(question, vl):
            return "mentioned"
    for p in parts:
        if len(p) <= 2 or p.lower() in {"id", "pk"}:
            continue
        for m in _morphs(p):
            if len(m) >= 3 and _in_question(question, m):
                return "mentioned"
    base = re.sub(r"(?:_?[Ii][Dd]|_?[Pp][Kk])$", "", name)
    base_sp = base.replace("_", " ").strip()
    if len(base) >= 3 and (
        _in_question(question, base_sp)
        or _in_question(question, base)
        or base.lower().replace("_", "") in question.lower().replace(" ", "").replace("_", "")
    ):
        return "soft_base"
    if table:
        tl = str(table).lower()
        if _in_question(question, tl) or _in_question(question, tl + "s"):
            return "table_only"
        if tl.endswith("s") and len(tl) >= 4 and _in_question(question, tl[:-1]):
            return "table_only"
    return "unmentioned"


def _is_bare_id_name(col: str) -> bool:
    n = str(col or "").split(".")[-1].lower()
    return n in {"id", "pk", "key"} or bool(re.fullmatch(r"id\d*", n))


def _is_date_year_col(col: str) -> bool:
    parts = [p.lower() for p in _name_parts(col)]
    name = str(col or "").split(".")[-1].lower()
    if name in _DATE_YEAR_PARTS:
        return True
    return any(p in _DATE_YEAR_PARTS for p in parts)


def _asks_for_ids(question: str) -> bool:
    """问句在要编号、列出某类实体、或问 How many users/patients 时，跳过主键剪枝。"""
    q = question or ""
    return bool(
        _ASKS_IDS.search(q)
        or _ASKS_NUMBER_ID.search(q)
        or _ASKS_LIST_ENTITY.search(q)
        or _ASKS_HOW_MANY_ENTITY.search(q)
    )


def _prunable_unmentioned(question: str, table: str, col: str) -> bool:
    """True = 问句没点到这个主键列，可以剪。table_only 的裸 id 也可剪。"""
    st = mention_status(question, table, col)
    if st in {"mentioned", "soft_base", "unknown"}:
        return False
    if st == "table_only":
        return _is_bare_id_name(col)
    return True


def _official_pks(db_path: str) -> dict[tuple[str, str], str]:
    """(table_lower, col_lower) -> primary | fk_to_pk。不含仅按名字猜的 extended。"""
    key = str(db_path or "")
    if key in _PK_CACHE:
        return _PK_CACHE[key]
    out: dict[tuple[str, str], str] = {}
    fks_out: dict[tuple[str, str], tuple[str, str]] = {}
    cols_out: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    if not key:
        _PK_CACHE[key] = out
        _FK_CACHE[key] = fks_out
        _TABLE_COLS_CACHE[key] = cols_out
        return out
    try:
        conn = _open_db(key)
    except Exception:
        _PK_CACHE[key] = out
        _FK_CACHE[key] = fks_out
        _TABLE_COLS_CACHE[key] = cols_out
        return out
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for t in tables:
            colinfo: list[tuple[str, str]] = []
            for row in conn.execute(f'PRAGMA table_info({_qident(t)})'):
                colinfo.append((str(row[1]), str(row[2] or "")))
                if row[5]:
                    out[(t.lower(), str(row[1]).lower())] = "primary"
            cols_out[t.lower()] = (t, colinfo)
        for t in tables:
            try:
                fks = list(conn.execute(f'PRAGMA foreign_key_list({_qident(t)})'))
            except Exception:
                fks = []
            for fk in fks:
                frm, dest_t, dest_c = fk[3], fk[2], fk[4]
                if dest_c and (str(dest_t).lower(), str(dest_c).lower()) in out:
                    out.setdefault((t.lower(), str(frm).lower()), "fk_to_pk")
                    fks_out.setdefault(
                        (t.lower(), str(frm).lower()),
                        (str(dest_t), str(dest_c)),
                    )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    _PK_CACHE[key] = out
    _FK_CACHE[key] = fks_out
    _TABLE_COLS_CACHE[key] = cols_out
    return out


def _fk_target(db_path: str, table: str, col: str) -> tuple[str, str] | None:
    _official_pks(db_path)
    return _FK_CACHE.get(str(db_path or ""), {}).get(
        (str(table).lower(), str(col).lower())
    )


def _pk_kind(db_path: str, table: str, col: str) -> str | None:
    return _official_pks(db_path).get((str(table).lower(), str(col).lower()))


def _is_prunable_pk(db_path: str, table: str, col: str, question: str) -> bool:
    if not _pk_kind(db_path, table, col):
        return False
    if _is_date_year_col(col):
        return False
    if not _prunable_unmentioned(question, table, col):
        return False
    if _is_value_mentioned(db_path, table, col, question):
        return False
    return True


def _norm_col_leaf(col: str) -> str:
    return re.sub(
        r"(?:_?[Ii][Dd]|_?[Pp][Kk])$",
        "",
        str(col or "").split(".")[-1],
    ).lower().replace("_", "")


def _content_tokens(col: str) -> set[str]:
    return {
        p.lower()
        for p in _name_parts(col)
        if p and p.lower() not in _DROP_NAME_TOKENS
    }


_VALUE_MENTION_MIN = 4
_VALUE_STOP = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "them", "they", "their",
    "have", "has", "had", "been", "were", "was", "are", "all", "any", "each",
    "every", "both", "also", "into", "than", "then", "when", "what", "which",
    "who", "how", "where", "why", "will", "can", "not", "but", "yes", "no",
    "true", "false", "none", "null", "name", "type", "value", "text", "data",
    "info", "information", "other", "same", "more", "most", "some", "such",
    "only", "just", "very", "many", "much", "about", "after", "before",
    "between", "under", "over", "again", "once", "here", "there", "these",
    "those", "being", "does", "did", "doing", "done", "would", "could",
    "should", "shall", "might", "must", "need", "used", "using", "use",
    "make", "made", "like", "upon", "onto", "within", "without", "your",
    "our", "its", "his", "her", "him", "she", "you", "list", "show", "give",
    "find", "provide", "select", "count", "total", "open", "close", "closed",
    "test", "unknown", "title", "label", "comment", "description", "desc",
})
_NUMERIC_AFFINITY = re.compile(
    r"^(?:INT|INTEGER|TINYINT|SMALLINT|MEDIUMINT|BIGINT|REAL|FLOAT|DOUBLE|"
    r"DOUBLE\s+PRECISION|NUMERIC|DECIMAL|BOOLEAN|BLOB)(?:\s*\(.*\))?$",
    re.I,
)
_AGG_TOKS = {
    "min", "max", "avg", "average", "sum", "count", "mean", "total", "stddev", "std",
}


def _distinctive_value_strings(vals) -> list[str]:
    out: list[str] = []
    for v in vals or []:
        if v is None:
            continue
        s = str(v).strip()
        if len(s) < _VALUE_MENTION_MIN:
            continue
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s):
            continue
        if s.lower() in _VALUE_STOP:
            continue
        out.append(s)
    return out


def _value_in_question(question: str, value: str) -> bool:
    sl = (value or "").strip()
    if not sl or not question:
        return False
    if " " in sl or len(sl) >= 8:
        return sl.lower() in question.lower()
    return bool(re.search(
        r"(?i)(?:^|[^A-Za-z0-9])" + re.escape(sl) + r"(?:s|es)?(?:[^A-Za-z0-9]|$)",
        question,
    ))


def _table_distinctive_values(db_path: str, table: str) -> list[str] | None:
    key = (str(db_path or ""), str(table).lower())
    if key in _TABLE_VALS_CACHE:
        return _TABLE_VALS_CACHE[key]
    _official_pks(db_path)
    entry = _TABLE_COLS_CACHE.get(str(db_path or ""), {}).get(str(table).lower())
    if not entry:
        _TABLE_VALS_CACHE[key] = []
        return []
    actual, colinfo = entry
    found: list[str] = []
    seen: set[str] = set()
    for col, typ in colinfo:
        typ_u = (typ or "").strip()
        if typ_u and _NUMERIC_AFFINITY.match(typ_u):
            continue
        vals = _col_values(db_path, actual, col)
        if vals is None:
            continue
        for s in _distinctive_value_strings(vals):
            sl = s.lower()
            if sl not in seen:
                seen.add(sl)
                found.append(s)
    _TABLE_VALS_CACHE[key] = found
    return found


def _is_value_mentioned(db_path: str, table: str, col: str, question: str) -> bool:
    """问句是否出现该列、或该外键指向维表里的区分性取值。不用源表上的其他列。"""
    q = question or ""
    if not q.strip() or not db_path:
        return False
    cache_key = (str(db_path), str(table).lower(), str(col).lower(), q)
    if cache_key in _VAL_MENTION_CACHE:
        return _VAL_MENTION_CACHE[cache_key]
    hit = False
    vals = _col_values(db_path, table, col)
    if vals is not None:
        for s in _distinctive_value_strings(vals):
            if _value_in_question(q, s):
                hit = True
                break
    if not hit:
        dest = _fk_target(db_path, table, col)
        if dest:
            dvals = _table_distinctive_values(db_path, dest[0])
            for s in dvals or []:
                if _value_in_question(q, s):
                    hit = True
                    break
    _VAL_MENTION_CACHE[cache_key] = hit
    return hit


def _alt_dimension_fks(db_path: str, cands: list) -> bool:
    """候选都是同一张表指向至少两个不同维表的外键（互斥关系，不是同一条 Join 的两端）。"""
    if not db_path or len(cands) < 2:
        return False
    sources: set[str] = set()
    targets: set[str] = set()
    for cd in cands:
        binds = _parse_col_bindings(cd)
        if not binds:
            return False
        for t, c in binds:
            dest = _fk_target(db_path, t, c)
            if not dest:
                return False
            sources.add(str(t).lower())
            targets.add(str(dest[0]).lower())
    return len(sources) == 1 and len(targets) >= 2


def _agg_measure_core(col: str) -> str | None:
    parts = [p.lower() for p in _name_parts(col)]
    if len(parts) < 2:
        return None
    if parts[0] in _AGG_TOKS:
        return "".join(parts[1:])
    if parts[-1] in _AGG_TOKS:
        return "".join(parts[:-1])
    return None


def _is_raw_vs_preagg(col_a: str, col_b: str) -> bool:
    """一边是原列、另一边是 min_/max_/avg_/sum_ 等预聚合列。"""
    a_core = _agg_measure_core(col_a)
    b_core = _agg_measure_core(col_b)
    if bool(a_core) == bool(b_core):
        return False
    core = a_core or b_core or ""
    raw = col_b if a_core else col_a
    raw_n = re.sub(r"[^a-z0-9]", "", str(raw).split(".")[-1].lower())
    if not core or not raw_n:
        return False
    return core == raw_n or core.endswith(raw_n) or raw_n.endswith(core)


def _col_names_similar(col_a: str, col_b: str) -> bool:
    """后缀包含（status / event_status）或词元子集。home_team_goal vs away_team_goal 不会中。"""
    na, nb = _norm_col_leaf(col_a), _norm_col_leaf(col_b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 3 and len(nb) >= 3 and (na.endswith(nb) or nb.endswith(na)):
        return True
    ta, tb = _content_tokens(col_a), _content_tokens(col_b)
    if ta and tb and (ta <= tb or tb <= ta):
        return True
    return False


def _col_values(db_path: str, table: str, col: str) -> frozenset | None:
    key = (str(db_path), str(table), str(col))
    if key in _VAL_CACHE:
        return _VAL_CACHE[key]
    try:
        conn = _open_db(db_path)
        try:
            sql = f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} LIMIT 5001"
            rows = list(_exec_sql(conn, sql, n=5001, timeout_s=8) or [])
        finally:
            conn.close()
    except Exception:
        _VAL_CACHE[key] = None
        return None
    if len(rows) > 5000:
        _VAL_CACHE[key] = None
        return None
    vals = frozenset(r[0] if r else None for r in rows)
    _VAL_CACHE[key] = vals
    return vals


def _jaccard(a: frozenset | None, b: frozenset | None) -> float:
    if a is None or b is None or (not a and not b):
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _schema_tables(schema: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for t, cols in (schema or {}).items():
        if isinstance(cols, dict):
            out[str(t)] = list(cols.keys())
        elif isinstance(cols, (list, tuple)):
            out[str(t)] = [str(c) for c in cols]
        else:
            out[str(t)] = []
    return out


def _resolve_table(schema: dict, table: str) -> str | None:
    tl = str(table).lower()
    for t in (schema or {}):
        if str(t).lower() == tl:
            return t
    return None


def _expand_project_star(cand: Any, schema: dict) -> tuple[Any, bool]:
    """把 Project 里的 T.* / ['*'] 展开成该表全部列。"""
    if not isinstance(cand, dict):
        return cand, False
    tables = _schema_tables(schema)
    out: dict[Any, Any] = {}
    changed = False
    for k, v in cand.items():
        cols_for = None
        is_star = False
        if isinstance(v, str) and v.strip() == "*":
            is_star = True
        elif isinstance(v, list) and any(isinstance(x, str) and x.strip() == "*" for x in v):
            is_star = True
        if is_star and IDENT.match(str(k)):
            rt = _resolve_table(schema, str(k))
            if rt:
                cols_for = list(tables.get(rt) or [])
        if cols_for:
            out[k] = cols_for
            changed = True
        else:
            out[k] = v
    return (out if changed else cand), changed


def _cand_all_prunable_pks(
    cand: Any, db_path: str, question: str
) -> tuple[bool, list[str]]:
    """候选的全部裸列都是可剪主键（无公式）。"""
    if _cand_has_expr(cand):
        return False, []
    binds = _parse_col_bindings(cand)
    if not binds:
        return False, []
    pruned: list[str] = []
    for t, c in binds:
        if not _is_prunable_pk(db_path, t, c, question):
            return False, []
        kind = _pk_kind(db_path, t, c) or "pk"
        pruned.append(f"{t}.{c}({kind})")
    return True, pruned


def _cand_has_expr(cand: Any) -> bool:
    return any(_is_formula_text(s) for s in _walk_strings(cand))


def _strip_project_pks(cand: Any, db_path: str, question: str) -> tuple[Any | None, list[str]]:
    """从 Project 列清单去掉未提及主键；一列不剩则 None。"""
    if not isinstance(cand, dict) or _cand_has_expr(cand):
        return cand, []
    stripped: list[str] = []
    kept_pairs: list[tuple[str, str]] = []
    for t, val in cand.items():
        if not isinstance(val, list):
            binds = _parse_col_bindings({t: val})
            for bt, bc in binds or [(t, str(val))]:
                if _is_prunable_pk(db_path, bt, bc, question):
                    kind = _pk_kind(db_path, bt, bc) or "pk"
                    stripped.append(f"{bt}.{bc}({kind})")
                else:
                    kept_pairs.append((bt, bc))
            continue
        for x in val:
            xs = str(x)
            if IDENT.match(xs):
                bt, bc = t, xs
            elif QUAL.match(xs):
                bt, bc = xs.split(".", 1)
            else:
                kept_pairs.append((t, xs))
                continue
            if _is_prunable_pk(db_path, bt, bc, question):
                kind = _pk_kind(db_path, bt, bc) or "pk"
                stripped.append(f"{bt}.{bc}({kind})")
            else:
                kept_pairs.append((bt, bc))
    if not stripped:
        return cand, []
    rewritten = _rewrite_project_cand(cand, kept_pairs)
    return rewritten, stripped



def _table_name_tokens(table: str) -> set[str]:
    tl = str(table or "").lower()
    out = {tl}
    if tl.endswith("s") and len(tl) >= 4:
        out.add(tl[:-1])
    else:
        if tl:
            out.add(tl + "s")
    for p in _name_parts(table):
        if p:
            out.add(p.lower())
    return {x for x in out if x and x not in {"id", "pk"}}


def _vd_mention_rank(question: str, table: str, col: str, other_table: str) -> int:
    """0=mentioned … 3=unmentioned。列名里仅对应另一张表的词，不算提到了这一列。"""
    st = mention_status(question, table, col)
    other_toks = _table_name_tokens(other_table)
    parts = _name_parts(col)
    other_in_col = any(p.lower() in other_toks for p in parts)
    if st == "mentioned" and other_in_col:
        remain = [
            p for p in parts
            if p.lower() not in other_toks and p.lower() not in {"id", "pk", "key"}
        ]
        mentioned_remain = False
        for p in remain:
            if any(len(m) >= 3 and _in_question(question, m) for m in _morphs(p)):
                mentioned_remain = True
                break
            if _in_question(question, p):
                mentioned_remain = True
                break
        if not mentioned_remain:
            st = mention_status(question, table, "_".join(remain) if remain else "id")
    return {"mentioned": 0, "soft_base": 1, "table_only": 2}.get(st, 3)


def _apply_column_vd(
    cands: list,
    db_path: str,
    question: str,
    notes: list[dict[str, Any]],
    sqls: list[str],
    schema: dict | None = None,
) -> list:
    """跨表、列名相近且 Jaccard > 0.9 时去掉冗余侧；同表同义列和原列/预聚合列不合并。"""
    if len(cands) < 2:
        return cands
    meta: list[tuple[str, str] | None] = []
    for cd in cands:
        binds = _parse_col_bindings(cd)
        if not binds:
            meta.append(None)
            continue
        t, c = binds[0]
        ident = _resolve_ident(schema or {}, t, c) if schema else None
        meta.append(ident if ident else (t, c))
    drop: set[int] = set()
    for i, a in enumerate(meta):
        if a is None or i in drop:
            continue
        for j, b in enumerate(meta):
            if j <= i or b is None or j in drop:
                continue
            ta, ca = a
            tb, cb = b
            # 同表同义列本身就是歧义，只做跨表
            if str(ta).lower() == str(tb).lower():
                continue
            if not _col_names_similar(ca, cb):
                continue
            # 同名跨表列不合并（Team.team_fifa_api_id vs Team_Attributes.team_fifa_api_id）
            if str(ca).split(".")[-1].lower() == str(cb).split(".")[-1].lower():
                continue
            # 原列与预聚合列不合并
            if _is_raw_vs_preagg(ca, cb):
                continue
            va = _col_values(db_path, ta, ca)
            vb = _col_values(db_path, tb, cb)
            jac = _jaccard(va, vb)
            sqls.append(f"VD {ta}.{ca} vs {tb}.{cb} jaccard={jac:.4f}")
            if jac <= VD_JACCARD:
                continue
            # 只在问句提及程度严格更好时去掉一侧；程度相同则两留，不用更长列名打破平局
            ra = _vd_mention_rank(question, ta, ca, tb)
            rb = _vd_mention_rank(question, tb, cb, ta)
            if ra == rb:
                continue
            lose, keep = (j, i) if ra < rb else (i, j)
            drop.add(lose)
            loser = cands[lose]
            notes.append({
                "cand": loser,
                "status": "vd_redundant",
                "keep": cands[keep],
                "pair": [f"{ta}.{ca}", f"{tb}.{cb}"],
                "jaccard": jac,
            })
    if not drop:
        return cands
    return [cd for i, cd in enumerate(cands) if i not in drop]


def _apply_pk_and_vd(
    dec: dict[str, Any],
    *,
    kind: str,
    schema: dict,
    db_path: str,
    question: str,
    original: list,
) -> dict[str, Any]:
    after = list(dec.get("after") if dec.get("after") is not None else original)
    notes = list(dec.get("notes") or [])
    sqls = list(dec.get("sqls") or [])
    if not after:
        return dec
    if not (question or "").strip():
        return dec

    skip_pk = _asks_for_ids(question)
    changed = False

    if kind == "Project":
        before_pk = list(after)
        new: list[Any] = []
        for cd in after:
            exp, did = _expand_project_star(cd, schema)
            if did:
                changed = True
                notes.append({"cand": cd, "status": "star_expanded", "rewritten": exp})
                sqls.append(f"STAR_EXPAND {cd} -> {exp}")
                cd = exp
            if skip_pk:
                new.append(cd)
                continue
            rewritten, stripped = _strip_project_pks(cd, db_path, question)
            if stripped:
                changed = True
                notes.append({
                    "cand": cd,
                    "status": "pk_stripped" if rewritten is not None else "pk_pruned",
                    "pruned": stripped,
                    "rewritten": rewritten,
                })
                sqls.append(f"PK_STRIP {stripped}")
                if rewritten is None:
                    continue
                cd = rewritten
            new.append(cd)
        after = _dedupe_cands(new)
        if not skip_pk and not after and before_pk:
            if _alt_dimension_fks(db_path, before_pk):
                after = list(before_pk)
                notes.append({"status": "pk_kept_alt_fk", "cands": before_pk})
                sqls.append("PK_KEEP_ALT_FK")
            elif _pk_prune_is_cross_table(before_pk):
                after = list(before_pk)
                notes.append({"status": "pk_kept_cross_table", "cands": before_pk})
                sqls.append("PK_KEEP_CROSS_TABLE")
    elif kind in {"Column", "Join", "Aggregate"} and not skip_pk:
        before_pk = list(after)
        flags: list[tuple[Any, bool, list[str]]] = []
        n_non_pk = 0
        for cd in after:
            whole, pruned = _cand_all_prunable_pks(cd, db_path, question)
            flags.append((cd, whole, pruned))
            if not whole:
                n_non_pk += 1
        new = []
        if kind == "Aggregate" and n_non_pk == 0:
            # 两个都是计数键时先不动
            new = list(after)
        else:
            for cd, whole, pruned in flags:
                if whole:
                    changed = True
                    notes.append({"cand": cd, "status": "pk_pruned", "pruned": pruned})
                    sqls.append(f"PK_PRUNE {pruned}")
                    continue
                new.append(cd)
        after = _dedupe_cands(new)
        if kind in {"Column", "Join"} and not after and before_pk:
            if _alt_dimension_fks(db_path, before_pk):
                after = list(before_pk)
                notes.append({"status": "pk_kept_alt_fk", "cands": before_pk})
                sqls.append("PK_KEEP_ALT_FK")
            elif _pk_prune_is_cross_table(before_pk):
                after = list(before_pk)
                notes.append({"status": "pk_kept_cross_table", "cands": before_pk})
                sqls.append("PK_KEEP_CROSS_TABLE")

    if kind == "Column" and len(after) >= 2:
        before_vd = list(after)
        after = _dedupe_cands(_apply_column_vd(after, db_path, question, notes, sqls, schema=schema))
        if after != before_vd:
            changed = True

    if not changed:
        return dec
    out = _decide_drop(original, after, notes, sqls)
    out = _rewrite_unparseable_dedup_auto(out, original)
    out = _rewrite_uncertain_unique_auto(out, original)
    return out


def _canon(x: Any) -> str:
    if isinstance(x, (dict, list)):
        return json.dumps(x, sort_keys=True, ensure_ascii=False)
    return str(x)


def _qident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _like_pat(val: Any) -> str:
    s = str(val).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{s}%"


def _strip_wrapping_quotes(val: Any) -> Any:
    if not isinstance(val, str):
        return val
    s = val.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    return val


def _parse_value_cand(cand: Any) -> tuple[str, str, Any] | None:
    if isinstance(cand, dict):
        if len(cand) != 1:
            return None
        k, v = next(iter(cand.items()))
        if isinstance(v, list):
            return None
        key = str(k)
        if "." not in key:
            return None
        t, c = key.split(".", 1)
        return t, c, _strip_wrapping_quotes(v)
    if isinstance(cand, str):
        m = re.match(r"""^\s*([\w]+)\.([\w]+)\s*=\s*(.*?)\s*$""", cand)
        if m:
            return m.group(1), m.group(2), _strip_wrapping_quotes(m.group(3))
    return None


def _ground_value(cand: Any, table: str, col: str, lit: Any) -> Any:
    if isinstance(cand, dict) and len(cand) == 1:
        return {f"{table}.{col}": lit}
    if isinstance(cand, str):
        return f"{table}.{col} = '{str(lit).replace(chr(39), chr(39)+chr(39))}'"
    return lit


def _n_distinct(conn: Any, table: str, col: str) -> int | None:
    rows = _exec_sql(
        conn,
        f"SELECT COUNT(DISTINCT {_qident(col)}) FROM {_qident(table)}",
        timeout_s=8,
    )
    if not rows:
        return None
    try:
        return int(rows[0][0])
    except (TypeError, ValueError):
        return None


def _probe_exact(conn: Any, table: str, col: str, val: Any) -> list[Any]:
    sql = f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} WHERE {_qident(col)} = ? LIMIT 5"
    return [r[0] for r in _exec_sql(conn, sql, (val,)) if r]


def _probe_nocase(conn: Any, table: str, col: str, val: Any) -> list[Any]:
    sql = (
        f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} "
        f"WHERE {_qident(col)} = ? COLLATE NOCASE LIMIT 5"
    )
    return [r[0] for r in _exec_sql(conn, sql, (str(val),)) if r]


def _probe_like(conn: Any, table: str, col: str, val: Any) -> list[Any]:
    sql = (
        f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} "
        f"WHERE CAST({_qident(col)} AS TEXT) LIKE ? ESCAPE '\\' LIMIT 5"
    )
    return [r[0] for r in _exec_sql(conn, sql, (_like_pat(val),), timeout_s=15) if r]


def _is_numeric_literal(val: Any) -> bool:
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False


def _numeric_equiv(a: Any, b: Any) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _same_value_literal(cand_val: Any, db_val: Any) -> bool:
    """仅大小写 / 首尾空白 / 包裹引号不同，才视为同一字面量。"""
    if _is_numeric_literal(cand_val) and _is_numeric_literal(db_val):
        return _numeric_equiv(cand_val, db_val)

    def norm(x: Any) -> str:
        s = str(x).strip()
        s = _strip_wrapping_quotes(s) if isinstance(s, str) else s
        return str(s).strip().casefold()

    return norm(cand_val) == norm(db_val)



_BARE_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")
_BARE_YYYYMM_RE = re.compile(r"^(?:19|20)\d{2}(?:0[1-9]|1[0-2])$")
_BARE_MEASURE_RE = re.compile(
    r"(consumption|amount|count|sum_|avg_|total|goal|price|cost|qty|quantity|"
    r"score|points|rating|salary|wage|revenue|profit|balance|population|"
    r"height|weight|duration|age$)",
    re.I,
)
_BARE_DATECOL_RE = re.compile(r"(date|time|year|month|season|day|birthday|timestamp|dob)", re.I)
_BARE_OP_RE = re.compile(r"^\s*(?:<=|>=|!=|<>|<|>|=)")
_BARE_ALNUM_RE = re.compile(r"[^0-9a-zA-Z]+")


def _parse_bare_value(cand: Any) -> tuple[str, Any] | None:
    """{table: value} or {col: value} — key has no '.' and value is not a list."""
    if isinstance(cand, dict) and len(cand) == 1:
        k, v = next(iter(cand.items()))
        if isinstance(v, list):
            return None
        if "." not in str(k):
            return str(k), _strip_wrapping_quotes(v)
    return None


def _bare_is_operator_or_formula(val: Any) -> bool:
    """Skip scan for comparison-operator values like '>= 14' or longer formulas.

    Short tokens such as '+' / '-' are still scanned and listed.
    """
    if val is None:
        return True
    s = str(val).strip()
    if not s:
        return True
    if _BARE_OP_RE.match(s):
        return True
    if len(s) > 2 and _is_formula_text(s):
        return True
    return False


def _bare_alnum(s: Any) -> str:
    return _BARE_ALNUM_RE.sub("", str(s or "")).casefold()


def _bare_is_yearish(val: Any) -> bool:
    s = str(val).strip()
    return bool(
        _BARE_YEAR_RE.fullmatch(s)
        or _BARE_YYYYMM_RE.fullmatch(s)
        or re.fullmatch(r"(?:19|20)\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?", s)
    )


def _bare_is_date_col(col: str, typ: str) -> bool:
    if _BARE_DATECOL_RE.search(col or ""):
        return True
    typ = typ or ""
    return "DATE" in typ or "TIME" in typ


def _bare_is_measure_col(col: str, typ: str) -> bool:
    if _BARE_MEASURE_RE.search(col or ""):
        return True
    typ = typ or ""
    if _BARE_DATECOL_RE.search(col or ""):
        return False
    if any(x in typ for x in ("INT", "REAL", "FLOA", "DOUB", "NUM")) and "CHAR" not in typ and "TEXT" not in typ:
        return True
    return False


def _bare_is_safe_auto(val: Any, col: str, typ: str) -> bool:
    if _bare_is_yearish(val) and not _bare_is_date_col(col, typ):
        return False
    if _is_numeric_literal(val) and _bare_is_measure_col(col, typ) and not _bare_is_date_col(col, typ):
        return False
    return True


def _ident_lookup_schema(schema: dict[str, dict[str, str]], name: str) -> tuple[str, list[str], list[tuple[str, str, str]]]:
    lname = (name or "").casefold()
    tables, cols = [], []
    for t, cmap in (schema or {}).items():
        if t.casefold() == lname:
            tables.append(t)
        for col, typ in cmap.items():
            if col.casefold() == lname:
                cols.append((t, col, typ))
    if tables and cols:
        return "both", tables, cols
    if tables:
        return "table", tables, cols
    if cols:
        return "col", tables, cols
    return "none", tables, cols


def _probe_prefix(conn: Any, table: str, col: str, prefix: str) -> list[Any]:
    pat = str(prefix).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = _exec_sql(
        conn,
        f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} "
        f"WHERE CAST({_qident(col)} AS TEXT) LIKE ? ESCAPE '\\' LIMIT 20",
        (pat,),
        timeout_s=15,
    )
    return [r[0] for r in rows if r] if rows else []


def _unique_alnum_hit(conn: Any, table: str, col: str, val: Any, cap: int = 400) -> list[Any]:
    key = _bare_alnum(val)
    if not key:
        return []
    nd = _n_distinct(conn, table, col)
    if nd is None or nd > cap:
        return []
    rows = _exec_sql(
        conn,
        f"SELECT DISTINCT {_qident(col)} FROM {_qident(table)} LIMIT {cap}",
        timeout_s=15,
    )
    if not rows:
        return []
    hits = [r[0] for r in rows if r and r[0] is not None and _bare_alnum(r[0]) == key]
    uniq, seen = [], set()
    for h in hits:
        k = str(h).casefold()
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq


def _collect_bare_hits(conn: Any, schema: dict[str, dict[str, str]], table_names: list[str], val: Any) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def add(t: str, c: str, typ: str, dbv: Any, mode: str) -> None:
        key = (t.casefold(), c.casefold(), str(dbv).casefold(), mode)
        if key in seen:
            return
        seen.add(key)
        hits.append({
            "table": t, "col": c, "typ": typ, "db_val": dbv, "mode": mode,
            "safe": _bare_is_safe_auto(val, c, typ),
        })

    is_word = isinstance(val, str) and not _is_numeric_literal(val)
    col_pairs: list[tuple[str, str, str]] = []
    for t in table_names:
        for col, typ in (schema.get(t) or {}).items():
            typ = typ or ""
            if is_word and _bare_is_measure_col(col, typ) and not _bare_is_date_col(col, typ) and any(
                x in typ for x in ("INT", "REAL", "FLOA", "DOUB", "NUM")
            ) and "TEXT" not in typ and "CHAR" not in typ:
                continue
            col_pairs.append((t, col, typ))

    for t, c, typ in col_pairs:
        exact = _probe_exact(conn, t, c, val)
        if exact:
            for v in exact:
                add(t, c, typ, v, "exact")
            continue
        nocase = _probe_nocase(conn, t, c, val)
        if nocase:
            for v in nocase:
                add(t, c, typ, v, "nocase")
            continue
        al = _unique_alnum_hit(conn, t, c, val)
        if len(al) == 1:
            add(t, c, typ, al[0], "alnum")

    year = None
    s = str(val).strip()
    if _BARE_YEAR_RE.fullmatch(s):
        year = s
    elif _BARE_YYYYMM_RE.fullmatch(s):
        year = s[:4]
    else:
        m = re.fullmatch(r"((?:19|20)\d{2})[-/.]\d{1,2}(?:[-/.]\d{1,2})?", s)
        if m:
            year = m.group(1)
    if year:
        for t, c, typ in col_pairs:
            if not _bare_is_date_col(c, typ):
                continue
            if _probe_prefix(conn, t, c, year):
                add(t, c, typ, f"YEAR:{year}", "year_prefix")
    return hits


def _prefer_year_readings(hits: list[dict[str, Any]], val: Any) -> list[dict[str, Any]]:
    """Yearish literals stay a year reading on date columns, not a single YYYYMM month.

    If a safe date year_prefix exists, also drop unsafe exact/nocase/alnum hits
    on other (measure/id) columns so a lone date reading can AutoResolve.
    Two safe date columns still list.
    """
    if not _bare_is_yearish(val):
        return hits
    year_cols = {(h["table"].casefold(), h["col"].casefold()) for h in hits if h["mode"] == "year_prefix"}
    if not year_cols:
        return hits
    has_safe_year = any(h["mode"] == "year_prefix" and h.get("safe") for h in hits)
    out = []
    for h in hits:
        key = (h["table"].casefold(), h["col"].casefold())
        if h["mode"] in {"exact", "nocase", "alnum"} and key in year_cols:
            continue
        if (
            has_safe_year
            and h["mode"] in {"exact", "nocase", "alnum"}
            and not h.get("safe")
            and key not in year_cols
        ):
            continue
        out.append(h)
    return out


def _decide_bare_hits(hits: list[dict[str, Any]]) -> str:
    cols = {(h["table"].casefold(), h["col"].casefold()) for h in hits}
    if not hits:
        return "miss"
    if len(cols) == 1:
        only = next(iter(cols))
        if all(h["safe"] for h in hits if (h["table"].casefold(), h["col"].casefold()) == only):
            return "auto"
        return "list"
    return "list"


def _hit_to_cand(orig: Any, hit: dict[str, Any]) -> Any:
    t, c, dbv, mode = hit["table"], hit["col"], hit["db_val"], hit["mode"]
    if mode == "year_prefix":
        year = str(dbv).split(":", 1)[-1]
        if isinstance(orig, dict) and len(orig) == 1:
            return {f"{t}.{c}": f"{year}%"}
        return f"{t}.{c} LIKE '{year}%'"
    return _ground_value(orig, t, c, dbv)


def _ground_bare_value(
    cand: Any, schema: dict[str, dict[str, str]], conn: Any
) -> tuple[list[Any] | None, list[dict[str, Any]], list[str]]:
    """Return (new_cands or None to keep original, notes, sqls)."""
    bare = _parse_bare_value(cand)
    if bare is None or _bare_is_operator_or_formula(bare[1]):
        return None, [{"cand": cand, "status": "unparseable_keep"}], []
    key, val = bare
    kind, tables, cols = _ident_lookup_schema(schema, key)
    sqls: list[str] = []
    if kind in {"table", "both"}:
        hits = _collect_bare_hits(conn, schema, tables, val)
    elif kind == "col":
        tset = list({t for t, _c, _typ in cols})
        allow = {(t.casefold(), c.casefold()) for t, c, _typ in cols}
        hits = [h for h in _collect_bare_hits(conn, schema, tset, val) if (h["table"].casefold(), h["col"].casefold()) in allow]
    else:
        hits = []
    hits = _prefer_year_readings(hits, val)
    sqls.append(f"BARE {key}={val!r} kind={kind} n_hits={len(hits)}")
    if not hits:
        return None, [{"cand": cand, "status": "unparseable_keep", "bare_key": key, "literal": val}], sqls
    dec = _decide_bare_hits(hits)
    # one cand per (table,col); year_prefix already preferred
    by_col: dict[tuple[str, str], dict[str, Any]] = {}
    for h in hits:
        by_col[(h["table"].casefold(), h["col"].casefold())] = h
    formal = [_hit_to_cand(cand, h) for h in by_col.values()]
    note = {
        "cand": cand,
        "status": "bare_ground_auto" if dec == "auto" else "bare_ground_list",
        "bare_key": key,
        "literal": val,
        "decision": dec,
        "hits": [
            f"{h['table']}.{h['col']}={h['db_val']!s}[{h['mode']},safe={h['safe']}]"
            for h in hits
        ],
    }
    return formal, [note], sqls



_TIME_LITERAL = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?$")
_YMD_LEAD = re.compile(r"^((?:19|20)\d{2})[-/.](\d{1,2})[-/.](\d{1,2})$")
_YM_LEAD = re.compile(r"^((?:19|20)\d{2})[-/.](\d{1,2})$")
_DMY_OR_MDY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.]((?:19|20)\d{2})$")


def _parse_temporal_keys(val: Any) -> list[tuple]:
    """Comparable date/time/yearmonth keys. Ambiguous D/M vs M/D yields both."""
    if val is None or isinstance(val, bool):
        return []
    s = str(val).strip()
    if not s:
        return []
    m = _TIME_LITERAL.fullmatch(s)
    if m:
        return [("t", int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))]
    if _BARE_YYYYMM_RE.fullmatch(s):
        return [("ym", int(s[:4]), int(s[4:6]))]
    m = _YM_LEAD.fullmatch(s)
    if m:
        month = int(m.group(2))
        return [("ym", int(m.group(1)), month)] if 1 <= month <= 12 else []
    m = _YMD_LEAD.fullmatch(s)
    if m:
        y, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [("d", y, month, day)] if 1 <= month <= 12 and 1 <= day <= 31 else []
    if re.fullmatch(r"\d{8}", s) and s[:2] in {"19", "20"}:
        y, month, day = int(s[:4]), int(s[4:6]), int(s[6:8])
        return [("d", y, month, day)] if 1 <= month <= 12 and 1 <= day <= 31 else []
    m = _DMY_OR_MDY.fullmatch(s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        keys: list[tuple] = []
        if 1 <= a <= 12 and 1 <= b <= 31:
            keys.append(("d", y, a, b))
        if 1 <= b <= 12 and 1 <= a <= 31:
            keys.append(("d", y, b, a))
        out, seen = [], set()
        for k in keys:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out
    return []


def _norm_hit_set(hits: Any) -> frozenset | None:
    if not hits:
        return None
    out: set[tuple] = set()
    for h in hits:
        if h is None:
            continue
        if _is_numeric_literal(h):
            try:
                out.add(("n", float(h)))
            except (TypeError, ValueError):
                out.add(("s", str(h).strip().casefold()))
        else:
            out.add(("s", str(h).strip().casefold()))
    return frozenset(out) if out else None


def _note_binding(note: dict[str, Any]) -> tuple[str, str, Any] | None:
    return _parse_value_cand((note or {}).get("cand"))


def _note_literal(note: dict[str, Any]) -> Any:
    if note.get("literal") is not None:
        return note.get("literal")
    parsed = _note_binding(note)
    return parsed[2] if parsed else None


def _valids_for_note(note: dict[str, Any], valid: list) -> list:
    """Locate this note's own cand in `valid`. Do not also take numeric synonyms."""
    cand = (note or {}).get("cand")
    nc = _canon(cand)
    parsed = _parse_value_cand(cand)
    matched = []
    for v in valid:
        if _canon(v) == nc:
            matched.append(v)
            continue
        pv = _parse_value_cand(v)
        if not parsed or not pv:
            continue
        if parsed[0].casefold() != pv[0].casefold() or parsed[1].casefold() != pv[1].casefold():
            continue
        a = str(_strip_wrapping_quotes(parsed[2])).strip()
        b = str(_strip_wrapping_quotes(pv[2])).strip()
        if a == b or a.casefold() == b.casefold():
            matched.append(v)
    return matched


def _collapse_equivalent_value_cands(
    valid: list, notes: list, sqls: list[str]
) -> tuple[list, list, list[str]]:
    """Drop same-column numeric synonyms and same-day date format aliases."""
    drop: set[str] = set()
    kept_examples: list[str] = []

    exact_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for note in notes or []:
        if str(note.get("status") or "") != "exact":
            continue
        parsed = _note_binding(note)
        hit_key = _norm_hit_set(note.get("hits"))
        if parsed is None or hit_key is None:
            continue
        exact_groups.setdefault((parsed[0].casefold(), parsed[1].casefold()), []).append(note)

    for col, group in exact_groups.items():
        clusters: dict[frozenset, list[dict[str, Any]]] = {}
        for note in group:
            clusters.setdefault(_norm_hit_set(note.get("hits")), []).append(note)
        for _key, cluster in clusters.items():
            if len(cluster) < 2:
                continue
            kept_examples.append(f"numeric:{col}->{cluster[0].get('literal')!r} x{len(cluster)}")
            for note in cluster[1:]:
                drop.add(_canon(note.get("cand")))

    col_notes: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for note in notes or []:
        parsed = _note_binding(note)
        if parsed is None:
            continue
        col_notes.setdefault((parsed[0].casefold(), parsed[1].casefold()), []).append(note)

    for col, group in col_notes.items():
        exact_keys: list[tuple] = []
        for note in group:
            if str(note.get("status") or "") != "exact":
                continue
            lit = _note_literal(note)
            for src in list(note.get("hits") or [])[:1] + [lit]:
                exact_keys.extend(_parse_temporal_keys(src))
        exact_set = set(exact_keys)
        if not exact_set:
            continue
        for note in group:
            if str(note.get("status") or "") not in {"date_or_pattern_keep", "empty_free_text_keep"}:
                continue
            alias_keys = _parse_temporal_keys(_note_literal(note))
            if not alias_keys:
                continue
            if any(k in exact_set for k in alias_keys):
                drop.add(_canon(note.get("cand")))
                kept_examples.append(f"date:{col}->{_note_literal(note)!r}")

    if not drop:
        return valid, notes, sqls

    drop_valids: set[str] = set()
    for note in notes or []:
        if _canon((note or {}).get("cand")) in drop:
            for v in _valids_for_note(note, valid):
                drop_valids.add(_canon(v))

    new_valid = [v for v in valid if _canon(v) not in drop_valids]
    if not new_valid or len(new_valid) == len(valid):
        return valid, notes, sqls

    notes = list(notes or []) + [{
        "status": "equiv_value_collapsed",
        "dropped": sorted(drop),
        "n_before": len(valid),
        "n_after": len(new_valid),
    }]
    sqls = list(sqls or []) + [f"COLLAPSE equiv {'; '.join(kept_examples)} {len(valid)}->{len(new_valid)}"]
    return new_valid, notes, sqls


def _handle_value(cands: list, schema: dict, conn: Any) -> dict[str, Any]:
    """Value 存在性：逻辑在本文件。"""
    sqls: list[str] = []
    valid: list[Any] = []
    notes: list[dict[str, Any]] = []
    for cand in cands:
        parsed = _parse_value_cand(cand)
        if parsed is None:
            formal, bare_notes, bare_sqls = _ground_bare_value(cand, schema, conn)
            notes.extend(bare_notes)
            sqls.extend(bare_sqls)
            if formal is None:
                valid.append(cand)
            else:
                valid.extend(formal)
            continue
        table, col, val = parsed
        ident = _resolve_ident(schema, table, col)
        if ident is None:
            notes.append({"cand": cand, "status": "schema_missing"})
            continue
        t, c = ident
        hits = _probe_exact(conn, t, c, val)
        sqls.append(f"EXACT {t}.{c}={val!r} -> {hits}")
        if hits:
            out_cand = cand
            if isinstance(cand, dict) and len(cand) == 1:
                _k, _v = next(iter(cand.items()))
                if isinstance(_v, str) and _strip_wrapping_quotes(_v) != _v:
                    out_cand = _ground_value(cand, t, c, hits[0])
            valid.append(out_cand)
            notes.append({"cand": cand, "status": "exact", "hits": hits, "literal": val})
            continue
        nocase = _probe_nocase(conn, t, c, val)
        sqls.append(f"NOCASE {t}.{c}={val!r} -> {nocase}")
        if len(nocase) == 1:
            if _is_numeric_literal(val) and not _numeric_equiv(val, nocase[0]):
                notes.append({
                    "cand": cand, "status": "numeric_nocase_mismatch",
                    "literal": val, "db_literal": nocase[0],
                })
            else:
                grounded = _ground_value(cand, t, c, nocase[0])
                valid.append(grounded)
                notes.append({"cand": cand, "status": "ground_nocase", "db_literal": nocase[0]})
                continue
        elif len(nocase) > 1:
            valid.append(cand)
            notes.append({"cand": cand, "status": "nocase_ambiguous", "hits": nocase})
            continue
        if _is_numeric_literal(val):
            valid.append(cand)
            notes.append({
                "cand": cand, "status": "numeric_miss_keep",
                "literal": val, "reason": "no_like_no_enum_drop",
            })
            continue
        if _is_sql_wildcard_literal(val):
            pattern_hits = _exec_sql(
                conn,
                f"SELECT DISTINCT {_qident(c)} FROM {_qident(t)} "
                f"WHERE CAST({_qident(c)} AS TEXT) LIKE ? LIMIT 5",
                (str(val),),
                timeout_s=15,
            )
            hits = [r[0] for r in pattern_hits if r] if pattern_hits else []
            sqls.append(f"PATTERN {t}.{c}~{val!r} -> {hits}")
            valid.append(cand)
            notes.append({
                "cand": cand,
                "status": "pattern_hit" if hits else "date_or_pattern_keep",
                "hits": hits,
                "literal": val,
            })
            continue
        fuzzy = _probe_like(conn, t, c, val)
        sqls.append(f"LIKE {t}.{c}~{val!r} -> {fuzzy}")
        if len(fuzzy) == 1:
            if _same_value_literal(val, fuzzy[0]):
                grounded = _ground_value(cand, t, c, fuzzy[0])
                valid.append(grounded)
                notes.append({"cand": cand, "status": "ground_like", "db_literal": fuzzy[0]})
                continue
            valid.append(cand)
            notes.append({
                "cand": cand, "status": "like_rewrite_blocked",
                "literal": val, "db_literal": fuzzy[0],
            })
            continue
        if len(fuzzy) > 1:
            valid.append(cand)
            notes.append({"cand": cand, "status": "like_ambiguous", "hits": fuzzy})
            continue
        nd = _n_distinct(conn, t, c)
        sqls.append(f"N_DISTINCT {t}.{c}={nd}")
        if _is_date_like_literal(val):
            valid.append(cand)
            notes.append({
                "cand": cand, "status": "date_or_pattern_keep",
                "literal": val, "n_distinct": nd,
            })
            continue
        if nd is not None and nd <= ENUM_N_DISTINCT:
            notes.append({"cand": cand, "status": "enum_absent", "n_distinct": nd})
            continue
        valid.append(cand)
        notes.append({"cand": cand, "status": "empty_free_text_keep", "n_distinct": nd})

    uniq: list[Any] = []
    seen: set[str] = set()
    for c in valid:
        k = _canon(c)
        if k not in seen:
            uniq.append(c)
            seen.add(k)
    uniq, notes, sqls = _collapse_equivalent_value_cands(uniq, notes, sqls)
    return _decide_drop(cands, uniq, notes, sqls)



def resolve_span_type(span: str, span_types: dict[str, str] | None) -> str:
    """先查 span_types；缺失时才用 phi key 自带的 \n[Type] 后缀。不回退到去后缀的别的类型。"""
    typ = str((span_types or {}).get(span) or "")
    if typ:
        return typ
    m = SPAN_TYPE_SUFFIX.search(str(span or ""))
    return m.group(1) if m else ""


def _parse_col_bindings(cand: Any) -> list[tuple[str, str]]:
    """抽出 table.col；公式等解析失败则返回空（调用方 keep）。"""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(table: str, col: str) -> None:
        table, col = str(table), str(col)
        if not table or not col:
            return
        if _is_formula_text(col) or any(ch in col for ch in " \t"):
            return
        key = (table, col)
        if key not in seen:
            seen.add(key)
            out.append(key)

    def add_qual(tok: str) -> None:
        tok = tok.strip().strip("'\"")
        m = QUAL.match(tok)
        if m:
            add(m.group(1), m.group(2))
            return
        if "." in tok:
            table, col = tok.split(".", 1)
            table, col = table.strip(), col.strip().strip("'\"")
            if table and col and "/" not in col and "*" not in col and "(" not in col:
                add(table, col)

    if isinstance(cand, dict):
        for k, v in cand.items():
            add_qual(str(k))
            if isinstance(v, str):
                # skip formula-like values
                if "(" in v or "/" in v or "*" in v:
                    continue
                add_qual(v)
            elif isinstance(v, list):
                if IDENT.match(str(k)) and v and all(
                    isinstance(x, str) and IDENT.match(x) for x in v
                ):
                    for col in v:
                        add(str(k), col)
                else:
                    for x in v:
                        if isinstance(x, str) and "(" not in x and "/" not in x:
                            add_qual(x)
        return out

    if isinstance(cand, str):
        if "(" in cand or "/" in cand:
            return out
        m = QUAL.match(cand.strip())
        if m:
            add(m.group(1), m.group(2))
            return out
        for tok in cand.replace("=", " ").replace(",", " ").split():
            if "." in tok:
                add_qual(tok)
    return out


def _decide_drop(original: list, valid: list, notes: list, sqls: list[str]) -> dict[str, Any]:
    """zero → DropCard（after=[]），不恢复原候选。"""
    if not valid:
        return {
            "action": "DropCard",
            "after": [],
            "healed": None,
            "notes": notes,
            "sqls": sqls,
            "reason": "zero_valid_drop",
        }
    if len(valid) == 1 and len(original) > 1:
        return {
            "action": "AutoResolve",
            "after": list(valid),
            "healed": valid[0],
            "notes": notes,
            "sqls": sqls,
            "reason": "unique_physical",
        }
    grounded = any(str(n.get("status", "")).startswith("ground_") for n in notes)
    pruned = any(
        n.get("status") in {
            "schema_missing", "enum_absent", "schema_partial",
            "pk_pruned", "pk_stripped", "vd_redundant", "star_expanded",
        }
        for n in notes
    )
    partial = any(n.get("status") == "schema_partial" for n in notes)
    action = "RetainForHuman"
    if grounded:
        action = "Ground"
    elif pruned and (len(valid) < len(original) or partial):
        action = "Prune"
    return {
        "action": action,
        "after": list(valid),
        "healed": valid[0] if len(valid) == 1 else None,
        "notes": notes,
        "sqls": sqls,
        "reason": "retain_or_mutate",
    }


def _rewrite_unparseable_dedup_auto(dec: dict[str, Any], original: list) -> dict[str, Any]:
    """缺列/{table:value} 等 unparseable 仅靠去重变 1 → 不算 AutoResolve 增益。"""
    if dec.get("action") != "AutoResolve":
        return dec
    notes = list(dec.get("notes") or [])
    if not notes:
        return dec
    statuses = [str(n.get("status") or "") for n in notes]
    # 全部是 unparseable_keep，且 after 变短只因去重
    if all(s == "unparseable_keep" for s in statuses):
        after = list(dec.get("after") or [])
        if len(after) == 1 and len(original) > 1:
            return {
                **dec,
                "action": "RetainForHuman",
                "healed": None,
                "reason": "unparseable_dedup_not_auto",
            }
    return dec


def _rewrite_uncertain_unique_auto(dec: dict[str, Any], original: list) -> dict[str, Any]:
    """因主键剪枝或公式未解析才剩下一条时，不做 AutoResolve，把不确定候选放回。"""
    if dec.get("action") != "AutoResolve":
        return dec
    after = list(dec.get("after") or [])
    notes = list(dec.get("notes") or [])
    after_keys = {_canon(c) for c in after}
    soft_removed: list[Any] = []
    for note in notes:
        if note.get("status") != "pk_pruned":
            continue
        cand = note.get("cand")
        if cand is not None and _canon(cand) not in after_keys:
            soft_removed.append(cand)
    unparseable_keys = {
        _canon(note["cand"])
        for note in notes
        if note.get("status") == "unparseable_keep" and "cand" in note
    }
    resolved_to_formula = bool(after) and all(_canon(c) in unparseable_keys for c in after)
    if not soft_removed and not resolved_to_formula:
        return dec
    if resolved_to_formula:
        restored = list(original)
    else:
        restored = _dedupe_cands(after + soft_removed)
        if len(restored) <= 1 and len(original) > 1:
            restored = list(original)
    hard_removed = any(
        note.get("status") in {"schema_missing", "enum_absent"} for note in notes
    )
    action = "Prune" if hard_removed and len(restored) < len(original) else "RetainForHuman"
    return {
        **dec,
        "action": action,
        "after": restored,
        "healed": None,
        "reason": "uncertain_unique_not_auto",
    }


def _rewrite_zero_to_drop(dec: dict[str, Any], original: list) -> dict[str, Any]:
    """把 zero_valid_fallback 改成 DropCard。"""
    if dec.get("reason") == "zero_valid_fallback" or (
        dec.get("action") == "RetainForHuman"
        and list(dec.get("after") or []) == list(original)
        and any(n.get("status") in {"schema_missing", "enum_absent"} for n in (dec.get("notes") or []))
        and not any(
            n.get("status") not in {"schema_missing", "enum_absent"}
            for n in (dec.get("notes") or [])
        )
    ):
        # 仅当全部候选都被剪掉时才 drop；若 reason 明确是 fallback 也 drop
        if dec.get("reason") == "zero_valid_fallback":
            return {
                **dec,
                "action": "DropCard",
                "after": [],
                "healed": None,
                "reason": "zero_valid_drop",
            }
    return dec


def _rewrite_project_cand(cand: Any, kept: list[tuple[str, str]]) -> Any | None:
    """按 kept 的 (table,col) 重写多列 Project 候选；一列不剩则 None。"""
    kept_l = {(t.lower(), c.lower()) for t, c in kept}
    if isinstance(cand, dict):
        out: dict[Any, Any] = {}
        for k, v in cand.items():
            if (
                isinstance(v, list)
                and IDENT.match(str(k))
                and v
                and all(isinstance(x, str) and IDENT.match(x) for x in v)
            ):
                new_cols = [
                    x for x in v
                    if (str(k).lower(), str(x).lower()) in kept_l
                ]
                if new_cols:
                    out[k] = new_cols
            else:
                # 非「表→列列表」：若该键对应绑定仍在 kept 则原样保留
                m = QUAL.match(str(k).strip().strip("'\""))
                if m and (m.group(1).lower(), m.group(2).lower()) in kept_l:
                    out[k] = v
                elif any(str(k).lower() == t for t, _ in kept_l):
                    out[k] = v
        return out if out else None
    return cand if kept else None


def _dedupe_cands(cands: list) -> list:
    uniq, seen = [], set()
    for c in cands:
        k = json.dumps(c, sort_keys=True, ensure_ascii=False) if isinstance(c, (dict, list)) else str(c)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def _is_empty_project_cand(cand: Any) -> bool:
    """{Table: []} / {} / []：解析得出零列，不是合法 Project 候选。"""
    if cand is None or cand == {} or cand == []:
        return True
    if isinstance(cand, dict) and cand and all(
        isinstance(v, list) and len(v) == 0 for v in cand.values()
    ):
        return True
    return False


def _handle_project(cands: list, schema: dict) -> dict[str, Any]:
    """Project：只剔坏列；改写后仍 ≥1 列则 keep；全空才丢候选。"""
    valid, notes, sqls = [], [], []
    for cand in cands:
        if _is_empty_project_cand(cand):
            notes.append({"cand": cand, "status": "empty_project"})
            continue
        if _cand_has_expr(cand) and not _parse_col_bindings(cand):
            valid.append(cand)
            notes.append({"cand": cand, "status": "unparseable_keep"})
            continue
        bindings = _parse_col_bindings(cand)
        if not bindings:
            valid.append(cand)
            notes.append({"cand": cand, "status": "unparseable_keep"})
            continue
        missing: list[str] = []
        kept: list[tuple[str, str]] = []
        resolved: list[tuple[str, str]] = []
        for table, col in bindings:
            ident = _resolve_ident(schema, table, col)
            if ident is None:
                missing.append(f"{table}.{col}")
            else:
                kept.append((table, col))
                resolved.append(ident)
        if not kept:
            sqls.append(f"Project_COLS {bindings} missing={missing}")
            notes.append({
                "cand": cand,
                "status": "schema_missing",
                "missing": missing,
                "bindings": bindings,
            })
            continue
        if missing:
            rewritten = _rewrite_project_cand(cand, kept)
            if rewritten is None:
                sqls.append(f"Project_COLS {bindings} missing={missing} kept_empty")
                notes.append({
                    "cand": cand,
                    "status": "schema_missing",
                    "missing": missing,
                    "bindings": bindings,
                })
                continue
            sqls.append(f"Project_COLS {bindings} missing={missing} kept={kept}")
            valid.append(rewritten)
            notes.append({
                "cand": cand,
                "status": "schema_partial",
                "missing": missing,
                "kept": [{"table": t, "col": c} for t, c in kept],
                "rewritten": rewritten,
                "bindings": bindings,
            })
        else:
            sqls.append(f"Project_COLS {bindings} ok")
            valid.append(cand)
            notes.append({
                "cand": cand,
                "status": "bindings_ok",
                "bindings": bindings,
                "resolved": [{"table": t, "col": c} for t, c in resolved],
            })
    return _decide_drop(cands, _dedupe_cands(valid), notes, sqls)


def _handle_schema(cands: list, schema: dict, *, kind: str) -> dict[str, Any]:
    if kind == "Project":
        return _handle_project(cands, schema)
    valid, notes, sqls = [], [], []
    for cand in cands:
        bindings = _parse_col_bindings(cand)
        if not bindings:
            valid.append(cand)
            notes.append({"cand": cand, "status": "unparseable_keep"})
            continue
        missing: list[str] = []
        resolved: list[tuple[str, str]] = []
        for table, col in bindings:
            ident = _resolve_ident(schema, table, col)
            if ident is None:
                missing.append(f"{table}.{col}")
            else:
                resolved.append(ident)
        if missing:
            if _cand_has_expr(cand):
                sqls.append(f"{kind}_COLS formula missing={missing} keep")
                valid.append(cand)
                notes.append({
                    "cand": cand,
                    "status": "unparseable_keep",
                    "missing": missing,
                    "bindings": bindings,
                })
                continue
            sqls.append(f"{kind}_COLS {bindings} missing={missing}")
            notes.append({
                "cand": cand,
                "status": "schema_missing",
                "missing": missing,
                "bindings": bindings,
            })
            continue
        sqls.append(f"{kind}_COLS {bindings} ok")
        valid.append(cand)
        notes.append({
            "cand": cand,
            "status": "bindings_ok",
            "bindings": bindings,
            "resolved": [{"table": t, "col": c} for t, c in resolved],
        })
    return _decide_drop(cands, valid, notes, sqls)


def _parse_col_cand(cand: Any) -> tuple[str, str] | None:
    if isinstance(cand, dict) and len(cand) == 1:
        k, v = next(iter(cand.items()))
        if isinstance(v, list) and len(v) == 1:
            return str(k), str(v[0])
        if isinstance(v, str) and "." not in str(k):
            return str(k), v
    return None


def _handle_null(cands: list, schema: dict, conn: sqlite3.Connection) -> dict[str, Any]:
    sqls: list[str] = []
    valid: list[Any] = []
    notes: list[dict[str, Any]] = []
    for cand in cands:
        parsed = _parse_col_cand(cand) or _parse_value_cand(cand)
        if parsed is None:
            valid.append(cand)
            notes.append({"cand": cand, "status": "unparseable_keep"})
            continue
        table, col = parsed[0], parsed[1]
        ident = _resolve_ident(schema, table, col)
        if ident is None:
            notes.append({"cand": cand, "status": "schema_missing"})
            continue
        t, c = ident
        n_null = _exec_sql(
            conn, f"SELECT COUNT(*) FROM {_qident(t)} WHERE {_qident(c)} IS NULL"
        )
        n_val = _exec_sql(
            conn, f"SELECT COUNT(*) FROM {_qident(t)} WHERE {_qident(c)} IS NOT NULL"
        )
        sqls.append(f"NULL {t}.{c} null={n_null} notnull={n_val}")
        valid.append(cand)
        notes.append({
            "cand": cand, "status": "null_stats",
            "n_null": n_null[0][0] if n_null else None,
            "n_notnull": n_val[0][0] if n_val else None,
        })
    return _decide_drop(cands, valid, notes, sqls)


def run_one_card(
    span: str,
    cands: list,
    ambig_type: str,
    db_path: str,
    *,
    question: str = "",
    extra_checks: bool = True,
) -> dict[str, Any]:
    dim = str(ambig_type or "")
    base = {
        "span": span,
        "ambig_type": dim,
        "initial": list(cands),
        "n_sql": 0,
        "trace": [],
    }
    if dim not in EXIST_TYPES:
        return {
            **base,
            "action": "Skip",
            "after": list(cands),
            "healed": None,
            "reason": "not_exist_type",
        }
    if len(cands) <= 1:
        return {
            **base,
            "action": "AutoResolve" if cands else "DropCard",
            "after": list(cands),
            "healed": cands[0] if cands else None,
            "reason": "unary",
        }

    schema = _load_schema(db_path)
    if not schema:
        return {
            **base,
            "action": "RetainForHuman",
            "after": list(cands),
            "healed": None,
            "reason": "no_sqlite",
        }

    try:
        if dim in SCHEMA_TYPES:
            dec = _handle_schema(cands, schema, kind=dim)
            dec = _rewrite_unparseable_dedup_auto(dec, list(cands))
            dec = _rewrite_uncertain_unique_auto(dec, list(cands))
            if extra_checks and dim in {"Column", "Join", "Project", "Aggregate"}:
                dec = _apply_pk_and_vd(
                    dec, kind=dim, schema=schema, db_path=db_path,
                    question=question, original=list(cands),
                )
        else:
            conn = _open_db(db_path)
            try:
                if dim == "Value":
                    dec = _handle_value(cands, schema, conn)
                else:
                    dec = _handle_null(cands, schema, conn)
            finally:
                conn.close()
            dec = _rewrite_zero_to_drop(dec, list(cands))
            dec = _rewrite_unparseable_dedup_auto(dec, list(cands))
            dec = _rewrite_uncertain_unique_auto(dec, list(cands))
    except ProbeAbort as e:
        return {
            **base,
            "action": "RetainForHuman",
            "after": list(cands),
            "healed": None,
            "reason": f"abort:{e}",
        }

    after = list(dec.get("after") if dec.get("after") is not None else cands)
    # 剪光：不再恢复
    if dec.get("action") == "DropCard":
        after = []
    n_sql = len(dec.get("sqls") or [])
    return {
        **base,
        "action": dec["action"],
        "after": after,
        "healed": after[0] if len(after) == 1 else None,
        "reason": dec.get("reason"),
        "notes": dec.get("notes") or [],
        "sqls": dec.get("sqls") or [],
        "n_sql": n_sql,
        "trace": [{"sqls": dec.get("sqls"), "notes": dec.get("notes")}],
    }


def apply_existence(
    gold,
    phi: dict[str, list],
    span_types: dict[str, str],
    healed: dict[str, Any],
) -> tuple[dict[str, list], int, int, list]:
    """返回 (phi_prime, n_probes, n_healed, trace)。DropCard 的 span 从 phi 移除。"""
    phi_prime = {k: list(v) for k, v in (phi or {}).items()}
    n_probes = n_healed = 0
    trace: list[dict] = []
    db_path = getattr(gold, "db_path", None) or ""
    question = (
        getattr(gold, "question", None)
        or getattr(gold, "question_out", None)
        or ""
    )
    for span, cands in list(phi_prime.items()):
        if not isinstance(cands, list) or len(cands) < 2:
            continue
        typ = resolve_span_type(span, span_types)
        if typ not in EXIST_TYPES:
            continue
        dec = run_one_card(span, list(cands), typ, db_path, question=question)
        n_probes += int(dec.get("n_sql") or 0)
        if dec.get("action") == "DropCard":
            phi_prime.pop(span, None)
            healed.pop(span, None)
        else:
            after = list(dec.get("after") if dec.get("after") is not None else cands)
            phi_prime[span] = after
            if len(after) == 1:
                healed[span] = after[0]
                n_healed += 1
            elif dec.get("healed") is not None:
                healed[span] = dec["healed"]
                n_healed += 1
        trace.append(dec)
    return phi_prime, n_probes, n_healed, trace
