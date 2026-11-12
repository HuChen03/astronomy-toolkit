from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import PROJECT_ROOT

from .knowledge_base import RRF_K, KnowledgeBase


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
                source=self._resolve(main_source) if main_source is not None else configs['main'].source,
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
            try:
                knowledge_base = self._get(identifier)
            except (FileNotFoundError, ValueError):
                knowledge_base = None
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
                "index_warning": stats.get("index_error") or None,
            })
        return result

    def search(self, query: str, *, knowledge_base_ids: list[str] | None = None, top_k: int = 10, min_score: float = 0.0) -> dict[str, Any]:
        selected = self.selected_ids(knowledge_base_ids)
        libraries = {identifier: self._get(identifier) for identifier in selected}
        candidates = [(identifier, item) for identifier, kb in libraries.items() for item in kb.recall(query, top_k)]
        results = libraries["main"].rank(
            query, candidates, top_k, min_score, corpora=[kb.bm25_index for kb in libraries.values()],
        )
        for item in results:
            item["knowledge_base_name"] = self.configs[item["knowledge_base_id"]].name
        retrieval = {"fusion": "rrf", "rrf_k": RRF_K, "generated_answer": False}
        try:
            self._attach_source_paragraphs(results)
        except sqlite3.Error:
            retrieval["evidence_warning"] = "evidence overlay is unavailable"
        return {
            "query": query,
            "knowledge_base_ids": selected,
            "matched": bool(results),
            "results": results,
            "retrieval": retrieval,
        }

    def _attach_source_paragraphs(self, items: list[dict[str, Any]]) -> None:
        if not self.overlay_path or not self.overlay_path.is_file():
            return
        main_items = [item for item in items if item["knowledge_base_id"] == "main"]
        store = KnowledgeStore(self.overlay_path, read_only=True)
        for item, details in zip(main_items, store.qa_matches(main_items)):
            if not details:
                continue
            if not item["source_paragraph"] and details["evidence_text"]:
                item.update(source_paragraph=details["evidence_text"], source_section=details["section_path"],
                            source_locator_quality=details["locator_quality"])
            for key in ("paper_id", "qa_id", "qa_version_id", "review_status"):
                item[key] = details[key]
