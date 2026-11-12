from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from lab_knowledge_platform.paths import KNOWLEDGE_OVERLAY_DB, PROJECT_ROOT


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}, text
    values: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip().strip('"\'')
    return values, parts[2].lstrip()


def parse_sections(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = re.sub(r"^\d+(?:\.\d+)*[.、]?\s*", "", match.group(2)).strip().lower()
        body = text[match.end():end].strip()
        sections[key] = body
    return sections


def section_value(sections: dict[str, str], *terms: str) -> str:
    for key, value in sections.items():
        if any(term in key for term in terms):
            return value
    return ""


def doi_from_filename(path: Path) -> str | None:
    name = path.name.removesuffix(".knowledge.md")
    parts = name.split("_", 1)
    if len(parts) != 2 or not parts[1].startswith("10."):
        return None
    return parts[1].replace("_", "/", 1)


def document_id(root: Path, path: Path, source_type: str) -> str:
    relative = path.relative_to(root).as_posix()
    return f"{source_type}:{hashlib.sha256(relative.encode()).hexdigest()[:24]}"


def import_structured(root: Path, store_path: Path) -> dict[str, Any]:
    store = KnowledgeStore(store_path)
    counts = {"reading_cards": 0, "topics": 0, "decisions": 0, "paper_linked": 0}
    for path in sorted(root.rglob("*.md")):
        if path.name in {"README.md"}:
            continue
        body = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not body:
            continue
        front, content = parse_front_matter(body)
        relative = path.relative_to(root).as_posix()
        if relative.startswith("topics/") or "/topics/" in f"/{relative}":
            source_type = "topic"
        elif relative.startswith("decisions/") or "/decisions/" in f"/{relative}":
            source_type = "decision"
        else:
            source_type = "reading_card"
        paper = store.resolve_paper(doi_from_filename(path) or "")
        doc_id = document_id(root, path, source_type)
        store.upsert_document(document_id=doc_id, paper_id=paper["paper_id"] if paper else None, source_type=source_type, title=front.get("title") or path.stem, body=body, review_status="legacy_unreviewed", metadata={"source_artifact": relative, "parser": "structured_knowledge_v1"})
        sections = parse_sections(content)
        if source_type == "reading_card":
            store.upsert_reading_card({
                "card_id": doc_id,
                "paper_id": paper["paper_id"] if paper else None,
                "source_document_id": doc_id,
                "template_version": "reading-card-v1",
                "reader": front.get("reader"),
                "status": "draft_ai",
                "author_claims": section_value(sections, "一句话核心结论", "作者主张", "核心结论"),
                "reader_interpretation": section_value(sections, "阅读者解释", "解读"),
                "lab_consensus": section_value(sections, "实验室共识"),
                "problem": section_value(sections, "研究问题", "科学问题", "研究背景"),
                "contributions": section_value(sections, "主要贡献", "贡献"),
                "methods": section_value(sections, "方法与技术路线", "方法", "数值方法"),
                "datasets": section_value(sections, "数据", "模拟设置", "数据集"),
                "main_results": section_value(sections, "关键结果", "主要结果", "结果"),
                "limitations": section_value(sections, "局限", "不足", "开放问题"),
                "reproducibility": section_value(sections, "复现", "代码", "可复现"),
                "lab_relevance": section_value(sections, "实验室相关性", "项目影响"),
                "reusable_assets": section_value(sections, "可复用", "资源"),
                "metadata": {"source_artifact": relative},
            })
            counts["reading_cards"] += 1
        elif source_type == "topic":
            topic_id = front.get("id") or path.stem
            store.upsert_topic({"topic_id": topic_id, "source_document_id": doc_id, "title": front.get("title") or path.stem, "maintainer": front.get("maintainer"), "status": front.get("status") or "active", "last_reviewed": front.get("last_reviewed"), "current_consensus": section_value(sections, "当前共识", "共识"), "supporting_evidence": section_value(sections, "支持证据"), "conflicting_evidence": section_value(sections, "冲突证据"), "open_questions": section_value(sections, "开放问题"), "project_impact": section_value(sections, "项目影响"), "metadata": {"source_artifact": relative}})
            counts["topics"] += 1
        else:
            decision_id = front.get("id") or path.stem
            store.upsert_decision({"decision_id": decision_id, "source_document_id": doc_id, "title": front.get("title") or path.stem, "maintainer": front.get("maintainer"), "status": front.get("status") or "draft", "decision": section_value(sections, "决策", "结论"), "rationale": section_value(sections, "理由", "依据", "决策依据"), "alternatives": section_value(sections, "替代方案", "备选"), "impact": section_value(sections, "影响"), "evidence_summary": section_value(sections, "证据", "支持证据"), "decided_at": front.get("decided_at"), "metadata": {"source_artifact": relative}})
            counts["decisions"] += 1
        if paper:
            counts["paper_linked"] += 1
    return {**counts, "stats": store.stats()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse Markdown into structured reading cards, topics, and decisions.")
    parser.add_argument("root", type=Path, nargs="?", default=PROJECT_ROOT / "data/knowledge_acquisition/paper_library_1_knowledge")
    parser.add_argument("--store", type=Path, default=KNOWLEDGE_OVERLAY_DB)
    args = parser.parse_args()
    root = args.root if args.root.is_absolute() else PROJECT_ROOT / args.root
    store = args.store if args.store.is_absolute() else PROJECT_ROOT / args.store
    print(json.dumps(import_structured(root, store), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
