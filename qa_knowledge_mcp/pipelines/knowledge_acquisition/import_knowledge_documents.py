from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT


def _title(markdown: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else fallback


def _doi_from_filename(path: Path) -> str | None:
    name = path.name.removesuffix(".knowledge.md")
    parts = name.split("_", 1)
    if len(parts) != 2 or not parts[1].startswith("10."):
        return None
    return parts[1].replace("_", "/", 1)


def import_documents(root: Path, store_path: Path) -> dict[str, Any]:
    store = KnowledgeStore(store_path)
    imported = 0
    linked = 0
    for path in sorted(root.rglob("*.md")):
        if path.name in {"README.md"}:
            continue
        body = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not body:
            continue
        relative = path.relative_to(root).as_posix()
        if "/topics/" in f"/{relative}" or relative.startswith("topics/"):
            source_type = "topic"
        elif "/decisions/" in f"/{relative}" or relative.startswith("decisions/"):
            source_type = "decision"
        else:
            source_type = "reading_card"
        paper = store.resolve_paper(_doi_from_filename(path) or "")
        document_id = f"{source_type}:{hashlib.sha256(relative.encode()).hexdigest()[:24]}"
        store.upsert_document(
            document_id=document_id,
            paper_id=paper["paper_id"] if paper else None,
            source_type=source_type,
            title=_title(body, path.stem),
            body=body,
            review_status="legacy_unreviewed",
            metadata={"source_artifact": relative, "importer": "knowledge_documents_v1"},
        )
        imported += 1
        if paper:
            linked += 1
    return {"root": str(root), "store": str(store_path), "imported": imported, "paper_linked": linked, "stats": store.stats()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Markdown reading cards, topics, and decisions.")
    parser.add_argument("root", type=Path, nargs="?", default=PROJECT_ROOT / "data/knowledge_acquisition/paper_library_1_knowledge")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    args = parser.parse_args()
    root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
    store = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    print(json.dumps(import_documents(root, store), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
