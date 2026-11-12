import tempfile
import unittest
from pathlib import Path

from literature_digest_agent.repository import DigestRepository


class RepositoryTests(unittest.TestCase):
    def test_reads_published_daily_papers_in_read_only_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "digest.sqlite3"
            repository = DigestRepository(database)
            repository.publish(
                {
                    "items": [{
                        "paper_id": "p1",
                        "title": "Paper One",
                        "priority_score": 2.0,
                        "keyword_categories": [],
                    }],
                    "summary": "Hub summary",
                    "generated_summary": "Generated summary",
                },
                business_date="2026-08-09",
                discipline="cond-mat",
                completeness="complete",
                total_candidates=1,
                tag_config_version="test",
                started_at="2026-08-09T00:00:00+00:00",
                automation_jobs=[],
            )

            result = DigestRepository(database, read_only=True).get_daily_papers(
                business_date="2026-08-09",
                discipline="cond-mat",
            )

            self.assertEqual(result["items"][0]["paper_id"], "p1")
            self.assertEqual(result["total_candidates"], 1)
            self.assertEqual(result["snapshot"]["status"], "published")

    def test_publish_and_query_by_any_or_all_tags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = DigestRepository(Path(tmpdir) / "digest.sqlite3")
            repository.publish(
                {
                    "summary": "Hub summary",
                    "items": [
                        paper("both", ["battery", "kagome"]),
                        paper("battery", ["battery"]),
                        paper("none", []),
                    ],
                },
                business_date="2026-07-28",
                discipline="cond-mat",
                completeness="complete",
                total_candidates=3,
                tag_config_version="test-v1",
                started_at="2026-07-28T20:00:00+08:00",
                automation_jobs=[],
            )

            any_result = repository.query_papers(
                ["battery", "kagome"],
                business_date="2026-07-28",
                match_mode="any",
            )
            all_result = repository.query_papers(
                ["battery", "kagome"],
                business_date="2026-07-28",
                match_mode="all",
            )

            self.assertEqual(any_result["total"], 2)
            self.assertEqual(all_result["total"], 1)
            self.assertEqual(all_result["items"][0]["paper_id"], "both")
            self.assertEqual(repository.list_tags("2026-07-28")["tags"][0]["today_count"], 2)

    def test_latest_snapshot_is_used_when_date_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repository = DigestRepository(Path(tmpdir) / "digest.sqlite3")
            for business_date, paper_id in (
                ("2026-07-27", "old"),
                ("2026-07-28", "new"),
            ):
                repository.publish(
                    {"items": [paper(paper_id, ["battery"])]},
                    business_date=business_date,
                    discipline="cond-mat",
                    completeness="complete",
                    total_candidates=1,
                    tag_config_version="test-v1",
                    started_at=f"{business_date}T20:00:00+08:00",
                    automation_jobs=[],
                )

            result = repository.query_papers(["battery"])

            self.assertEqual(result["date"], "2026-07-28")
            self.assertEqual(result["items"][0]["paper_id"], "new")


def paper(paper_id: str, tags: list[str]) -> dict:
    return {
        "paper_id": paper_id,
        "title": f"Paper {paper_id}",
        "authors": [],
        "brief": f"Brief {paper_id}",
        "upstream_score": 1,
        "priority_score": 2,
        "keyword_matched": bool(tags),
        "keyword_categories": [
            {
                "category_id": tag,
                "category": tag.title(),
                "matched_terms": [tag],
                "match_score": 2,
            }
            for tag in tags
        ],
    }


if __name__ == "__main__":
    unittest.main()
