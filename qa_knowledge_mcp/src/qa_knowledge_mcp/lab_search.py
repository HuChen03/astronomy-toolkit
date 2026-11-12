from __future__ import annotations

from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB

from .knowledge_base import KnowledgeBase


DOCUMENT_SOURCE_TYPES = {"reading_card", "paper_analysis", "topic", "decision"}
SOURCE_PRIORITY = {"qa": 0, "evidence": 1, "reading_card": 2, "paper_analysis": 3, "topic": 4, "decision": 5}


class LabKnowledgeSearch:
    def __init__(self, knowledge_base: KnowledgeBase, store_path: Path = KNOWLEDGE_OVERLAY_DB) -> None:
        self.knowledge_base = knowledge_base
        if store_path.exists():
            self.store = KnowledgeStore(store_path)
        else:
            self.store = None

    def search(self, query: str, *, top_k: int = 10, min_score: float = 0.0, source_types: list[str] | None = None) -> dict[str, Any]:
        allowed = set(source_types or ["qa", "evidence", *sorted(DOCUMENT_SOURCE_TYPES)])
        ranked_lists: list[list[dict[str, Any]]] = []
        candidate_k = max(20, min(100, top_k * 4))
        if "qa" in allowed:
            qa_results = []
            items = self.knowledge_base.search(query, top_k=candidate_k, min_score=min_score)
            annotations = self.store.qa_matches(items) if self.store else [None] * len(items)
            for item, details in zip(items, annotations):
                enriched = {**item, "source_type": "qa", "knowledge_type": "model_summary"}
                if self.store and details:
                    enriched.update({"paper_id": details["paper_id"], "qa_id": details["qa_id"], "qa_version_id": details["qa_version_id"], "review_status": details["review_status"], "knowledge_type": details["knowledge_type"], "evidence": [self._public_evidence(row) for row in self.store.evidence_for_qa_version(details["qa_version_id"])]})
                qa_results.append(enriched)
            ranked_lists.append(qa_results)
        if self.store and "evidence" in allowed:
            ranked_lists.append([{**self._public_evidence(row), "source_type": "evidence", "knowledge_type": row["knowledge_type"]} for row in self.store.search_evidence(query, limit=candidate_k)])
        document_types = allowed & DOCUMENT_SOURCE_TYPES
        if self.store and document_types:
            ranked_lists.append([{**row, "knowledge_type": row["source_type"]} for row in self.store.search_documents(query, source_types=document_types, limit=candidate_k)])
        results = self._rrf(ranked_lists)
        return {"query": query, "matched": bool(results), "results": results[: max(1, min(top_k, 100))], "retrieval": {"source_types": sorted(allowed), "fusion": "rrf", "rrf_k": 60, "generated_answer": False}}

    def answer_with_evidence(self, question: str, *, top_k: int = 8, min_score: float = 0.0) -> dict[str, Any]:
        search = self.search(question, top_k=top_k, min_score=min_score, source_types=["qa"])
        for result in search["results"]:
            if result.get("review_status") not in {"reviewed", "approved", "verified"}:
                continue
            usable = [item for item in result.get("evidence") or [] if item.get("locator_quality") != "qa_pair" and item.get("review_status") in {"reviewed", "approved", "verified"}]
            if usable:
                return {"question": question, "answered": True, "answer": result["answer"], "answer_type": "retrieved_qa", "qa_id": result.get("qa_id"), "qa_version_id": result.get("qa_version_id"), "paper_id": result.get("paper_id"), "review_status": result.get("review_status"), "evidence": usable, "warning": "This is a retrieved QA answer, not a newly generated laboratory consensus."}
        return {"question": question, "answered": False, "answer": None, "evidence": [], "reason": "No retrieved QA result has independently located evidence."}

    @staticmethod
    def _rrf(ranked_lists: list[list[dict[str, Any]]], *, rrf_k: int = 60) -> list[dict[str, Any]]:
        fused: dict[str, dict[str, Any]] = {}
        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                identity = str(item.get("qa_version_id") or item.get("evidence_id") or item.get("document_id") or f"{item.get('doc_id')}:{item.get('pair_id')}")
                entry = fused.setdefault(identity, {**item, "rrf_score": 0.0, "retrieval_ranks": []})
                entry["rrf_score"] += 1.0 / (rrf_k + rank)
                entry["retrieval_ranks"].append(rank)
        return sorted(fused.values(), key=lambda item: (-item["rrf_score"], SOURCE_PRIORITY.get(item.get("source_type"), 99), str(item.get("document_id") or item.get("evidence_id") or item.get("qa_version_id") or "")))

    def paper_evidence(self, identifier: str, *, limit: int = 50) -> dict[str, Any]:
        if not self.store:
            return {"found": False, "paper": None, "evidence": []}
        paper = self.store.resolve_paper(identifier)
        if not paper:
            return {"found": False, "paper": None, "evidence": []}
        return {"found": True, "paper": self._public_paper(paper), "evidence": [self._public_evidence(row) for row in self.store.paper_evidence(paper["paper_id"], limit=limit)]}

    def stats(self) -> dict[str, Any]:
        return self.store.stats() if self.store else {"available": False}

    @staticmethod
    def _public_evidence(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result.pop("source_locator", None)
        return result

    @staticmethod
    def _public_paper(row: dict[str, Any]) -> dict[str, Any]:
        allowed = ("paper_id", "hub_paper_id", "doi", "arxiv_id", "legacy_key", "title", "category", "match_status")
        return {key: row.get(key) for key in allowed}
