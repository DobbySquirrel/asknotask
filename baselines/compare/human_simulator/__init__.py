"""Human simulators used by the CLEAR and AmbiSQL wrappers."""
from __future__ import annotations

from typing import Any, Optional

from .grounded_hybrid import pick_hybrid
from .official_clear import PickResult, pick_clambsql_official
from .standard import pick_mapping_08

SIMULATOR_CLAMBSQL = "clear_official"
SIMULATOR_HYBRID = "grounded_hybrid"
CLAMBSQL_DATASETS = {"clambsql"}


def pick(
    dataset: str,
    *,
    clear_ambiguity: Any = None,
    ambiguity_mapping: Any = None,
    gold_table_columns: Optional[set[str]] = None,
    question: str = "",
    nl_options: Optional[dict[str, list[str]]] = None,
    agent_fn=None,
) -> PickResult:
    if dataset in CLAMBSQL_DATASETS:
        return pick_clambsql_official(clear_ambiguity, ambiguity_mapping)
    return pick_hybrid(
        gold_table_columns=gold_table_columns or set(),
        ambiguity_mapping=ambiguity_mapping,
        question=question,
        nl_options=nl_options or {},
        agent_fn=agent_fn,
    )


__all__ = [
    "SIMULATOR_CLAMBSQL",
    "SIMULATOR_HYBRID",
    "PickResult",
    "pick",
    "pick_clambsql_official",
    "pick_mapping_08",
]
