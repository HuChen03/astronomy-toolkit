from __future__ import annotations

from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parents[1]
ASSET_ROOT = PROJECT_ROOT / "data" / "knowledge_acquisition"

COSMOLOGICAL_CORE_ROOT = ASSET_ROOT / "cosmological_simulation_core"
COSMOLOGICAL_QA_ROOT = ASSET_ROOT / "cosmological_simulation_qa_cache"
COSMOLOGICAL_INDEX_ROOT = ASSET_ROOT / "cosmological_simulation_qa_index"


def project_path(path: Path | str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate
