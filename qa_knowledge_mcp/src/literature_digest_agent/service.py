from __future__ import annotations

from typing import Any

from .classifier import classify_items
from .keywords import KeywordCategory, rerank_items
from .normalizer import normalize_digest_payload


def process_digest_payload(
    payload: dict[str, Any],
    categories: list[KeywordCategory],
    taxonomy: dict[str, Any] | None = None,
    enable_llm_classification: bool = False,
    max_workers: int = 4,
) -> dict[str, Any]:
    active_categories = [category for category in categories if category.enabled]
    effective_taxonomy = taxonomy or {
        "categories": [category.to_taxonomy_category() for category in active_categories]
    }
    digest = normalize_digest_payload(payload)
    ranked = rerank_items(digest["items"], categories)
    classified = classify_items(
        ranked,
        taxonomy=effective_taxonomy,
        enable_llm=enable_llm_classification,
        max_workers=max_workers,
    )
    digest["items"] = [attach_brief(attach_classification_categories(item)) for item in classified]
    digest["keyword_agent"] = {
        "keyword_categories": len(active_categories),
        "matched_items": sum(1 for item in classified if item.get("keyword_matched")),
        "llm_classification_enabled": enable_llm_classification,
        "taxonomy_categories": len(effective_taxonomy.get("categories") or []),
    }
    return digest


def attach_classification_categories(item: dict[str, Any]) -> dict[str, Any]:
    classification = item.get("classification") or {}
    primary = classification.get("primary_category")
    secondary = classification.get("secondary_categories") or []
    categories = [primary, *secondary] if isinstance(primary, dict) else list(secondary)
    if not categories:
        return dict(item)
    confidence = float(classification.get("confidence") or 0.0)
    output = dict(item)
    output["keyword_matched"] = primary.get("id") != "other" if isinstance(primary, dict) else False
    output["keyword_score"] = confidence
    output["priority_score"] = max(float(item.get("priority_score") or 0), confidence)
    output["keyword_categories"] = [
        {
            "category_id": row.get("id"),
            "category": row.get("name"),
            "matched_terms": [],
            "match_score": confidence if index == 0 else max(0.0, confidence - 0.1),
            "classification_source": classification.get("mode", "llm"),
        }
        for index, row in enumerate(categories)
        if isinstance(row, dict) and row.get("id") and row.get("name")
    ]
    return output


def attach_brief(item: dict[str, Any]) -> dict[str, Any]:
    output = dict(item)
    if item.get("brief"):
        return output
    abstract = str(item.get("abstract") or "").strip()
    output["brief"] = abstract
    output["brief_source"] = "abstract" if abstract else "missing"
    output["brief_source_field"] = "abstract" if abstract else None
    return output
