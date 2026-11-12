from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lab_knowledge_platform.hub_client import LiteratureHubClient, LiteratureHubSettings
from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT


def sync(store: KnowledgeStore, client: LiteratureHubClient, *, limit: int = 10) -> dict[str, int]:
    result = {"papers": 0, "references": 0, "citations": 0, "errors": 0}
    with store.connect() as connection:
        papers = [dict(row) for row in connection.execute("SELECT * FROM papers WHERE match_status='matched' ORDER BY paper_id LIMIT ?", (limit,))]
    for paper in papers:
        identifier = paper.get("hub_paper_id") or paper.get("doi")
        if not identifier:
            continue
        result["papers"] += 1
        for relation_type, endpoint, key in (("reference", "/api/v1/papers/references", "references"), ("citation", "/api/v1/papers/citations", "citations")):
            try:
                rows = client.paper_relations(endpoint, identifier)
                result[key] += store.replace_paper_relations(paper["paper_id"], relation_type, rows)
            except Exception:
                result["errors"] += 1
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync paper references and citations from the literature hub.")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    parser.add_argument("--base-url", default=os.environ.get("LITERATURE_HUB_BASE_URL", ""))
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if not args.base_url.strip():
        parser.error("configure LITERATURE_HUB_BASE_URL or pass --base-url")
    path = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    result = sync(KnowledgeStore(path), LiteratureHubClient(LiteratureHubSettings(args.base_url.rstrip("/"))), limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["errors"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
