from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\u3400-\u9fff]+", re.UNICODE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+-]{2,}|[\u3400-\u9fff]{2,}")
_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "analysis",
    "based",
    "between",
    "data",
    "during",
    "from",
    "for",
    "into",
    "model",
    "paper",
    "results",
    "show",
    "study",
    "than",
    "that",
    "their",
    "these",
    "this",
    "using",
    "with",
}


@dataclass(frozen=True)
class KeywordCategory:
    id: str
    name: str
    terms: tuple[str, ...]
    weight: float = 1.0
    match_mode: str = "any"
    enabled: bool = True
    definition: str = ""

    def to_taxonomy_category(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "definition": self.definition,
            "keywords": list(self.terms),
        }


def load_keyword_categories(path: Path) -> list[KeywordCategory]:
    value = json.loads(path.read_text(encoding="utf8"))
    return parse_keyword_categories(value)


def parse_keyword_categories(value: Any) -> list[KeywordCategory]:
    rows = value.get("categories") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError("keyword file must be a list or an object with categories")
    categories: list[KeywordCategory] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        terms_raw = row.get("terms") or row.get("keywords") or []
        terms = tuple(dict.fromkeys(str(term).strip() for term in terms_raw if str(term).strip()))
        if not name or not terms:
            continue
        match_mode = str(row.get("match_mode", "any")).strip().lower()
        if match_mode not in {"any", "all"}:
            raise ValueError(f"invalid match_mode for category {name}: {match_mode}")
        categories.append(
            KeywordCategory(
                id=str(row.get("id") or slugify(name) or f"category_{index}"),
                name=name,
                terms=terms,
                weight=float(row.get("weight", 1.0)),
                match_mode=match_mode,
                enabled=bool(row.get("enabled", True)),
                definition=str(row.get("definition") or "").strip(),
            )
        )
    if not categories:
        raise ValueError("keyword file contains no valid categories")
    return categories


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u3400-\u9fff]+", "_", value.strip().lower()).strip("_")
    return slug


def normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = _PUNCTUATION_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def contains_term(text: str, term: str) -> bool:
    normalized_term = normalize_text(term)
    if not normalized_term:
        return False
    if _CJK_RE.search(normalized_term):
        return normalized_term in text
    return f" {normalized_term} " in f" {text} "


def classify_by_keywords(item: dict[str, Any], categories: list[KeywordCategory]) -> tuple[list[dict[str, Any]], float]:
    title = normalize_text(item.get("title"))
    abstract = normalize_text(item.get("abstract") or item.get("summary") or item.get("description"))
    matches: list[dict[str, Any]] = []
    total_score = 0.0
    for category in categories:
        if not category.enabled:
            continue
        matched_terms: list[str] = []
        field_score = 0.0
        for term in category.terms:
            in_title = contains_term(title, term)
            in_abstract = contains_term(abstract, term)
            if in_title or in_abstract:
                matched_terms.append(term)
                field_score += 2.0 if in_title else 1.0
        if category.match_mode == "all" and len(matched_terms) != len(category.terms):
            continue
        if not matched_terms:
            continue
        score = round(field_score * category.weight, 6)
        total_score += score
        matches.append(
            {
                "category_id": category.id,
                "category": category.name,
                "matched_terms": matched_terms,
                "match_score": score,
            }
        )
    matches.sort(key=lambda row: (-float(row["match_score"]), row["category_id"]))
    return matches, round(total_score, 6)


def extract_keywords(item: dict[str, Any], max_terms: int = 10) -> list[str]:
    text = normalize_text(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "abstract", "summary", "description")
        )
    )
    counts: dict[str, int] = {}
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).casefold()
        if token in _STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda row: (-row[1], row[0]))
    return [token for token, _ in ranked[:max_terms]]


def rerank_items(items: list[dict[str, Any]], categories: list[KeywordCategory]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for position, raw_item in enumerate(items):
        item = dict(raw_item)
        matches, keyword_score = classify_by_keywords(item, categories)
        upstream_score = safe_float(item.get("score", item.get("upstream_score", 0)))
        recognized = []
        for match in matches:
            recognized.extend(match["matched_terms"])
        item["upstream_score"] = upstream_score
        item["keyword_score"] = keyword_score
        item["priority_score"] = round(upstream_score + keyword_score, 6)
        item["keyword_matched"] = bool(matches)
        item["keyword_categories"] = matches
        item["recognized_keywords"] = list(dict.fromkeys(recognized))
        item["extracted_keywords"] = extract_keywords(item)
        item["_upstream_position"] = position
        ranked.append(item)
    ranked.sort(
        key=lambda item: (
            not item["keyword_matched"],
            -safe_float(item["keyword_score"]),
            -safe_float(item["upstream_score"]),
            item["_upstream_position"],
        )
    )
    for item in ranked:
        item.pop("_upstream_position", None)
    return ranked


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
