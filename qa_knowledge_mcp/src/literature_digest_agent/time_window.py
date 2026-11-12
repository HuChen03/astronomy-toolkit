from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DigestWindow:
    start: datetime
    end: datetime
    timezone: str
    source: str = "local"

    @property
    def business_date(self) -> str:
        return self.end.date().isoformat()

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "timezone": self.timezone,
            "source": self.source,
        }


def daily_window(
    timezone_name: str,
    *,
    business_date: str | None = None,
    cutoff_hour: int = 8,
    now: datetime | None = None,
) -> DigestWindow:
    timezone = ZoneInfo(timezone_name)
    current = now.astimezone(timezone) if now else datetime.now(timezone)
    if business_date:
        end_date = date.fromisoformat(business_date)
    else:
        end_date = current.date() if current.time() >= time(cutoff_hour) else current.date() - timedelta(days=1)
    end = datetime.combine(end_date, time(cutoff_hour), timezone)
    return DigestWindow(
        start=end - timedelta(hours=24),
        end=end,
        timezone=timezone_name,
    )


def window_from_payload(payload: dict[str, Any], fallback: DigestWindow) -> DigestWindow:
    candidates = [payload.get("window"), payload.get("time_window"), payload.get("range")]
    for value in candidates:
        if not isinstance(value, dict):
            continue
        start = parse_timestamp(value.get("start") or value.get("start_at") or value.get("from"), fallback.timezone)
        end = parse_timestamp(value.get("end") or value.get("end_at") or value.get("to"), fallback.timezone)
        if start and end and start < end:
            return DigestWindow(start=start, end=end, timezone=fallback.timezone, source="hub")
    return fallback


def parse_timestamp(value: Any, timezone_name: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    timezone = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def paper_timestamp(item: dict[str, Any], timezone_name: str) -> tuple[datetime | None, str | None]:
    for field in ("discovered_at", "ingested_at", "created_at", "published_at"):
        parsed = parse_timestamp(item.get(field), timezone_name)
        if parsed:
            return parsed, field
    return None, None
