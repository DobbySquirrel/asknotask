"""Human pick 之后的拼接：改写落地 + DetectResult 合同。"""
from .contract import DEFAULT_REWRITE, DetectResult, PARSERS, REWRITE_MODES, SYSTEMS
from .rewrite import (
    apply_rewrite,
    merge_evidence,
    render_mapping_snippet,
    evidence_dump,
    evidence_qa,
    _table_col_keys,
)

__all__ = [
    "DEFAULT_REWRITE",
    "DetectResult",
    "PARSERS",
    "REWRITE_MODES",
    "SYSTEMS",
    "apply_rewrite",
    "merge_evidence",
    "render_mapping_snippet",
    "evidence_dump",
    "evidence_qa",
    "_table_col_keys",
]
