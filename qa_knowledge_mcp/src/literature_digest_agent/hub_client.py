from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import HubSettings


class LiteratureHubClient:
    def __init__(self, settings: HubSettings) -> None:
        self._settings = settings

    def fetch_daily_digest(
        self,
        digest_date: str,
        discipline: str,
        limit: int,
        *,
        window_start: str | None = None,
        window_end: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "date": digest_date,
            "domain": normalize_domain(discipline),
            "ranking_mode": "latest",
            "topk": min(max(1, limit), 50),
            "candidate_limit": min(max(50, limit), 5000),
            "preselect_limit": min(max(1, limit), 500),
            "backfill_days": 0,
            "refresh_forward": False,
            "fulltext": False,
            "store_markdown": False,
            "use_llm": True,
            "include_markdown_text": False,
            "cache_policy": "build",
        }
        if window_start and window_end:
            payload["window_start"] = window_start
            payload["window_end"] = window_end
            payload["start_time"] = window_start
            payload["end_time"] = window_end
        response = self._post_json("/api/v1/digest/daily", payload)
        return normalize_daily_digest_response(response)

    def get_automation_jobs(self) -> dict[str, Any]:
        value = self._get_json_value("/api/v1/automation/jobs")
        if isinstance(value, list):
            return {"jobs": [item for item in value if isinstance(item, dict)]}
        if isinstance(value, dict):
            return value
        raise RuntimeError("literature_hub_returned_invalid_automation_jobs")

    def _get_json(self, path: str) -> dict[str, Any]:
        value = self._get_json_value(path)
        if not isinstance(value, dict):
            raise RuntimeError("literature_hub_returned_non_object_json")
        return value

    def _get_json_value(self, path: str) -> Any:
        request = urllib.request.Request(
            self._settings.base_url + path,
            headers={"accept": "application/json"},
            method="GET",
        )
        return self._open_json_value(request)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._settings.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        value = self._open_json_value(request)
        if not isinstance(value, dict):
            raise RuntimeError("literature_hub_returned_non_object_json")
        return value

    def _open_json_value(self, request: urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(request, timeout=self._settings.timeout_seconds) as response:
                body = response.read().decode("utf8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf8", errors="replace")[:1000]
            raise RuntimeError(f"literature_hub_http_{error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"literature_hub_unavailable: {error.reason}") from error
        return json.loads(body)


def normalize_domain(value: str) -> str:
    normalized = value.strip().lower()
    aliases = {
        "cond-mat": "condmat",
        "cond_mat": "condmat",
    }
    return aliases.get(normalized, normalized)


def normalize_daily_digest_response(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "building":
        return {
            "status": "building",
            "date": payload.get("date"),
            "items": [],
            "summary": payload.get("overall_summary") or payload.get("message") or "",
            "stats": {"total_candidates": 0, "selected": 0},
            "retry_after_seconds": payload.get("retry_after_seconds", 30),
            "cache_key": payload.get("cache_key"),
        }
    if isinstance(payload.get("items"), list):
        return payload

    detailed = {
        str(item.get("paper_id")): item
        for item in payload.get("papers") or []
        if isinstance(item, dict) and item.get("paper_id")
    }
    metadata_items = [
        item for item in payload.get("all_papers_metadata") or [] if isinstance(item, dict)
    ]
    source_items = metadata_items or [
        item for item in payload.get("papers") or [] if isinstance(item, dict)
    ]
    items: list[dict[str, Any]] = []
    for metadata in source_items:
        paper_id = str(metadata.get("paper_id") or "")
        detail = detailed.get(paper_id) or {}
        item = dict(metadata)
        summary_value = detail.get("summary")
        if isinstance(summary_value, dict):
            summary_text = (
                summary_value.get("brief")
                or summary_value.get("summary")
                or summary_value.get("text")
                or ""
            )
        else:
            summary_text = summary_value or ""
        if summary_text:
            item["brief"] = str(summary_text)
            item["brief_source"] = "hub"
            item["brief_source_field"] = "papers.summary"
        item["summary"] = str(summary_text or "")
        item["score"] = metadata.get("relevance_score", 0)
        fulltext = detail.get("fulltext")
        if isinstance(fulltext, dict):
            item["pdf_path"] = fulltext.get("pdf_path")
            item["markdown_path"] = fulltext.get("markdown_path")
        items.append(item)
    candidate_count = int(payload.get("candidate_count") or len(items))
    return {
        **payload,
        "items": items,
        "summary": payload.get("overall_summary") or "",
        "stats": {
            "total_candidates": candidate_count,
            "selected": len(items),
        },
    }
