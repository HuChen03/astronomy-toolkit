from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from lab_knowledge_platform.hub_client import LiteratureHubClient, LiteratureHubSettings
from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT


def normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value.lower()).strip()


def identifier_fingerprint(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def match_papers(store: KnowledgeStore, client: LiteratureHubClient, *, limit: int = 1000) -> dict[str, Any]:
    stats = {"processed": 0, "matched": 0, "needs_review": 0, "not_found": 0, "errors": []}
    for paper in store.list_papers_for_matching(limit=limit):
        stats["processed"] += 1
        try:
            candidate = client.read_paper(doi=paper.get("doi")) if paper.get("doi") else None
            method = "doi_exact"
            if not candidate and paper.get("title"):
                candidate = client.read_paper(title=paper["title"])
                method = "title_exact"
            if not candidate and paper.get("title"):
                results = client.offline_search(paper["title"], per_page=10)
                exact_titles = [row for row in results if normalized_title(str(row.get("title") or "")) == normalized_title(paper["title"])]
                if len(exact_titles) == 1:
                    candidate = exact_titles[0]
                    method = "offline_title_exact"
            if not candidate and paper.get("title"):
                results = client.online_search(paper["title"], top_k=10, ingest=True)
                exact_titles = [row for row in results if normalized_title(str(row.get("title") or "")) == normalized_title(paper["title"])]
                if len(exact_titles) == 1:
                    candidate = exact_titles[0]
                    method = "online_title_exact"
            if not candidate:
                store.update_paper_match(paper["paper_id"], hub_paper_id=None, status="legacy_unmatched", method="not_found", confidence=0.0)
                stats["not_found"] += 1
                continue
            hub_id = str(candidate.get("id") or candidate.get("paper_id") or candidate.get("local_paper_id") or "")
            doi_equal = bool(paper.get("doi") and candidate.get("doi") and identifier_fingerprint(str(candidate["doi"])) == identifier_fingerprint(str(paper["doi"])))
            title_equal = normalized_title(str(candidate.get("title") or "")) == normalized_title(str(paper.get("title") or ""))
            status = "matched" if hub_id and doi_equal else "needs_review"
            if status == "matched" and method in {"title_exact", "offline_title_exact", "online_title_exact"}:
                method += "+doi_fingerprint"
            confidence = 1.0 if status == "matched" else (0.95 if hub_id and title_equal else 0.6)
            store.update_paper_match(paper["paper_id"], hub_paper_id=hub_id or None, status=status, method=method, confidence=confidence, hub_metadata=candidate)
            stats[status] += 1
        except Exception as error:
            store.update_paper_match(paper["paper_id"], hub_paper_id=None, status="legacy_unmatched", method="transient_error", confidence=0.0)
            stats["errors"].append({"paper_id": paper["paper_id"], "error": f"{type(error).__name__}: {error}"})
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Match overlay papers to literature-hub paper UUIDs.")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    parser.add_argument("--base-url", default=os.environ.get("LITERATURE_HUB_BASE_URL", ""))
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    store_path = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    if not args.base_url.strip():
        parser.error("configure LITERATURE_HUB_BASE_URL or pass --base-url")
    result = match_papers(KnowledgeStore(store_path), LiteratureHubClient(LiteratureHubSettings(args.base_url.rstrip("/"))), limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
