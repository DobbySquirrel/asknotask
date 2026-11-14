"""CLEAR-F：原文 match 侧列检索剪枝。不改 repos/CLEAR。

官方 schema_retrieval：k = clip(0.25 * n, 10, 15)，all-mpnet-base-v2 cosine。
列说明用 BIRD database_description（已在 interpretations() 里），不再另调 LLM。
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Optional

QUERY_SCOPE_RE = re.compile(r"\b(each|every|all)\b", re.I)
QUERY_ATTACH_RE = re.compile(r"\b(and|or)\b", re.I)
QUERY_KW_RE = re.compile(r"\b(each|every|all|and|or)\b", re.I)
_TOK = re.compile(r"[a-z0-9]+")


def query_gate_keywords(question: str) -> bool:
    """原文 Query 开门：NL 含 each/every/all 或 and/or。"""
    return bool(QUERY_KW_RE.search(question or ""))


def query_gate_scope_only(question: str) -> bool:
    return bool(QUERY_SCOPE_RE.search(question or ""))


def retrieve_k(n: int) -> int:
    if n <= 0:
        return 0
    return min(n, max(10, min(15, int(n * 0.25))))


def _lexical_scores(question: str, passages: list[str]) -> list[float]:
    qt = set(_TOK.findall((question or "").lower()))
    out: list[float] = []
    for p in passages:
        pt = set(_TOK.findall((p or "").lower()))
        if not qt or not pt:
            out.append(0.0)
            continue
        out.append(len(qt & pt) / math.sqrt(len(qt) * len(pt)))
    return out


@lru_cache(maxsize=1)
def _st_model():
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None
    for name in (
        "sentence-transformers/all-mpnet-base-v2",
        "all-mpnet-base-v2",
    ):
        try:
            return SentenceTransformer(name)
        except Exception:
            continue
    return None


def retrieve_interpretations(
    question: str,
    passages: list[str],
    k: Optional[int] = None,
) -> tuple[list[str], dict]:
    """返回 (top-k 列说明, 检索元信息)。优先 mpnet，否则词重叠。"""
    n = len(passages or [])
    if n == 0:
        return [], {"n_all": 0, "n_used": 0, "k": 0, "backend": "empty"}
    kk = retrieve_k(n) if k is None else min(n, max(1, int(k)))
    backend = "lexical"
    scores: list[float]
    model = _st_model()
    if model is not None:
        try:
            from sentence_transformers import util

            q = model.encode([question or ""], convert_to_tensor=True)
            p = model.encode(list(passages), convert_to_tensor=True)
            scores = util.cos_sim(q, p)[0].cpu().tolist()
            backend = "mpnet"
        except Exception:
            scores = _lexical_scores(question, passages)
    else:
        scores = _lexical_scores(question, passages)
    order = sorted(range(n), key=lambda i: scores[i], reverse=True)[:kk]
    picked = [passages[i] for i in order]
    return picked, {
        "n_all": n,
        "n_used": len(picked),
        "k": kk,
        "backend": backend,
        "top_score": scores[order[0]] if order else None,
    }
