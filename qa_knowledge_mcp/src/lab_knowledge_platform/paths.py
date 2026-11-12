from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
PROJECT_ROOT = SRC_ROOT.parent

CONFIG_ROOT = PROJECT_ROOT / "config"
DATA_ROOT = PROJECT_ROOT / "data"
EXAMPLES_ROOT = PROJECT_ROOT / "examples"
PIPELINES_ROOT = PROJECT_ROOT / "pipelines"

COSMOLOGICAL_DATA_ROOT = DATA_ROOT / "cosmological_simulation"
LITERATURE_DATA_ROOT = DATA_ROOT / "literature_digest"
DAILY_CACHE_ROOT = DATA_ROOT / "daily_digest_cache"
KNOWLEDGE_OVERLAY_DB = DATA_ROOT / "lab_knowledge.sqlite3"
INDEX_ROOT = DATA_ROOT / "indexes"


def resolve_project_path(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate
