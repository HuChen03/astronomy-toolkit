from __future__ import annotations

import hashlib
from typing import Any


def normalize_digest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items_raw = payload.get("items")
    if not isinstance(items_raw, list):
        raise RuntimeError("literature hub digest response has no items array")
    items = [normalize_paper_item(item) for item in items_raw if isinstance(item, dict)]
    output = dict(payload)
    output["items"] = items
    return output


def normalize_paper_item(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or item.get("paper_title") or "Untitled").strip()
    paper_id = str(item.get("paper_id") or item.get("id") or "").strip() or stable_paper_key(item, title)
    abstract = str(item.get("abstract") or item.get("description") or item.get("summary") or "").strip()
    hub_brief, hub_brief_field = resolve_hub_brief(item)
    normalized = dict(item)
    normalized["paper_id"] = paper_id
    normalized["title"] = title
    normalized["abstract"] = abstract
    normalized["summary"] = hub_brief or abstract
    normalized["brief"] = hub_brief or abstract
    normalized["brief_source"] = "hub" if hub_brief else ("abstract" if abstract else "missing")
    normalized["brief_source_field"] = hub_brief_field or ("abstract" if abstract else None)
    normalized["authors"] = normalize_authors(item.get("authors"))
    normalized["doi"] = empty_to_none(item.get("doi"))
    normalized["arxiv_id"] = empty_to_none(item.get("arxiv_id") or item.get("arxivId"))
    normalized["venue"] = empty_to_none(item.get("venue") or item.get("journal"))
    normalized["published_at"] = empty_to_none(item.get("published_at") or item.get("published") or item.get("date"))
    normalized["discovered_at"] = empty_to_none(item.get("discovered_at"))
    normalized["ingested_at"] = empty_to_none(item.get("ingested_at"))
    normalized["created_at"] = empty_to_none(item.get("created_at"))
    normalized["pdf_path"] = empty_to_none(item.get("pdf_path"))
    normalized["markdown_path"] = empty_to_none(item.get("markdown_path"))
    return normalized


def resolve_hub_brief(item: dict[str, Any]) -> tuple[str, str | None]:
    for field in ("brief", "paper_brief", "summary", "paper_summary", "content_summary"):
        value = item.get(field)
        if isinstance(value, dict):
            for nested_field in ("brief", "summary", "text", "content"):
                text = str(value.get(nested_field) or "").strip()
                if text:
                    return text, f"{field}.{nested_field}"
        else:
            text = str(value or "").strip()
            if text:
                return text, field
    return "", None


def normalize_authors(value: Any) -> list[str]:
    if isinstance(value, list):
        authors: list[str] = []
        for item in value:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item or "").strip()
            if name:
                authors.append(name)
        return authors
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def empty_to_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def stable_paper_key(item: dict[str, Any], title: str) -> str:
    identity = "|".join(
        [
            str(item.get("doi") or "").casefold().strip(),
            str(item.get("arxiv_id") or item.get("arxivId") or "").casefold().strip(),
            title.casefold(),
        ]
    )
    return "sha256:" + hashlib.sha256(identity.encode("utf8")).hexdigest()
