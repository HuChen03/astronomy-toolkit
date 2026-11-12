from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiteratureHubSettings:
    base_url: str
    timeout_seconds: float = 30.0


class LiteratureHubClient:
    def __init__(self, settings: LiteratureHubSettings) -> None:
        if not settings.base_url.strip():
            raise ValueError("LITERATURE_HUB_BASE_URL must be configured")
        self.settings = settings

    def read_paper(self, *, paper_id: str | None = None, doi: str | None = None, arxiv_id: str | None = None, title: str | None = None) -> dict[str, Any] | None:
        identifier = paper_id or doi or arxiv_id or title
        if not identifier:
            raise ValueError("one paper identifier is required")
        try:
            result = self._post("/api/v1/read", {"identifier": identifier, "prefer": "markdown_then_pdf", "ensure_markdown": False, "include_legacy": True})
            return None if result.get("status") == "error" or result.get("error") else result
        except RuntimeError as error:
            if "http_404" in str(error):
                return None
            raise

    def offline_search(self, query: str, *, per_page: int = 10) -> list[dict[str, Any]]:
        response = self._post("/api/v1/search/offline", {"query": query, "search_scope": ["title", "doi", "arxiv_id"], "mode": "hybrid", "page": 1, "per_page": per_page, "enqueue_missing_markdown": False})
        return [row for row in response.get("results") or [] if isinstance(row, dict)]

    def backfill_markdown(self, markdown_dir: str, *, recursive: bool = True, overwrite: bool = False, dry_run: bool = True, max_read_bytes: int = 262144, max_files: int | None = None) -> dict[str, Any]:
        return self._post("/api/v1/markdown/backfill/by-dir", {
            "markdown_dir": markdown_dir,
            "recursive": recursive,
            "overwrite": overwrite,
            "create_missing": False,
            "dry_run": dry_run,
            "max_read_bytes": max_read_bytes,
            "max_files": max_files,
        })

    def online_search(self, query: str, *, top_k: int = 10, ingest: bool = True) -> list[dict[str, Any]]:
        response = self._post("/api/v1/search/online", {
            "query": query,
            "search_queries": [query],
            "top_k": top_k,
            "ingest": ingest,
            "download": False,
            "fetch_pdf": False,
        })
        return [row for row in response.get("results") or [] if isinstance(row, dict)]

    def paper_relations(self, endpoint: str, identifier: str, *, limit: int = 100) -> list[dict[str, Any]]:
        response = self._post(endpoint, {"identifier": identifier, "limit": limit, "fresh": False})
        key = "references" if endpoint.endswith("references") else "citations"
        return [row for row in response.get(key) or [] if isinstance(row, dict)]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(self.settings.base_url.rstrip("/") + path, data=json.dumps(payload, ensure_ascii=False).encode(), headers={"content-type": "application/json", "accept": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"literature_hub_http_{error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"literature_hub_unavailable: {error.reason}") from error
        if not isinstance(value, dict):
            raise RuntimeError("literature_hub_returned_non_object_json")
        return value
