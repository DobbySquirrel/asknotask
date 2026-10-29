"""Bindings to the existing pipeline (method-freeze-20261028b + V2 fixes).

Every function below must call the code that produced the frozen V2 runs.
Do not reimplement prompts or checks here; import and delegate. Each
function documents the exact contract that task_c.py relies on.
"""
from __future__ import annotations

from typing import Any


def load_questions(dataset: str) -> list[dict]:
    """Return one record per question of the benchmark, in benchmark order.

    Required keys: qid, question, evidence, db_id, gold_sql (y*).
    The record is passed back unchanged to every other adapter, so it may
    carry anything the existing code needs (schema, S+, etc.).
    """
    raise NotImplementedError


def load_frozen(dataset: str) -> dict[str, dict]:
    """Map qid -> frozen V2 Always-Ask record (the 324 / 513 / 776 runs).

    Required keys per record:
      cards        list of forward cards after detection (each with span,
                   type, stage, interpretations; whatever the checks need)
      asked        list of cards that reached the simulated user
      responses    {card_id: response} of the simulated user
      evidence     evidence string given to the parser
      pred_sql     parser output
      correct      bool under y* with the 30 s gold cache
      y_bot_sql    no-clarification query y_bot
    """
    raise NotImplementedError


def load_d10(dataset: str) -> dict[str, dict]:
    """Map qid -> frozen D10 record (BIRD: run C = 341, AMBROSIA/CLAMBSQL:
    handoff_d10_ac). Required keys: drafts (list of {sql, strategy}),
    draft_descriptions ({sql: M1 description}), d10_cards, evidence,
    pred_sql, correct, n_asked (questions asked in the D10 run, merged
    D10 cards not counted). Questions without drafts may be absent.
    """
    raise NotImplementedError


def execute(db_id: str, sql: str, timeout_s: float = 30.0) -> Any:
    """Execute on the benchmark database. Return rows, or None on error or
    timeout. Must be the same executor the 30 s gold cache was built with."""
    raise NotImplementedError


def results_equal(rows_a: Any, rows_b: Any, question: str) -> bool:
    """The comparator used for EX scoring (official set comparison).
    Draft groups are formed with this function, so that two drafts that
    differ only in row order fall into the same group."""
    raise NotImplementedError


def detect_stage(stage: int, rec: dict, open_ambiguities: list[dict],
                 extra_block: str, port: int) -> list[dict]:
    """Run Stage `stage` (1, 2, 3) of the existing staged detection with the
    unchanged prompt, appending `extra_block` verbatim at the end of the
    user message. `open_ambiguities` is the Stage 1 (or Stage 1+2) open
    block, as in V2. Temperature 0. Return the cards of this stage, already
    post-processed exactly as in V2 (Scope templates for Stage-1 Scope,
    multiple types per span kept, no Scope fallback for empty types).
    """
    raise NotImplementedError


def run_checks(rec: dict, card: dict, port: int) -> dict:
    """Apply Q1, Q2, Q3 by the applicability table, with P1 and P2.
    Return {"outcome": one of "q1_removed", "settled_written",
    "settled_dropped", "q3_removed", "ask", "error"},
    "card": the card after checks, "written": sentence or None}.
    """
    raise NotImplementedError


def simulate_user(rec: dict, card: dict, port: int) -> Any:
    """Existing simulated user (sees y*). Return its response."""
    raise NotImplementedError


def compose_evidence(rec: dict, written: list[str],
                     answered: list[tuple[dict, Any]]) -> str:
    """Existing composition: E' = E + sentences, one per ambiguity."""
    raise NotImplementedError


def parse(rec: dict, evidence: str, port: int) -> str:
    """Existing Qwen3-Coder parser call, max tokens 4096."""
    raise NotImplementedError


def score(rec: dict, pred_sql: str) -> bool:
    """EX under y* with the 30 s gold cache."""
    raise NotImplementedError
