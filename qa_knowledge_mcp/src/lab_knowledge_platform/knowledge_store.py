from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 5
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u3400-\u9fff]{2,}")


class KnowledgeStore:
    """SQLite overlay for canonical papers, derived knowledge, and provenance."""

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            connection = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            if not self.read_only:
                connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    hub_paper_id TEXT,
                    doi TEXT,
                    arxiv_id TEXT,
                    legacy_doc_id TEXT NOT NULL,
                    legacy_key TEXT,
                    title TEXT NOT NULL,
                    category TEXT,
                    source_locator TEXT,
                    match_status TEXT NOT NULL,
                    match_method TEXT,
                    match_confidence REAL,
                    matched_at TEXT,
                    reviewed_by TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_legacy_doc ON papers(legacy_doc_id);
                CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
                CREATE TABLE IF NOT EXISTS qa_families (
                    qa_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                    canonical_question TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS qa_versions (
                    qa_version_id TEXT PRIMARY KEY,
                    qa_id TEXT NOT NULL REFERENCES qa_families(qa_id),
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    source_pipeline TEXT NOT NULL,
                    source_run_id TEXT,
                    knowledge_type TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    quality_score REAL NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_line INTEGER,
                    pair_id INTEGER,
                    created_at TEXT NOT NULL,
                    supersedes_version_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_qa_versions_active
                    ON qa_versions(review_status, knowledge_type);
                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    qa_version_id TEXT NOT NULL REFERENCES qa_versions(qa_version_id),
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                    evidence_text TEXT NOT NULL,
                    page_start INTEGER,
                    page_end INTEGER,
                    section_path TEXT,
                    figure_ref TEXT,
                    table_ref TEXT,
                    locator_quality TEXT NOT NULL,
                    alignment_method TEXT NOT NULL,
                    alignment_confidence REAL NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'needs_review',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    source_locator TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_paper ON evidence(paper_id, locator_quality);
                CREATE TABLE IF NOT EXISTS taxonomy_nodes (
                    node_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    parent_id TEXT,
                    node_type TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_taxonomy (
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                    node_id TEXT NOT NULL REFERENCES taxonomy_nodes(node_id),
                    assignment_type TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    PRIMARY KEY (paper_id, node_id)
                );
                CREATE TABLE IF NOT EXISTS processing_tasks (
                    task_id TEXT PRIMARY KEY,
                    paper_id TEXT,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    input_hash TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    available_at TEXT,
                    locked_at TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_versions (
                    index_version TEXT PRIMARY KEY,
                    source_hash TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published_at TEXT
                );
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    paper_id TEXT REFERENCES papers(paper_id),
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_documents_type
                    ON knowledge_documents(source_type, status, review_status);
                CREATE TABLE IF NOT EXISTS document_evidence (
                    document_id TEXT NOT NULL REFERENCES knowledge_documents(document_id),
                    evidence_id TEXT NOT NULL REFERENCES evidence(evidence_id),
                    PRIMARY KEY (document_id, evidence_id)
                );
                CREATE TABLE IF NOT EXISTS paper_relations (
                    relation_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
                    relation_type TEXT NOT NULL,
                    related_identifier TEXT,
                    related_doi TEXT,
                    related_title TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_relations_paper ON paper_relations(paper_id, relation_type);
                CREATE TABLE IF NOT EXISTS reading_cards (
                    card_id TEXT PRIMARY KEY,
                    paper_id TEXT REFERENCES papers(paper_id),
                    source_document_id TEXT REFERENCES knowledge_documents(document_id),
                    template_version TEXT NOT NULL,
                    reader TEXT,
                    status TEXT NOT NULL,
                    author_claims TEXT NOT NULL,
                    reader_interpretation TEXT NOT NULL,
                    lab_consensus TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    contributions TEXT NOT NULL,
                    methods TEXT NOT NULL,
                    datasets TEXT NOT NULL,
                    main_results TEXT NOT NULL,
                    limitations TEXT NOT NULL,
                    reproducibility TEXT NOT NULL,
                    lab_relevance TEXT NOT NULL,
                    reusable_assets TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS topics (
                    topic_id TEXT PRIMARY KEY,
                    source_document_id TEXT REFERENCES knowledge_documents(document_id),
                    title TEXT NOT NULL,
                    maintainer TEXT,
                    status TEXT NOT NULL,
                    last_reviewed TEXT,
                    current_consensus TEXT NOT NULL,
                    supporting_evidence TEXT NOT NULL,
                    conflicting_evidence TEXT NOT NULL,
                    open_questions TEXT NOT NULL,
                    project_impact TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    source_document_id TEXT REFERENCES knowledge_documents(document_id),
                    title TEXT NOT NULL,
                    maintainer TEXT,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    alternatives TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    evidence_summary TEXT NOT NULL,
                    decided_at TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            for column, definition in (
                ("max_attempts", "INTEGER NOT NULL DEFAULT 3"),
                ("payload_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("result_json", "TEXT"),
                ("available_at", "TEXT"),
                ("locked_at", "TEXT"),
            ):
                existing = {row[1] for row in connection.execute("PRAGMA table_info(processing_tasks)")}
                if column not in existing:
                    connection.execute(f"ALTER TABLE processing_tasks ADD COLUMN {column} {definition}")
            paper_columns = {row[1] for row in connection.execute("PRAGMA table_info(papers)")}
            for column, definition in (("match_method", "TEXT"), ("match_confidence", "REAL"), ("matched_at", "TEXT"), ("reviewed_by", "TEXT")):
                if column not in paper_columns:
                    connection.execute(f"ALTER TABLE papers ADD COLUMN {column} {definition}")
            evidence_columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence)")}
            for column, definition in (("review_status", "TEXT NOT NULL DEFAULT 'needs_review'"), ("reviewed_by", "TEXT"), ("reviewed_at", "TEXT")):
                if column not in evidence_columns:
                    connection.execute(f"ALTER TABLE evidence ADD COLUMN {column} {definition}")
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def stable_paper_id(legacy_doc_id: str, doi: str | None) -> str:
        if doi:
            return f"doi:{doi.lower()}"
        return f"legacy:{legacy_doc_id}"

    @staticmethod
    def stable_qa_id(paper_id: str, pair_id: int, question: str) -> str:
        digest = hashlib.sha256(f"{paper_id}\n{pair_id}\n{question}".encode()).hexdigest()[:24]
        return f"qa:{digest}"

    @staticmethod
    def stable_qa_version_id(qa_id: str, answer: str) -> str:
        digest = hashlib.sha256(f"{qa_id}\n{answer}".encode()).hexdigest()[:24]
        return f"qav:{digest}"

    def upsert_paper(self, paper: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        paper_id = str(paper["paper_id"])
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO papers(
                    paper_id, hub_paper_id, doi, arxiv_id, legacy_doc_id, legacy_key,
                    title, category, source_locator, match_status, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    hub_paper_id=excluded.hub_paper_id,
                    doi=excluded.doi,
                    arxiv_id=excluded.arxiv_id,
                    title=excluded.title,
                    category=excluded.category,
                    source_locator=excluded.source_locator,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    paper_id,
                    paper.get("hub_paper_id"),
                    paper.get("doi"),
                    paper.get("arxiv_id"),
                    paper["legacy_doc_id"],
                    paper.get("legacy_key"),
                    paper.get("title") or "",
                    paper.get("category"),
                    paper.get("source_locator"),
                    paper.get("match_status") or "legacy_unmatched",
                    json.dumps(paper.get("metadata") or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return paper_id

    def upsert_qa(
        self,
        *,
        paper_id: str,
        pair_id: int,
        question: str,
        answer: str,
        source_line: int,
        source_pipeline: str = "legacy_jsonl_import",
        knowledge_type: str = "model_summary",
        review_status: str = "needs_review",
        quality_score: float = 0.0,
    ) -> tuple[str, str]:
        now = datetime.now(timezone.utc).isoformat()
        qa_id = self.stable_qa_id(paper_id, pair_id, question)
        version_id = self.stable_qa_version_id(qa_id, answer)
        content_hash = hashlib.sha256(f"{question}\n{answer}".encode()).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO qa_families(qa_id, paper_id, canonical_question, lifecycle_status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(qa_id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (qa_id, paper_id, question, now, now),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO qa_versions(
                    qa_version_id, qa_id, question, answer, source_pipeline, source_run_id,
                    knowledge_type, review_status, quality_score, content_hash, source_line,
                    pair_id, created_at, supersedes_version_id
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    version_id,
                    qa_id,
                    question,
                    answer,
                    source_pipeline,
                    knowledge_type,
                    review_status,
                    quality_score,
                    content_hash,
                    source_line,
                    pair_id,
                    now,
                ),
            )
        return qa_id, version_id

    def add_evidence(
        self,
        *,
        qa_version_id: str,
        paper_id: str,
        evidence_text: str,
        locator_quality: str,
        alignment_method: str,
        alignment_confidence: float,
        source_locator: str | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        section_path: str | None = None,
        figure_ref: str | None = None,
        table_ref: str | None = None,
        review_status: str = "needs_review",
        reviewed_by: str | None = None,
    ) -> str:
        evidence_id = f"ev:{hashlib.sha256(f'{qa_version_id}\n{evidence_text}'.encode()).hexdigest()[:24]}"
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO evidence(
                    evidence_id, qa_version_id, paper_id, evidence_text, page_start, page_end,
                    section_path, figure_ref, table_ref, locator_quality, alignment_method,
                    alignment_confidence, review_status, reviewed_by, reviewed_at, source_locator, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    qa_version_id,
                    paper_id,
                    evidence_text,
                    page_start,
                    page_end,
                    section_path,
                    figure_ref,
                    table_ref,
                    locator_quality,
                    alignment_method,
                    alignment_confidence,
                    review_status,
                    reviewed_by,
                    datetime.now(timezone.utc).isoformat() if reviewed_by else None,
                    source_locator,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return evidence_id

    def review_evidence(self, evidence_id: str, *, decision: str, actor: str) -> bool:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        status = "reviewed" if decision == "approve" else "rejected"
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE evidence SET review_status=?, reviewed_by=?, reviewed_at=? WHERE evidence_id=?",
                (status, actor, datetime.now(timezone.utc).isoformat(), evidence_id),
            )
        return cursor.rowcount > 0

    def upsert_document(
        self,
        *,
        document_id: str,
        source_type: str,
        title: str,
        body: str,
        paper_id: str | None = None,
        status: str = "active",
        review_status: str = "needs_review",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents(
                    document_id, paper_id, source_type, title, body, status,
                    review_status, content_hash, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    paper_id=excluded.paper_id, source_type=excluded.source_type,
                    title=excluded.title, body=excluded.body, status=excluded.status,
                    review_status=excluded.review_status, content_hash=excluded.content_hash,
                    metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
                """,
                (document_id, paper_id, source_type, title, body, status, review_status,
                 content_hash, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return document_id

    def link_document_evidence(self, document_id: str, evidence_ids: list[str]) -> int:
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO document_evidence(document_id, evidence_id) VALUES (?, ?)",
                [(document_id, evidence_id) for evidence_id in evidence_ids],
            )
        return len(evidence_ids)

    def search_documents(self, query: str, *, source_types: set[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        tokens = set(TOKEN_RE.findall(query.lower()))
        if not tokens:
            return []
        clauses = ["status='active'"]
        params: list[Any] = []
        if source_types:
            clauses.append("source_type IN (" + ",".join("?" for _ in source_types) + ")")
            params.extend(sorted(source_types))
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_documents WHERE " + " AND ".join(clauses), params
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            haystack = set(TOKEN_RE.findall(f"{item['title']} {item['body']}".lower()))
            overlap = len(tokens & haystack)
            if overlap:
                item["score"] = overlap / max(1, len(tokens))
                item["metadata"] = json.loads(item.pop("metadata_json"))
                item["excerpt"] = item.pop("body")[:600]
                results.append(item)
        results.sort(key=lambda item: (-item["score"], item["document_id"]))
        return results[: max(1, min(limit, 100))]

    def search_evidence(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        tokens = set(TOKEN_RE.findall(query.lower()))
        if not tokens:
            return []
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*, q.question, q.answer, q.knowledge_type, q.review_status,
                       p.title, p.doi
                FROM evidence e
                JOIN qa_versions q ON q.qa_version_id=e.qa_version_id
                JOIN papers p ON p.paper_id=e.paper_id
                """
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            haystack = set(TOKEN_RE.findall(f"{item['question']} {item['evidence_text']}".lower()))
            overlap = len(tokens & haystack)
            if overlap:
                item["score"] = overlap / max(1, len(tokens))
                results.append(item)
        results.sort(key=lambda item: (-item["score"], item["evidence_id"]))
        return results[: max(1, min(limit, 100))]

    def enqueue_task(
        self, *, stage: str, idempotency_key: str, input_hash: str,
        paper_id: str | None = None, payload: dict[str, Any] | None = None,
        config_version: str = "v1", max_attempts: int = 3,
    ) -> str:
        task_id = "task:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO processing_tasks(
                    task_id, paper_id, stage, status, idempotency_key, input_hash,
                    config_version, attempts, max_attempts, payload_json, result_json,
                    available_at, locked_at, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, NULL, ?, NULL, NULL, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (task_id, paper_id, stage, idempotency_key, input_hash, config_version,
                 max(1, max_attempts), json.dumps(payload or {}, ensure_ascii=False), now, now, now),
            )
        return task_id

    def claim_task(self, *, stage: str | None = None) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = "SELECT * FROM processing_tasks WHERE status='queued' AND (available_at IS NULL OR available_at<=?)"
            params: list[Any] = [now]
            if stage:
                query += " AND stage=?"
                params.append(stage)
            query += " ORDER BY created_at, task_id LIMIT 1"
            row = connection.execute(query, params).fetchone()
            if not row:
                return None
            connection.execute(
                "UPDATE processing_tasks SET status='running', attempts=attempts+1, locked_at=?, updated_at=? WHERE task_id=?",
                (now, now, row["task_id"]),
            )
            result = dict(row)
            result["status"] = "running"
            result["attempts"] = int(result["attempts"]) + 1
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def finish_task(self, task_id: str, *, result: dict[str, Any] | None = None) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE processing_tasks SET status='succeeded', result_json=?, updated_at=?, locked_at=NULL WHERE task_id=? AND status='running'",
                (json.dumps(result or {}, ensure_ascii=False), datetime.now(timezone.utc).isoformat(), task_id),
            )
        return cursor.rowcount > 0

    def fail_task(self, task_id: str, error_message: str, *, retry_delay_seconds: int | None = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            row = connection.execute("SELECT attempts, max_attempts FROM processing_tasks WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                return False
            status = "queued" if row["attempts"] < row["max_attempts"] else "dead_letter"
            delay = retry_delay_seconds if retry_delay_seconds is not None else min(3600, 60 * (2 ** max(0, int(row["attempts"]) - 1)))
            available_at = (datetime.now(timezone.utc) + timedelta(seconds=max(0, delay))).isoformat() if status == "queued" else None
            cursor = connection.execute(
                "UPDATE processing_tasks SET status=?, error_message=?, available_at=?, updated_at=?, locked_at=NULL WHERE task_id=? AND status='running'",
                (status, error_message[:2000], available_at, now, task_id),
            )
        return cursor.rowcount > 0

    def list_tasks(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM processing_tasks WHERE status=? ORDER BY updated_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM processing_tasks ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def seed_taxonomy(self, categories: list[dict[str, Any]], *, version: str = "v1") -> int:
        with self.connect() as connection:
            for category in categories:
                node_id = str(category.get("id") or "").strip()
                if not node_id:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO taxonomy_nodes(
                        node_id, name, parent_id, node_type, version, status, metadata_json
                    ) VALUES (?, ?, NULL, 'research_direction', ?, 'active', ?)
                    """,
                    (node_id, category.get("name") or node_id, version, json.dumps(category, ensure_ascii=False)),
                )
        return len([row for row in categories if row.get("id")])

    def stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            result = {}
            for table in ("papers", "qa_families", "qa_versions", "evidence", "taxonomy_nodes", "knowledge_documents", "reading_cards", "topics", "decisions", "paper_relations", "processing_tasks", "index_versions"):
                result[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            return {"schema_version": SCHEMA_VERSION, **result}

    def replace_paper_relations(self, paper_id: str, relation_type: str, rows: list[dict[str, Any]], *, source: str = "literature_hub") -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute("DELETE FROM paper_relations WHERE paper_id=? AND relation_type=?", (paper_id, relation_type))
            for index, row in enumerate(rows):
                related_identifier = str(row.get("id") or row.get("paper_id") or row.get("arxiv_id") or row.get("doi") or f"row-{index}")
                relation_id = "rel:" + hashlib.sha256(f"{paper_id}\n{relation_type}\n{related_identifier}".encode()).hexdigest()[:24]
                connection.execute(
                    """INSERT INTO paper_relations(relation_id,paper_id,relation_type,related_identifier,related_doi,related_title,metadata_json,source,fetched_at)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (relation_id, paper_id, relation_type, related_identifier, row.get("doi"), row.get("title") or "", json.dumps(row, ensure_ascii=False), source, now),
                )
        return len(rows)

    def upsert_reading_card(self, card: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        fields = ("card_id", "paper_id", "source_document_id", "template_version", "reader", "status", "author_claims", "reader_interpretation", "lab_consensus", "problem", "contributions", "methods", "datasets", "main_results", "limitations", "reproducibility", "lab_relevance", "reusable_assets", "metadata_json", "created_at", "updated_at", "reviewed_at")
        values = [card.get(key) for key in fields]
        values[18] = json.dumps(card.get("metadata") or {}, ensure_ascii=False)
        values[19] = values[20] = now
        with self.connect() as connection:
            connection.execute(
                f"INSERT INTO reading_cards({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(card_id) DO UPDATE SET " + ','.join(f"{key}=excluded.{key}" for key in fields[1:] if key != "created_at"), values,
            )
        return str(card["card_id"])

    def upsert_topic(self, topic: dict[str, Any]) -> str:
        return self._upsert_synthesis("topics", topic, ("topic_id", "source_document_id", "title", "maintainer", "status", "last_reviewed", "current_consensus", "supporting_evidence", "conflicting_evidence", "open_questions", "project_impact", "metadata_json", "created_at", "updated_at"))

    def upsert_decision(self, decision: dict[str, Any]) -> str:
        return self._upsert_synthesis("decisions", decision, ("decision_id", "source_document_id", "title", "maintainer", "status", "decision", "rationale", "alternatives", "impact", "evidence_summary", "decided_at", "metadata_json", "created_at", "updated_at"))

    def _upsert_synthesis(self, table: str, item: dict[str, Any], fields: tuple[str, ...]) -> str:
        now = datetime.now(timezone.utc).isoformat()
        values = [item.get(key) for key in fields]
        metadata_index = fields.index("metadata_json")
        values[metadata_index] = json.dumps(item.get("metadata") or {}, ensure_ascii=False)
        for key in ("created_at", "updated_at"):
            values[fields.index(key)] = now
        with self.connect() as connection:
            connection.execute(f"INSERT INTO {table}({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT({fields[0]}) DO UPDATE SET " + ','.join(f"{key}=excluded.{key}" for key in fields[1:] if key not in {"created_at"}), values)
        return str(item[fields[0]])

    def get_reading_card(self, card_id: str) -> dict[str, Any] | None:
        return self._get_structured("reading_cards", "card_id", card_id)

    def list_reading_cards(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reading_cards" + (" WHERE status=?" if status else "") + " ORDER BY updated_at DESC LIMIT ?",
                ((status, max(1, min(limit, 500))) if status else (max(1, min(limit, 500)),)),
            ).fetchall()
        return [self._decode_metadata(dict(row)) for row in rows]

    def list_topics(self, *, status: str | None = "active") -> list[dict[str, Any]]:
        return self._list_structured("topics", status)

    def get_topic(self, topic_id: str) -> dict[str, Any] | None:
        return self._get_structured("topics", "topic_id", topic_id)

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        return self._get_structured("decisions", "decision_id", decision_id)

    def _get_structured(self, table: str, key: str, value: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        return self._decode_metadata(dict(row)) if row else None

    def _list_structured(self, table: str, status: str | None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(f"SELECT * FROM {table}" + (" WHERE status=?" if status else "") + " ORDER BY updated_at DESC", (status,) if status else ()).fetchall()
        return [self._decode_metadata(dict(row)) for row in rows]

    @staticmethod
    def _decode_metadata(row: dict[str, Any]) -> dict[str, Any]:
        if "metadata_json" in row:
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return row

    def export_search_chunks(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            qa = connection.execute(
                """SELECT qv.qa_version_id AS entity_id, 'qa' AS source_type, p.paper_id,
                   qv.question || '\n' || qv.answer AS text, qv.review_status
                   FROM qa_versions qv JOIN qa_families q ON q.qa_id=qv.qa_id JOIN papers p ON p.paper_id=q.paper_id"""
            ).fetchall()
            evidence = connection.execute(
                """SELECT e.evidence_id AS entity_id, 'evidence' AS source_type, e.paper_id,
                   e.evidence_text AS text, e.review_status FROM evidence e"""
            ).fetchall()
            documents = connection.execute(
                """SELECT document_id AS entity_id, source_type, paper_id, title || '\n' || body AS text,
                   review_status FROM knowledge_documents WHERE status='active'"""
            ).fetchall()
        return [dict(row) for row in (*qa, *evidence, *documents)]

    def list_directions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT node_id, name, parent_id, node_type, version, status FROM taxonomy_nodes WHERE status='active' ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def paper_evidence(self, paper_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.*, q.question, q.answer, q.knowledge_type, q.review_status
                FROM evidence e JOIN qa_versions q ON q.qa_version_id=e.qa_version_id
                WHERE e.paper_id=? ORDER BY e.locator_quality DESC, e.evidence_id LIMIT ?
                """,
                (paper_id, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def evidence_for_qa_version(self, qa_version_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evidence WHERE qa_version_id=? ORDER BY evidence_id",
                (qa_version_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_paper(self, identifier: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM papers
                WHERE paper_id = ? OR doi = ? OR legacy_doc_id = ? OR legacy_key = ?
                LIMIT 1
                """,
                (identifier, identifier, identifier, identifier),
            ).fetchone()
        return dict(row) if row else None

    def list_papers_for_matching(self, *, statuses: tuple[str, ...] = ("legacy_unmatched", "needs_review"), limit: int = 1000) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM papers WHERE match_status IN ({placeholders}) ORDER BY paper_id LIMIT ?",
                (*statuses, max(1, min(limit, 10000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_paper_match(self, paper_id: str, *, hub_paper_id: str | None, status: str, method: str, confidence: float, hub_metadata: dict[str, Any] | None = None, reviewed_by: str | None = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            row = connection.execute("SELECT metadata_json FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
            if not row:
                return False
            metadata = json.loads(row["metadata_json"] or "{}")
            if hub_metadata:
                metadata["hub_candidate"] = hub_metadata
            cursor = connection.execute(
                """UPDATE papers SET hub_paper_id=?, match_status=?, match_method=?, match_confidence=?,
                   matched_at=?, reviewed_by=?, metadata_json=?, updated_at=? WHERE paper_id=?""",
                (hub_paper_id, status, method, confidence, now, reviewed_by, json.dumps(metadata, ensure_ascii=False), now, paper_id),
            )
        return cursor.rowcount > 0

    def qa_details(self, legacy_doc_id: str, pair_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT p.paper_id, p.doi, p.title, p.category, q.qa_id, qv.*
                FROM papers p
                JOIN qa_families q ON q.paper_id = p.paper_id
                JOIN qa_versions qv ON qv.qa_id = q.qa_id
                WHERE p.legacy_doc_id = ? AND qv.pair_id = ?
                ORDER BY qv.created_at DESC LIMIT 1
                """,
                (legacy_doc_id, pair_id),
            ).fetchone()
        return dict(row) if row else None

    def register_index(self, index_version: str, source_hash: str, manifest: dict[str, Any], *, status: str = "published") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO index_versions(
                    index_version, source_hash, manifest_json, status, created_at, published_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (index_version, source_hash, json.dumps(manifest, ensure_ascii=False), status, now, now if status == "published" else None),
            )

    def latest_index(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM index_versions WHERE status='published' ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result
