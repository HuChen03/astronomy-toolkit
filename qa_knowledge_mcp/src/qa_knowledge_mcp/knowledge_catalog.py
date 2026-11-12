from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import PROJECT_ROOT

from .knowledge_base import KnowledgeBase


@dataclass(frozen=True)
class KnowledgeBaseConfig:
    knowledge_base_id: str
    name: str
    description: str
    source: Path
    index: Path | None
    enabled: bool = True


class KnowledgeBaseCatalog:
    """Load same-format QA knowledge bases and route searches across them."""

    def __init__(
        self,
        config_dir: Path,
        *,
        main_source: Path | None = None,
        main_index: Path | None = None,
        overlay_path: Path | None = None,
    ) -> None:
        self.config_dir = config_dir if config_dir.is_absolute() else PROJECT_ROOT / config_dir
        self.overlay_path = overlay_path
        self.configs = self._load_configs(main_source=main_source, main_index=main_index)
        self._knowledge_bases: dict[str, KnowledgeBase] = {}

    def _load_configs(self, *, main_source: Path | None, main_index: Path | None) -> dict[str, KnowledgeBaseConfig]:
        configs: dict[str, KnowledgeBaseConfig] = {}
        files = sorted(self.config_dir.glob("*.json")) if self.config_dir.exists() else []
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            identifier = str(payload.get("id") or payload.get("knowledge_base_id") or path.stem).strip()
            if not identifier:
                continue
            source = self._resolve(payload.get("source"))
            index_value = payload.get("index")
            index = self._resolve(index_value) if index_value else None
            configs[identifier] = KnowledgeBaseConfig(
                knowledge_base_id=identifier,
                name=str(payload.get("name") or identifier),
                description=str(payload.get("description") or ""),
                source=source,
                index=index,
                enabled=bool(payload.get("enabled", True)),
            )
        if "main" not in configs:
            source = main_source or PROJECT_ROOT / "data/cosmological_simulation/generate_paper.jsonl"
            configs["main"] = KnowledgeBaseConfig(
                knowledge_base_id="main",
                name="主知识库",
                description="实验室主 QA 知识库。",
                source=self._resolve(source),
                index=self._resolve(main_index) if main_index else None,
            )
        elif main_source is not None or main_index is not None:
            configs["main"] = KnowledgeBaseConfig(
                knowledge_base_id="main",
                name=configs["main"].name,
                description=configs["main"].description,
                source=self._resolve(main_source),
                index=(
                    self._resolve(main_index)
                    if main_index is not None
                    else None
                    if main_source is not None
                    else configs["main"].index
                ),
                enabled=configs["main"].enabled,
            )
        return configs

    @staticmethod
    def _resolve(value: str | Path) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    def _get(self, identifier: str) -> KnowledgeBase:
        if identifier not in self.configs:
            raise ValueError(f"unknown knowledge base: {identifier}")
        config = self.configs[identifier]
        if not config.enabled:
            raise ValueError(f"knowledge base is disabled: {identifier}")
        if identifier not in self._knowledge_bases:
            self._knowledge_bases[identifier] = KnowledgeBase(config.source, config.index)
        return self._knowledge_bases[identifier]

    def selected_ids(self, knowledge_base_ids: list[str] | None) -> list[str]:
        # Explicit small directions augment, rather than replace, the main database.
        requested = [item.strip() for item in (knowledge_base_ids or []) if item and item.strip()]
        selected = ["main"] + [item for item in requested if item != "main"]
        unknown = [item for item in selected if item not in self.configs]
        if unknown:
            raise ValueError(f"unknown knowledge base(s): {', '.join(unknown)}")
        disabled = [item for item in selected if not self.configs[item].enabled]
        if disabled:
            raise ValueError(f"disabled knowledge base(s): {', '.join(disabled)}")
        return list(dict.fromkeys(selected))

    def list(self) -> list[dict[str, Any]]:
        result = []
        for identifier, config in sorted(self.configs.items()):
            if not config.enabled:
                continue
            knowledge_base = self._get(identifier) if config.source.exists() else None
            stats = knowledge_base.stats() if knowledge_base else {"record_count": 0, "doc_count": 0}
            result.append({
                "id": identifier,
                "name": config.name,
                "description": config.description,
                "status": "active" if knowledge_base else "unavailable",
                "source": str(config.source.relative_to(PROJECT_ROOT)) if config.source.is_relative_to(PROJECT_ROOT) else str(config.source),
                "index": str(config.index.relative_to(PROJECT_ROOT)) if config.index and config.index.is_relative_to(PROJECT_ROOT) else str(config.index) if config.index else None,
                "qa_count": stats.get("record_count", 0),
                "paper_count": stats.get("doc_count", 0),
            })
        return result

    def search(self, query: str, *, knowledge_base_ids: list[str] | None = None, top_k: int = 10, min_score: float = 0.0) -> dict[str, Any]:
        selected = self.selected_ids(knowledge_base_ids)
        per_base = max(top_k * 4, 20)
        ranked: list[dict[str, Any]] = []
        for identifier in selected:
            config = self.configs[identifier]
            results = self._get(identifier).search(query, top_k=per_base, min_score=min_score)
            for rank, item in enumerate(results, start=1):
                enriched = {**item, "knowledge_base_id": identifier, "knowledge_base_name": config.name, "retrieval_rank": rank}
                self._attach_source_paragraph(enriched)
                ranked.append(enriched)
        ranked.sort(key=lambda item: (-float(item.get("score", 0)), item["knowledge_base_id"], str(item.get("doc_id")), int(item.get("pair_id", 0))))
        return {
            "query": query,
            "knowledge_base_ids": selected,
            "matched": bool(ranked),
            "results": ranked[: max(1, min(top_k, 100))],
            "retrieval": {"fusion": "score_sort", "generated_answer": False},
        }

    def _attach_source_paragraph(self, item: dict[str, Any]) -> None:
        if item.get("source_paragraph"):
            return
        if not self.overlay_path or not self.overlay_path.exists() or item.get("knowledge_base_id") != "main":
            return
        store = KnowledgeStore(self.overlay_path, read_only=True)
        details = store.qa_details(str(item.get("doc_id")), int(item.get("pair_id", 0)))
        if not details:
            return
        evidence = store.evidence_for_qa_version(details["qa_version_id"])
        if evidence:
            best = sorted(evidence, key=lambda row: (row.get("locator_quality") != "section", -float(row.get("alignment_confidence") or 0)))[0]
            item["source_paragraph"] = best.get("evidence_text") or ""
            item["source_section"] = best.get("section_path")
            item["source_locator_quality"] = best.get("locator_quality")
        item["paper_id"] = details.get("paper_id")
        item["qa_id"] = details.get("qa_id")
        item["qa_version_id"] = details.get("qa_version_id")
        item["review_status"] = details.get("review_status")
