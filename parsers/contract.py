"""Minimal result bag used by parser prompt builders."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectResult:
    schema_out: str = ""
    question_out: str = ""
    evidence_out: str = ""
    clarification: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
