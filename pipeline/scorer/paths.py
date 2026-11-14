"""打分器路径。默认都在本仓库内（outputs/scorer、dataset/、models/）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("SCORER_WORK", str(REPO / "outputs" / "scorer")))
BUILD = Path(os.environ.get("SCORER_BUILD", str(WORK / "build")))


def ensure_repo_on_path() -> None:
    root = str(REPO)
    if root not in sys.path:
        sys.path.insert(0, root)


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else None


MODEL = _env_path("SCORER_MODEL") or (REPO / "models" / "Qwen3-8B")

ensure_repo_on_path()


def clambsql_json() -> Path:
    """Official CLAMBSQL native-option file (not dataset/clambsql/gold.jsonl)."""
    env = _env_path("CLAM_JSON")
    if env:
        return env
    return REPO / "dataset" / "clambsql" / "clambsql.json"


def theta_star(default: float = 0.5) -> float:
    env = os.environ.get("SCORER_THETA", "").strip()
    if env:
        return float(env)
    path = WORK / "select_theta.json"
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
        value = doc.get("theta_star")
        if value is not None:
            return float(value)
    return default
