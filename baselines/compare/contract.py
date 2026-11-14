"""DetectResult：检测+Human+改写之后、进 parser 之前的统一合同。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

REWRITE_MODES = ("schema_dq", "schema_dqg", "schema_q", "ambisql", "evidence", "none")
SYSTEMS = ("zero", "clear", "ambisql", "ours", "ours_1bc")
PARSERS = ("base", "deepeye")
DEFAULT_REWRITE = {
    "zero": "none",
    "clear": "schema_dq",
    "ambisql": "ambisql",
    "ours": "evidence",
    "ours_1bc": "evidence",
}


@dataclass
class DetectResult:
    id: str
    system: str
    rewrite_mode: str
    question_in: str
    schema_in: str
    question_out: str
    schema_out: str
    evidence_out: str = ""
    clarification: str = ""
    ambiguity_mapping: Optional[dict[str, Any]] = None
    pick: Optional[dict[str, Any]] = None
    pivots: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_pred_fields(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pivots": list(self.pivots),
            "columns": list(self.columns),
            "ambiguity_mapping": self.ambiguity_mapping,
            "question_out": self.question_out,
            "schema_out": self.schema_out,
            "evidence_out": self.evidence_out,
            "clarification": self.clarification,
            "rewrite_mode": self.rewrite_mode,
            "system": self.system,
            "n_asked": (self.meta or {}).get("n_asked", 0),
            "n_answered": (self.meta or {}).get("n_answered", 0),
            "intervened": (self.meta or {}).get("intervened", False),
            "turns": (self.meta or {}).get("turns", 0),
            "n_rounds": (self.meta or {}).get("n_rounds", 0),
            "round_asks": (self.meta or {}).get("round_asks") or [],
            "rounds": (self.meta or {}).get("rounds") or [],
            "human": (self.meta or {}).get("human"),
            "agree_08_official": (self.meta or {}).get("agree_08_official"),
            "official_pick": (self.meta or {}).get("official_pick"),
            "n_probes": (self.meta or {}).get("n_probes"),
            "n_healed": (self.meta or {}).get("n_healed"),
            "n_qc": (self.meta or {}).get("n_qc"),
            "probes": (self.meta or {}).get("probes") or [],
            "probe_judges": (self.meta or {}).get("probe_judges") or [],
            "probe_facts": (self.meta or {}).get("probe_facts") or "",
            "ask_cards": (self.meta or {}).get("ask_cards") or [],
            "healed": (self.meta or {}).get("healed") or {},
            "qc_question": (self.meta or {}).get("qc_question") or "",
            "phi": (self.meta or {}).get("phi") or {},
            "phi_prime": (self.meta or {}).get("phi_prime") or {},
            "batches": (self.meta or {}).get("batches") or {},
            "eig_mode": (self.meta or {}).get("eig_mode"),
            "eig_scope": (self.meta or {}).get("eig_scope"),
            "eig_trace": (self.meta or {}).get("eig_trace") or [],
            "clear_faithful": (self.meta or {}).get("clear_faithful"),
            "query_gate": (self.meta or {}).get("query_gate"),
            "n_interp_all": (self.meta or {}).get("n_all") or (self.meta or {}).get("n_interp_all"),
            "n_interp_used": (self.meta or {}).get("n_used") or (self.meta or {}).get("n_interp_used"),
        }
