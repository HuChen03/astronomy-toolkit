from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .classifier import load_taxonomy
from .config import CatalogSettings
from .hub_client import LiteratureHubClient
from .keywords import load_keyword_categories
from .repository import DigestRepository
from .service import process_digest_payload
from .time_window import DigestWindow, daily_window, paper_timestamp, window_from_payload


def previous_business_date(timezone_name: str) -> str:
    return daily_window(timezone_name).business_date


def refresh_daily_catalog(
    settings: CatalogSettings,
    *,
    business_date: str | None = None,
    force: bool = False,
    skip_automation_check: bool = False,
) -> dict[str, Any]:
    requested_window = daily_window(
        settings.timezone,
        business_date=business_date,
        cutoff_hour=settings.cutoff_hour,
    )
    target_date = requested_window.business_date
    validate_date(target_date)
    repository = DigestRepository(settings.database_path)
    if not force:
        existing = repository.get_sync_status(target_date, settings.discipline)
        if existing.get("status") == "published":
            return {**existing, "reused": True}

    started_at = datetime.now(ZoneInfo(settings.timezone)).isoformat()
    categories = load_keyword_categories(settings.keywords_path)
    taxonomy = load_taxonomy(settings.taxonomy_path, categories)
    config_version = keyword_config_version(settings.keywords_path)
    client = LiteratureHubClient(settings.hub)
    automation_jobs: list[dict[str, Any]] = []
    automation_error: str | None = None
    try:
        automation_payload = client.get_automation_jobs()
        automation_jobs = [
            job for job in automation_payload.get("jobs") or [] if isinstance(job, dict)
        ]
    except Exception as error:
        automation_error = str(error)

    running_jobs = [
        str(job.get("job_id") or job.get("name") or job.get("id"))
        for job in automation_jobs
        if job.get("status") == "active" and job.get("last_run_status") == "running"
    ]
    if running_jobs and not skip_automation_check:
        return {
            "status": "deferred",
            "date": target_date,
            "discipline": settings.discipline,
            "reason": "automation_jobs_running",
            "running_jobs": running_jobs,
            "automation_jobs": automation_jobs,
            "window": requested_window.to_dict(),
        }

    try:
        payload = fetch_window_digest(client, settings, requested_window)
        if payload.get("status") == "building":
            return {
                "status": "deferred",
                "date": target_date,
                "discipline": settings.discipline,
                "reason": "daily_digest_building",
                "retry_after_seconds": payload.get("retry_after_seconds", 30),
                "cache_key": payload.get("cache_key"),
                "automation_jobs": automation_jobs,
                "window": requested_window.to_dict(),
            }
        effective_window = window_from_payload(payload, requested_window)
        payload, discovery_filter = filter_digest_by_window(payload, effective_window)
        if discovery_filter["source_items"] and not discovery_filter["timestamped_items"]:
            return {
                "status": "deferred",
                "date": target_date,
                "discipline": settings.discipline,
                "reason": "discovery_timestamp_unavailable",
                "message": (
                    "The literature hub returned papers without a usable discovery, ingestion, creation, "
                    "or publication timestamp. No near-24-hour snapshot was published."
                ),
                "source_items": discovery_filter["source_items"],
                "automation_jobs": automation_jobs,
                "window": effective_window.to_dict(),
            }
        digest = process_digest_payload(
            payload,
            categories,
            taxonomy=taxonomy,
            enable_llm_classification=settings.enable_llm_classification,
            max_workers=settings.max_workers,
        )
        total_candidates = discovery_filter["matched_items"]
        fetched_count = len(digest.get("items") or [])
        completeness = "complete" if fetched_count >= total_candidates else "partial"
        result = repository.publish(
            digest,
            business_date=target_date,
            discipline=settings.discipline,
            completeness=completeness,
            total_candidates=total_candidates,
            tag_config_version=config_version,
            started_at=started_at,
            automation_jobs=automation_jobs,
            window=effective_window.to_dict(),
            source_count=int(discovery_filter["source_items"]),
            filtered_count=int(discovery_filter["matched_items"]),
        )
        result["reused"] = False
        result["discovery_filter"] = discovery_filter
        result["window"] = effective_window.to_dict()
        if automation_error:
            result["automation_check_warning"] = automation_error
        return result
    except Exception as error:
        repository.record_failure(
            business_date=target_date,
            discipline=settings.discipline,
            started_at=started_at,
            tag_config_version=config_version,
            error_message=str(error),
            automation_jobs=automation_jobs,
        )
        raise


