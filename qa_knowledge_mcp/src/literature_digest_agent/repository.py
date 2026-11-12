from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class DigestRepository:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.read_only:
            connection = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        if not self.read_only:
            connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    business_date TEXT NOT NULL,
                    discipline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    completeness TEXT NOT NULL,
                    total_candidates INTEGER NOT NULL,
                    fetched_count INTEGER NOT NULL,
                    tag_config_version TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    hub_summary TEXT NOT NULL,
                    generated_summary TEXT NOT NULL,
                    automation_jobs_json TEXT NOT NULL,
                    error_message TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_daily_runs_date
                ON daily_runs(business_date, discipline, run_id DESC);

                CREATE TABLE IF NOT EXISTS papers (
                    run_id INTEGER NOT NULL,
                    paper_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    brief TEXT NOT NULL,
                    published_at TEXT,
                    upstream_score REAL NOT NULL,
                    priority_score REAL NOT NULL,
                    item_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, paper_id),
                    FOREIGN KEY (run_id) REFERENCES daily_runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS paper_tags (
                    run_id INTEGER NOT NULL,
                    paper_id TEXT NOT NULL,
                    tag_id TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    tag_score REAL NOT NULL,
                    matched_terms_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, paper_id, tag_id),
                    FOREIGN KEY (run_id, paper_id) REFERENCES papers(run_id, paper_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_paper_tags_query
                ON paper_tags(run_id, tag_id, paper_id);

                CREATE TABLE IF NOT EXISTS tag_summaries (
                    run_id INTEGER NOT NULL,
                    tag_id TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    paper_count INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    PRIMARY KEY (run_id, tag_id),
                    FOREIGN KEY (run_id) REFERENCES daily_runs(run_id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_columns(
                connection,
                "daily_runs",
                {
                    "window_start": "TEXT",
                    "window_end": "TEXT",
                    "window_timezone": "TEXT",
                    "window_source": "TEXT",
                    "source_count": "INTEGER NOT NULL DEFAULT 0",
                    "filtered_count": "INTEGER NOT NULL DEFAULT 0",
                    "classification_success_count": "INTEGER NOT NULL DEFAULT 0",
                    "classification_failed_count": "INTEGER NOT NULL DEFAULT 0",
                },
            )
            connection.commit()

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        table: str,
        columns: dict[str, str],
    ) -> None:
        existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def publish(
        self,
        digest: dict[str, Any],
        *,
        business_date: str,
        discipline: str,
        completeness: str,
        total_candidates: int,
        tag_config_version: str,
        started_at: str,
        automation_jobs: list[dict[str, Any]],
        window: dict[str, Any] | None = None,
        source_count: int | None = None,
        filtered_count: int | None = None,
    ) -> dict[str, Any]:
        items = digest.get("items") or []
        completed_at = datetime.now(timezone.utc).isoformat()
        generated_summary = build_daily_summary(items, business_date)
        classification_success_count = sum(
            1 for item in items if (item.get("classification") or {}).get("status") == "success"
        )
        classification_failed_count = sum(
            1 for item in items if (item.get("classification") or {}).get("status") == "failed"
        )
        window = window or {}
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO daily_runs (
                    business_date, discipline, status, completeness,
                    total_candidates, fetched_count, tag_config_version,
                    started_at, completed_at, hub_summary, generated_summary,
                    automation_jobs_json, error_message,
                    window_start, window_end, window_timezone, window_source,
                    source_count, filtered_count,
                    classification_success_count, classification_failed_count
                ) VALUES (?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    business_date,
                    discipline,
                    completeness,
                    total_candidates,
                    len(items),
                    tag_config_version,
                    started_at,
                    completed_at,
                    str(digest.get("summary") or ""),
                    generated_summary,
                    json.dumps(automation_jobs, ensure_ascii=False),
                    window.get("start"),
                    window.get("end"),
                    window.get("timezone"),
                    window.get("source"),
                    source_count if source_count is not None else len(items),
                    filtered_count if filtered_count is not None else len(items),
                    classification_success_count,
                    classification_failed_count,
                ),
            )
            run_id = int(cursor.lastrowid)
            tag_rows: dict[str, dict[str, Any]] = {}
            for item in items:
                paper_id = str(item["paper_id"])
                connection.execute(
                    """
                    INSERT INTO papers (
                        run_id, paper_id, title, brief, published_at,
                        upstream_score, priority_score, item_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        paper_id,
                        str(item.get("title") or ""),
                        str(item.get("brief") or ""),
                        item.get("published_at"),
                        float(item.get("upstream_score") or 0),
                        float(item.get("priority_score") or 0),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
                for tag in item.get("keyword_categories") or []:
                    tag_id = str(tag["category_id"])
                    tag_name = str(tag["category"])
                    connection.execute(
                        """
                        INSERT INTO paper_tags (
                            run_id, paper_id, tag_id, tag_name,
                            tag_score, matched_terms_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            paper_id,
                            tag_id,
                            tag_name,
                            float(tag.get("match_score") or 0),
                            json.dumps(tag.get("matched_terms") or [], ensure_ascii=False),
                        ),
                    )
                    row = tag_rows.setdefault(tag_id, {"name": tag_name, "items": []})
                    row["items"].append(item)
            for tag_id, row in tag_rows.items():
                tagged_items = row["items"]
                connection.execute(
                    """
                    INSERT INTO tag_summaries (
                        run_id, tag_id, tag_name, paper_count, summary
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        tag_id,
                        row["name"],
                        len(tagged_items),
                        build_tag_summary(row["name"], tagged_items, business_date),
                    ),
                )
            connection.commit()
        return self.get_sync_status(business_date, discipline)

    def record_failure(
        self,
        *,
        business_date: str,
        discipline: str,
        started_at: str,
        tag_config_version: str,
        error_message: str,
        automation_jobs: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO daily_runs (
                    business_date, discipline, status, completeness,
                    total_candidates, fetched_count, tag_config_version,
                    started_at, completed_at, hub_summary, generated_summary,
                    automation_jobs_json, error_message
                ) VALUES (?, ?, 'failed', 'unknown', 0, 0, ?, ?, ?, '', '', ?, ?)
                """,
                (
                    business_date,
                    discipline,
                    tag_config_version,
                    started_at,
                    datetime.now(timezone.utc).isoformat(),
                    json.dumps(automation_jobs, ensure_ascii=False),
                    error_message,
                ),
            )
            connection.commit()

    def list_tags(self, business_date: str | None = None, discipline: str = "cond-mat") -> dict[str, Any]:
        run = self._published_run(business_date, discipline)
        if run is None:
            return {"date": business_date, "tags": [], "tag_config_version": None}
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT tag_id, tag_name, paper_count, summary
                FROM tag_summaries
                WHERE run_id = ?
                ORDER BY paper_count DESC, tag_id
                """,
                (run["run_id"],),
            ).fetchall()
        return {
            "date": run["business_date"],
            "tags": [
                {
                    "id": row["tag_id"],
                    "name": row["tag_name"],
                    "today_count": row["paper_count"],
                    "summary": row["summary"],
                }
                for row in rows
            ],
            "tag_config_version": run["tag_config_version"],
            "snapshot": snapshot_metadata(run),
        }

    def get_daily_papers(
        self,
        *,
        business_date: str | None = None,
        discipline: str = "cond-mat",
    ) -> dict[str, Any]:
        run = self._published_run(business_date, discipline)
        if run is None:
            return {
                "date": business_date,
                "discipline": discipline,
                "summary": "",
                "total_candidates": 0,
                "fetched_count": 0,
                "items": [],
                "snapshot": None,
            }
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT item_json FROM papers WHERE run_id = ? ORDER BY priority_score DESC, paper_id",
                (run["run_id"],),
            ).fetchall()
        return {
            "date": run["business_date"],
            "discipline": run["discipline"],
            "summary": run["generated_summary"] or run["hub_summary"],
            "total_candidates": run["total_candidates"],
            "fetched_count": run["fetched_count"],
            "items": [json.loads(row["item_json"]) for row in rows],
            "snapshot": snapshot_metadata(run),
        }

    def query_papers(
        self,
        tags: list[str],
        *,
        business_date: str | None = None,
        discipline: str = "cond-mat",
        match_mode: str = "any",
        limit: int = 20,
        offset: int = 0,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        if not tags:
            raise ValueError("at least one tag is required")
        if match_mode not in {"any", "all"}:
            raise ValueError("match_mode must be 'any' or 'all'")
        if sort not in {"relevance", "published_desc", "upstream_score"}:
            raise ValueError("unsupported sort")
        run = self._published_run(business_date, discipline)
        if run is None:
            return self._empty_query_result(tags, business_date, match_mode)
        unique_tags = list(dict.fromkeys(tags))
        placeholders = ",".join("?" for _ in unique_tags)
        having = "HAVING COUNT(DISTINCT pt.tag_id) = ?" if match_mode == "all" else ""
        order_by = {
            "relevance": "tag_score DESC, p.priority_score DESC, p.paper_id",
            "published_desc": "COALESCE(p.published_at, '') DESC, tag_score DESC, p.paper_id",
            "upstream_score": "p.upstream_score DESC, tag_score DESC, p.paper_id",
        }[sort]
        parameters: list[Any] = [run["run_id"], *unique_tags]
        if match_mode == "all":
            parameters.append(len(unique_tags))
        base_query = f"""
            SELECT p.paper_id, p.item_json, SUM(pt.tag_score) AS tag_score
            FROM papers p
            JOIN paper_tags pt ON pt.run_id = p.run_id AND pt.paper_id = p.paper_id
            WHERE p.run_id = ? AND pt.tag_id IN ({placeholders})
            GROUP BY p.paper_id
            {having}
        """
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM ({base_query}) matched",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"{base_query} ORDER BY {order_by} LIMIT ? OFFSET ?",
                [*parameters, max(1, min(limit, 100)), max(0, offset)],
            ).fetchall()
            summary_rows = connection.execute(
                f"""
                SELECT tag_id, tag_name, summary
                FROM tag_summaries
                WHERE run_id = ? AND tag_id IN ({placeholders})
                ORDER BY tag_id
                """,
                [run["run_id"], *unique_tags],
            ).fetchall()
        items = [public_paper(json.loads(row["item_json"]), float(row["tag_score"] or 0)) for row in rows]
        tag_summaries = {row["tag_id"]: row["summary"] for row in summary_rows}
        return {
            "date": run["business_date"],
            "requested_tags": unique_tags,
            "match_mode": match_mode,
            "total": total,
            "returned": len(items),
            "summary": combine_tag_summaries(tag_summaries),
            "tag_summaries": tag_summaries,
            "global_daily_summary": run["generated_summary"] or run["hub_summary"],
            "items": items,
            "snapshot": snapshot_metadata(run),
        }

    def get_daily_summary(
        self,
        *,
        business_date: str | None = None,
        discipline: str = "cond-mat",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        run = self._published_run(business_date, discipline)
        if run is None:
            return {"date": business_date, "summary": "", "tag_summaries": {}, "snapshot": None}
        tag_summaries: dict[str, str] = {}
        if tags:
            placeholders = ",".join("?" for _ in tags)
            with self.connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT tag_id, summary FROM tag_summaries
                    WHERE run_id = ? AND tag_id IN ({placeholders})
                    ORDER BY tag_id
                    """,
                    [run["run_id"], *tags],
                ).fetchall()
            tag_summaries = {row["tag_id"]: row["summary"] for row in rows}
        return {
            "date": run["business_date"],
            "summary": combine_tag_summaries(tag_summaries) if tags else run["generated_summary"],
            "hub_summary": run["hub_summary"],
            "tag_summaries": tag_summaries,
            "total_candidates": run["total_candidates"],
            "fetched_count": run["fetched_count"],
            "snapshot": snapshot_metadata(run),
        }

    def get_paper(
        self,
        paper_id: str,
        *,
        business_date: str | None = None,
        discipline: str = "cond-mat",
    ) -> dict[str, Any] | None:
        run = self._published_run(business_date, discipline)
        if run is None:
            return None
        with self.connect() as connection:
            row = connection.execute(
                "SELECT item_json FROM papers WHERE run_id = ? AND paper_id = ?",
                (run["run_id"], paper_id),
            ).fetchone()
        return json.loads(row["item_json"]) if row else None

    def get_sync_status(
        self,
        business_date: str | None = None,
        discipline: str = "cond-mat",
    ) -> dict[str, Any]:
        with self.connect() as connection:
            if business_date:
                row = connection.execute(
                    """
                    SELECT * FROM daily_runs
                    WHERE business_date = ? AND discipline = ?
                    ORDER BY run_id DESC LIMIT 1
                    """,
                    (business_date, discipline),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT * FROM daily_runs
                    WHERE discipline = ?
                    ORDER BY business_date DESC, run_id DESC LIMIT 1
                    """,
                    (discipline,),
                ).fetchone()
        if row is None:
            return {"status": "not_found", "date": business_date, "discipline": discipline}
        return {
            **snapshot_metadata(row),
            "date": row["business_date"],
            "source": "local_digest_repository",
            "discipline": row["discipline"],
            "total_candidates": row["total_candidates"],
            "fetched_count": row["fetched_count"],
            "tag_config_version": row["tag_config_version"],
            "started_at": row["started_at"],
            "error_message": row["error_message"],
            "automation_jobs": json.loads(row["automation_jobs_json"]),
            "jobs": json.loads(row["automation_jobs_json"]),
            "window": run_window(row),
            "source_count": row["source_count"],
            "filtered_count": row["filtered_count"],
            "classification_success_count": row["classification_success_count"],
            "classification_failed_count": row["classification_failed_count"],
        }

    def _published_run(self, business_date: str | None, discipline: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            if business_date:
                return connection.execute(
                    """
                    SELECT * FROM daily_runs
                    WHERE business_date = ? AND discipline = ? AND status = 'published'
                    ORDER BY run_id DESC LIMIT 1
                    """,
                    (business_date, discipline),
                ).fetchone()
            return connection.execute(
                """
                SELECT * FROM daily_runs
                WHERE discipline = ? AND status = 'published'
                ORDER BY business_date DESC, run_id DESC LIMIT 1
                """,
                (discipline,),
            ).fetchone()

    @staticmethod
    def _empty_query_result(tags: list[str], business_date: str | None, match_mode: str) -> dict[str, Any]:
        return {
            "date": business_date,
            "requested_tags": tags,
            "match_mode": match_mode,
            "total": 0,
            "returned": 0,
            "summary": "",
            "tag_summaries": {},
            "global_daily_summary": "",
            "items": [],
            "snapshot": None,
        }


def build_daily_summary(items: list[dict[str, Any]], business_date: str) -> str:
    matched = sum(1 for item in items if item.get("keyword_matched"))
    tag_counts: dict[str, int] = {}
    for item in items:
        for tag in item.get("keyword_categories") or []:
            name = str(tag.get("category") or tag.get("category_id"))
            tag_counts[name] = tag_counts.get(name, 0) + 1
    parts = [f"{business_date} 共收录 {len(items)} 篇论文，其中 {matched} 篇命中预设标签。"]
    if tag_counts:
        ranking = sorted(tag_counts.items(), key=lambda row: (-row[1], row[0]))
        parts.append("标签分布：" + "；".join(f"{name} {count} 篇" for name, count in ranking) + "。")
    return "".join(parts)


def build_tag_summary(tag_name: str, items: list[dict[str, Any]], business_date: str) -> str:
    titles = [str(item.get("title") or "") for item in items[:3] if item.get("title")]
    summary = f"{business_date} 的“{tag_name}”标签共有 {len(items)} 篇论文。"
    if titles:
        summary += "重点包括：" + "；".join(titles) + "。"
    return summary


def combine_tag_summaries(tag_summaries: dict[str, str]) -> str:
    return "\n".join(tag_summaries.values())


def snapshot_metadata(run: sqlite3.Row) -> dict[str, Any]:
    return {
        "status": run["status"],
        "completeness": run["completeness"],
        "generated_at": run["completed_at"],
        "window": run_window(run),
    }


def run_window(run: sqlite3.Row) -> dict[str, Any] | None:
    if not run["window_start"] or not run["window_end"]:
        return None
    return {
        "start": run["window_start"],
        "end": run["window_end"],
        "timezone": run["window_timezone"],
        "source": run["window_source"],
    }


def public_paper(item: dict[str, Any], relevance_score: float) -> dict[str, Any]:
    tags = [
        {
            "id": tag.get("category_id"),
            "name": tag.get("category"),
            "score": tag.get("match_score"),
            "matched_terms": tag.get("matched_terms") or [],
        }
        for tag in item.get("keyword_categories") or []
    ]
    return {
        "paper_id": item.get("paper_id"),
        "title": item.get("title"),
        "authors": item.get("authors") or [],
        "brief": item.get("brief") or item.get("summary") or item.get("abstract") or "",
        "brief_source": item.get("brief_source"),
        "brief_source_field": item.get("brief_source_field"),
        "primary_category": (item.get("classification") or {}).get("primary_category"),
        "secondary_categories": (item.get("classification") or {}).get("secondary_categories") or [],
        "classification_status": (item.get("classification") or {}).get("status"),
        "classification_confidence": (item.get("classification") or {}).get("confidence"),
        "discovered_at": item.get("discovered_at"),
        "published_at": item.get("published_at"),
        "venue": item.get("venue"),
        "doi": item.get("doi"),
        "arxiv_id": item.get("arxiv_id"),
        "tags": tags,
        "relevance_score": relevance_score,
        "links": {
            "arxiv": f"https://arxiv.org/abs/{item['arxiv_id']}" if item.get("arxiv_id") else None,
        },
    }
