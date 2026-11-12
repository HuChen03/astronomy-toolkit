from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .keywords import KeywordCategory


def load_taxonomy(path: Path | None, categories: list[KeywordCategory]) -> dict[str, Any]:
    if path:
        value = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(value, dict) or not isinstance(value.get("categories"), list):
            raise ValueError("taxonomy file must be an object with categories")
        return normalize_taxonomy(value)
    return normalize_taxonomy(
        {"categories": [category.to_taxonomy_category() for category in categories if category.enabled]}
    )


def classify_items(
    items: list[dict[str, Any]],
    taxonomy: dict[str, Any],
    enable_llm: bool,
    max_workers: int,
) -> list[dict[str, Any]]:
    if not enable_llm:
        return [attach_rule_based_classification(item) for item in items]

    agent = _load_classification_agent()
    if agent is None:
        return [attach_failed_llm_classification(item, taxonomy, "llm_classifier_not_available") for item in items]

    output: list[dict[str, Any] | None] = [None] * len(items)
    workers = min(max(1, max_workers), max(1, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_classify_one_with_agent, agent, item, taxonomy): index
            for index, item in enumerate(items)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                output[index] = future.result()
            except Exception as error:
                output[index] = attach_failed_llm_classification(
                    items[index], taxonomy, f"llm_classification_failed: {error}"
                )
    return [item for item in output if item is not None]


def attach_rule_based_classification(
    item: dict[str, Any],
    status: str = "success",
    reason: str | None = None,
) -> dict[str, Any]:
    categories = item.get("keyword_categories") or []
    primary = categories[0] if categories else None
    secondary = categories[1:] if len(categories) > 1 else []
    generated_keywords = list(
        dict.fromkeys(
            [
                *(item.get("recognized_keywords") or []),
                *(item.get("extracted_keywords") or []),
            ]
        )
    )
    classification = {
        "mode": "keyword",
        "status": status,
        "paper_id": item.get("paper_id"),
        "primary_category": (
            {
                "id": primary["category_id"],
                "name": primary["category"],
            }
            if primary
            else None
        ),
        "secondary_categories": [
            {"id": row["category_id"], "name": row["category"]}
            for row in secondary
        ],
        "generated_keywords": generated_keywords[:12],
        "confidence": 1.0 if primary else 0.0,
        "evidence": [
            {
                "text": ", ".join(primary.get("matched_terms", [])) if primary else item.get("title", ""),
                "reason": "keyword_rule_match" if primary else "no_keyword_rule_match",
            }
        ],
        "needs_human_review": not bool(primary),
        "review_reasons": [] if primary else ["no_keyword_category_matched"],
    }
    if reason:
        classification["fallback_reason"] = reason
        classification["review_reasons"] = list(
            dict.fromkeys([*classification["review_reasons"], reason])
        )
    output = dict(item)
    output["classification"] = classification
    return output


def _classify_one_with_agent(agent: Any, item: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "mode": "custom",
        "paper": {
            "paper_id": item.get("paper_id"),
            "title": item.get("title"),
            "brief": item.get("brief") or item.get("summary") or "",
            "abstract": item.get("abstract") or "",
            "keywords": list(
                dict.fromkeys(
                    [
                        *(item.get("recognized_keywords") or []),
                        *(item.get("extracted_keywords") or []),
                    ]
                )
            ),
            "metadata": {
                "doi": item.get("doi"),
                "arxiv_id": item.get("arxiv_id"),
                "venue": item.get("venue"),
                "published_at": item.get("published_at"),
            },
        },
        "taxonomy": taxonomy,
        "user_instruction": (
            "Choose exactly one primary category from the supplied taxonomy. Never invent a category. "
            "Use category id 'other' when evidence is insufficient. Return a confidence from 0 to 1 "
            "and concise evidence supporting the decision."
        ),
    }
    classification: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(2):
        if attempt:
            payload = {
                **payload,
                "user_instruction": (
                    payload["user_instruction"]
                    + " Your previous response was invalid. Return an existing primary_category_id exactly as written."
                ),
            }
        try:
            result = agent.classify(payload)
            raw = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            classification = validate_llm_classification(raw, taxonomy)
            break
        except Exception as error:
            last_error = error
    if classification is None:
        raise RuntimeError(f"llm_classification_invalid_after_retry: {last_error}")
    output = dict(item)
    output["classification"] = classification
    return output


def normalize_taxonomy(value: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in value.get("categories") or [] if isinstance(row, dict)]
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        category_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if not category_id or not name or category_id in seen:
            continue
        seen.add(category_id)
        normalized.append({**row, "id": category_id, "name": name})
    if "other" not in seen:
        normalized.append(
            {
                "id": "other",
                "name": "其他",
                "definition": "无法可靠归入其他预定义类别的论文。",
                "keywords": [],
            }
        )
    if not normalized:
        raise ValueError("taxonomy contains no valid categories")
    return {**value, "categories": normalized}


def validate_llm_classification(
    classification: dict[str, Any], taxonomy: dict[str, Any]
) -> dict[str, Any]:
    categories = {
        str(row["id"]): str(row["name"])
        for row in taxonomy.get("categories") or []
        if isinstance(row, dict) and row.get("id") and row.get("name")
    }
    primary = classification.get("primary_category")
    primary_id = str(
        classification.get("primary_category_id")
        or (primary.get("id") if isinstance(primary, dict) else primary or "")
    ).strip()
    if primary_id not in categories:
        raise ValueError(f"model_returned_unknown_category: {primary_id or '<empty>'}")
    secondary_raw = classification.get("secondary_category_ids") or classification.get("secondary_categories") or []
    secondary_ids: list[str] = []
    for value in secondary_raw:
        category_id = str(value.get("id") if isinstance(value, dict) else value).strip()
        if category_id in categories and category_id != primary_id and category_id not in secondary_ids:
            secondary_ids.append(category_id)
    try:
        confidence = float(classification.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        **classification,
        "mode": "llm",
        "status": "success",
        "primary_category": {"id": primary_id, "name": categories[primary_id]},
        "secondary_categories": [
            {"id": category_id, "name": categories[category_id]} for category_id in secondary_ids
        ],
        "confidence": min(1.0, max(0.0, confidence)),
        "needs_human_review": primary_id == "other" or confidence < 0.5,
    }


def attach_failed_llm_classification(
    item: dict[str, Any], taxonomy: dict[str, Any], reason: str
) -> dict[str, Any]:
    categories = {
        str(row.get("id")): str(row.get("name"))
        for row in taxonomy.get("categories") or []
        if isinstance(row, dict)
    }
    output = dict(item)
    output["classification"] = {
        "mode": "llm",
        "status": "failed",
        "primary_category": {"id": "other", "name": categories.get("other", "其他")},
        "secondary_categories": [],
        "confidence": 0.0,
        "needs_human_review": True,
        "review_reasons": [reason],
    }
    return output


def _load_classification_agent() -> Any | None:
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    return OpenAIClassificationAgent()


class OpenAIClassificationAgent:
    def __init__(self) -> None:
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.timeout = int(os.environ.get("OPENAI_TIMEOUT_S", "120"))

    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        taxonomy = payload.get("taxonomy") or {}
        category_ids = [
            str(row.get("id"))
            for row in taxonomy.get("categories") or []
            if isinstance(row, dict) and row.get("id")
        ]
        request_payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You classify academic papers. Return JSON only. Select exactly one primary_category_id "
                        "from the supplied taxonomy and never invent an id. Use other when uncertain. Also return "
                        "secondary_category_ids, confidence, reason, and evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf8"),
            headers={
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf8", errors="replace")[:1000]
            raise RuntimeError(f"classification_api_http_{error.code}: {detail}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"classification_api_unavailable: {error.reason}") from error
        try:
            content = value["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            raise RuntimeError("classification_api_returned_invalid_json") from error
        if str(result.get("primary_category_id") or "") not in category_ids:
            raise ValueError("classification_api_returned_unknown_category")
        return result