def keyword_config_version(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest[:16]}"


def fetch_window_digest(
    client: LiteratureHubClient,
    settings: CatalogSettings,
    window: DigestWindow,
) -> dict[str, Any]:
    common = {
        "discipline": settings.discipline,
        "limit": settings.fetch_limit,
        "window_start": window.start.isoformat(),
        "window_end": window.end.isoformat(),
    }
    current = client.fetch_daily_digest(digest_date=window.business_date, **common)
    if current.get("status") == "building" or has_explicit_window(current):
        return current
    previous_date = (window.end.date() - timedelta(days=1)).isoformat()
    if previous_date == window.business_date:
        return current
    previous = client.fetch_daily_digest(digest_date=previous_date, **common)
    if previous.get("status") == "building":
        return previous
    items = [
        item
        for payload in (previous, current)
        for item in payload.get("items") or []
        if isinstance(item, dict)
    ]
    return {
        **current,
        "items": items,
        "summary": current.get("summary") or previous.get("summary") or "",
        "stats": {
            **(current.get("stats") or {}),
            "source_responses": 2,
            "source_items": len(items),
        },
        "window_fetch_mode": "two_calendar_days",
    }


def has_explicit_window(payload: dict[str, Any]) -> bool:
    return any(isinstance(payload.get(field), dict) for field in ("window", "time_window", "range"))


def validate_date(value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("date must use YYYY-MM-DD format") from error


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def filter_digest_by_discovery_date(
    payload: dict[str, Any],
    target_date: str,
) -> tuple[dict[str, Any], dict[str, int | str]]:
    timezone_name = "UTC"
    start = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=ZoneInfo(timezone_name))
    return filter_digest_by_window(
        payload,
        DigestWindow(start=start, end=start.replace(hour=23, minute=59, second=59, microsecond=999999), timezone=timezone_name),
    )


def filter_digest_by_window(
    payload: dict[str, Any],
    window: DigestWindow,
) -> tuple[dict[str, Any], dict[str, int | str]]:
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    timestamped: list[dict[str, Any]] = []
    matched_by_id: dict[str, dict[str, Any]] = {}
    timestamp_fields: dict[str, int] = {}
    for item in items:
        timestamp, field = paper_timestamp(item, window.timezone)
        if not timestamp or not field:
            continue
        timestamped.append(item)
        timestamp_fields[field] = timestamp_fields.get(field, 0) + 1
        if window.start <= timestamp < window.end:
            identity = str(
                item.get("paper_id")
                or item.get("doi")
                or item.get("arxiv_id")
                or item.get("title")
                or len(matched_by_id)
            ).casefold()
            matched_by_id.setdefault(identity, item)
    matched = list(matched_by_id.values())
    output = dict(payload)
    output["items"] = matched
    output["stats"] = {
        **(payload.get("stats") or {}),
        "source_items": len(items),
        "timestamped_items": len(timestamped),
        "total_candidates": len(matched),
        "selected": len(matched),
    }
    return output, {
        "mode": "near_24_hours",
        "target_date": window.business_date,
        "window_start": window.start.isoformat(),
        "window_end": window.end.isoformat(),
        "window_source": window.source,
        "source_items": len(items),
        "timestamped_items": len(timestamped),
        "matched_items": len(matched),
        "excluded_items": len(items) - len(matched),
        "timestamp_fields": timestamp_fields,
    }


def timestamp_date(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""
