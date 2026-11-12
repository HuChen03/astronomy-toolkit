from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from lab_knowledge_platform.hub_client import LiteratureHubClient, LiteratureHubSettings
from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT
from .import_knowledge_documents import import_documents
from .match_hub_papers import match_papers


def run_one(store: KnowledgeStore, *, base_url: str) -> dict[str, Any] | None:
    task = store.claim_task()
    if not task:
        return None
    try:
        handlers: dict[str, Callable[[], dict[str, Any]]] = {
            "match_papers": lambda: match_papers(
                store,
                LiteratureHubClient(LiteratureHubSettings(base_url=base_url)),
                limit=int(task["payload"].get("limit", 1000)),
            ),
            "import_documents": lambda: import_documents(
                Path(task["payload"]["root"]), store.path,
            ),
            "markdown_backfill": lambda: LiteratureHubClient(LiteratureHubSettings(base_url=base_url)).backfill_markdown(
                task["payload"]["markdown_dir"], dry_run=bool(task["payload"].get("dry_run", True)),
            ),
        }
        handler = handlers.get(task["stage"])
        if handler is None:
            raise ValueError(f"unsupported task stage: {task['stage']}")
        result = handler()
        store.finish_task(task["task_id"], result=result)
        return {"task_id": task["task_id"], "status": "succeeded", "result": result}
    except Exception as error:
        store.fail_task(task["task_id"], f"{type(error).__name__}: {error}")
        return {"task_id": task["task_id"], "status": "failed", "error": str(error)}


def run_many(store: KnowledgeStore, *, base_url: str, max_tasks: int = 1, poll_seconds: float = 0.0) -> list[dict[str, Any]]:
    results = []
    while len(results) < max(1, max_tasks):
        result = run_one(store, base_url=base_url)
        if result is not None:
            results.append(result)
            continue
        if poll_seconds <= 0:
            break
        time.sleep(poll_seconds)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one queued laboratory knowledge task.")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    parser.add_argument("--base-url", default=os.environ.get("LITERATURE_HUB_BASE_URL", ""))
    parser.add_argument("--max-tasks", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if not args.base_url.strip():
        parser.error("configure LITERATURE_HUB_BASE_URL or pass --base-url")
    store_path = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    print(json.dumps(run_many(KnowledgeStore(store_path), base_url=args.base_url, max_tasks=args.max_tasks, poll_seconds=args.poll_seconds), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
