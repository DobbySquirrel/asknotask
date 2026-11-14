"""Ambiguity checks.

Existence, Difference, and Relevance each have a standalone apply_* entry
in their own modules. The run_* scripts are experiment runners only.
"""
from importlib import import_module

__all__ = ["apply_existence", "apply_difference", "apply_relevance"]

_EXPORTS = {
    "apply_existence": ".existence",
    "apply_difference": ".difference",
    "apply_relevance": ".relevance",
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
