from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import CONFIG_ROOT, KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT
from qa_knowledge_mcp.knowledge_base import doi_from_paper_key, normalize_text


TOKEN_RE = re.compile(r"[A-Za-z0-9_]{3,}|[\u3400-\u9fff]{2,}")


def resolve_locator(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.exists() else None


def portable_locator(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_sections(markdown: str) -> list[tuple[str, set[str]]]:
    sections: list[tuple[str, set[str]]] = []
    for heading in re.finditer(r"^#{1,6}\s+(.+?)\s*$", markdown, re.MULTILINE):
        name = normalize_text(heading.group(1))
        sections.append((name, set(TOKEN_RE.findall(name.lower()))))
    return sections


def best_section(sections: list[tuple[str, set[str]]], text: str) -> tuple[str | None, float]:
    tokens = set(TOKEN_RE.findall(text.lower()))
    best: tuple[str | None, float] = (None, 0.0)
    for name, heading_tokens in sections:
        overlap = len(tokens & heading_tokens)
        query_coverage = overlap / max(1, len(tokens))
        heading_coverage = overlap / max(1, len(heading_tokens))
        score = max(query_coverage, heading_coverage)
        if score > best[1]:
            best = (name, score)
    return best


def build_passages(markdown: str) -> list[tuple[str | None, str]]:
    passages: list[tuple[str | None, str]] = []
    section: str | None = None
    paragraph: list[str] = []

    def flush() -> None:
        text = normalize_text(" ".join(paragraph))
        if text:
            passages.append((section, text))
        paragraph.clear()

    for line in markdown.splitlines():
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if heading:
            flush()
            section = normalize_text(heading.group(1))
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
    flush()
    return passages


def align_evidence(
    passages: list[tuple[str | None, str]], answer: str,
) -> tuple[str, str | None, str, float]:
    normalized_answer = normalize_text(answer).lower()
    for section, passage in passages:
        normalized_passage = normalize_text(passage).lower()
        if normalized_answer and normalized_answer in normalized_passage:
            return passage, section, "exact_text_span", 1.0

    answer_tokens = set(TOKEN_RE.findall(normalized_answer))
    best: tuple[str, str | None, float] | None = None
    for section, passage in passages:
        passage_tokens = set(TOKEN_RE.findall(passage.lower()))
        overlap = len(answer_tokens & passage_tokens) / max(1, len(answer_tokens))
        if best is None or overlap > best[2]:
            best = (passage, section, overlap)
    if best and best[2] >= 0.6:
        return best[0], best[1], "paragraph_overlap", best[2]
    return answer, None, "legacy_pair", 0.0


def _prepare(source: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    papers: dict[str, dict[str, Any]] = {}
    qa_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            metadata = row.get("metadata") or {}
            legacy_doc_id = normalize_text(row.get("hash"))
            legacy_key = normalize_text(metadata.get("key"))
            doi = doi_from_paper_key(legacy_key)
            paper_id = KnowledgeStore.stable_paper_id(legacy_doc_id, doi)
            source_path = resolve_locator(metadata.get("source"))
            source_locator = portable_locator(source_path)
            papers[paper_id] = {
                "paper_id": paper_id,
                "doi": doi,
                "legacy_doc_id": legacy_doc_id,
                "legacy_key": legacy_key,
                "title": normalize_text(metadata.get("title")),
                "category": normalize_text(metadata.get("category")),
                "source_locator": source_locator,
                "match_status": "legacy_unmatched",
                "metadata": metadata,
            }
            markdown = source_path.read_text(encoding="utf-8", errors="ignore") if source_path else ""
            sections = build_sections(markdown)
            passages = build_passages(markdown)
            for pair_id, pair in enumerate(((row.get("result") or {}).get("qa_pairs") or [])):
                question = normalize_text(pair.get("question"))
                answer = normalize_text(pair.get("answer"))
                if not question or not answer:
                    continue
                qa_id = KnowledgeStore.stable_qa_id(paper_id, pair_id, question)
                version_id = KnowledgeStore.stable_qa_version_id(qa_id, answer)
                qa_rows.append({
                    "qa_id": qa_id,
                    "version_id": version_id,
                    "paper_id": paper_id,
                    "question": question,
                    "answer": answer,
                    "source_line": line_number,
                    "pair_id": pair_id,
                })
                evidence_text, aligned_section, method, confidence = align_evidence(passages, answer)
                if method == "legacy_pair":
                    aligned_section, confidence = best_section(sections, f"{question} {answer}") if sections else (None, 0.0)
                    method = "heading_overlap" if aligned_section and confidence >= 0.15 else "legacy_pair"
                quality = "section" if aligned_section and confidence >= 0.15 else "qa_pair"
                evidence_rows.append({
                    "evidence_id": f"ev:{hashlib.sha256(f'{version_id}\n{answer}'.encode()).hexdigest()[:24]}",
                    "version_id": version_id,
                    "paper_id": paper_id,
                    "evidence_text": evidence_text,
                    "section": aligned_section if quality == "section" else None,
                    "quality": quality,
                    "method": method,
                    "confidence": round(confidence, 4),
                    "source_locator": source_locator,
                })
    return papers, qa_rows, evidence_rows


def _write_batch(
    store: KnowledgeStore,
    papers: dict[str, dict[str, Any]],
    qa_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with store.connect() as connection:
        for paper in papers.values():
            connection.execute(
                """
                INSERT INTO papers(paper_id, hub_paper_id, doi, arxiv_id, legacy_doc_id, legacy_key,
                    title, category, source_locator, match_status, metadata_json, created_at, updated_at)
                VALUES (?, NULL, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    title=excluded.title, category=excluded.category,
                    source_locator=excluded.source_locator, metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    paper["paper_id"], paper["doi"], paper["legacy_doc_id"], paper["legacy_key"],
                    paper["title"], paper["category"], paper["source_locator"], paper["match_status"],
                    json.dumps(paper["metadata"], ensure_ascii=False), now, now,
                ),
            )
        for row in qa_rows:
            content_hash = hashlib.sha256(f'{row["question"]}\n{row["answer"]}'.encode()).hexdigest()
            connection.execute(
                """
                INSERT INTO qa_families(qa_id, paper_id, canonical_question, lifecycle_status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(qa_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (row["qa_id"], row["paper_id"], row["question"], now, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO qa_versions(
                    qa_version_id, qa_id, question, answer, source_pipeline, source_run_id,
                    knowledge_type, review_status, quality_score, content_hash, source_line,
                    pair_id, created_at, supersedes_version_id
                ) VALUES (?, ?, ?, ?, 'legacy_jsonl_import', NULL, 'model_summary',
                    'needs_review', 0.0, ?, ?, ?, ?, NULL)
                """,
                (
                    row["version_id"], row["qa_id"], row["question"], row["answer"],
                    content_hash, row["source_line"], row["pair_id"], now,
                ),
            )
        for row in evidence_rows:
            connection.execute(
                """
                INSERT OR REPLACE INTO evidence(
                    evidence_id, qa_version_id, paper_id, evidence_text, page_start, page_end,
                    section_path, figure_ref, table_ref, locator_quality, alignment_method,
                    alignment_confidence, review_status, reviewed_by, reviewed_at, source_locator, created_at
                ) VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL, NULL, ?, ?, ?, 'needs_review', NULL, NULL, ?, ?)
                """,
                (
                    row["evidence_id"], row["version_id"], row["paper_id"], row["evidence_text"],
                    row["section"], row["quality"], row["method"], row["confidence"],
                    row["source_locator"], now,
                ),
            )


def migrate(source: Path, store_path: Path) -> dict[str, Any]:
    papers, qa_rows, evidence_rows = _prepare(source)
    store = KnowledgeStore(store_path)
    _write_batch(store, papers, qa_rows, evidence_rows)
    categories_path = CONFIG_ROOT / "daily_categories.json"
    if categories_path.exists():
        payload = json.loads(categories_path.read_text(encoding="utf-8"))
        store.seed_taxonomy(payload.get("categories") or [], version="daily-v1")
    return {
        "source": str(source),
        "store": str(store_path),
        "papers": len(papers),
        "qa": len(qa_rows),
        "evidence": len(evidence_rows),
        "stats": store.stats(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy QA JSONL into the laboratory knowledge overlay.")
    parser.add_argument("source", type=Path, nargs="?", default=PROJECT_ROOT / "data/cosmological_simulation/generate_paper.jsonl")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    args = parser.parse_args()
    source = args.source if args.source.is_absolute() else PROJECT_ROOT / args.source
    store = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    print(json.dumps(migrate(source, store), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
