import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from literature_digest_agent.config import CatalogSettings, HubSettings
from literature_digest_agent.daily_catalog import (
    fetch_window_digest,
    filter_digest_by_discovery_date,
    filter_digest_by_window,
    refresh_daily_catalog,
)
from literature_digest_agent.repository import DigestRepository
from literature_digest_agent.time_window import daily_window


class DailyCatalogTests(unittest.TestCase):
    def test_refresh_publishes_complete_strict_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keywords_path = root / "keywords.json"
            keywords_path.write_text(
                json.dumps(
                    {
                        "categories": [
                            {
                                "id": "battery",
                                "name": "Battery",
                                "terms": ["zinc battery"],
                            }
                        ]
                    }
                ),
                encoding="utf8",
            )
            settings = CatalogSettings(
                hub=HubSettings("http://example.invalid", 1),
                discipline="cond-mat",
                fetch_limit=50,
                keywords_path=keywords_path,
                taxonomy_path=None,
                enable_llm_classification=False,
                max_workers=1,
                database_path=root / "digest.sqlite3",
                timezone="Asia/Shanghai",
            )
            with (
                patch(
                    "literature_digest_agent.daily_catalog.LiteratureHubClient.get_automation_jobs",
                    return_value={"jobs": []},
                ),
                patch(
                    "literature_digest_agent.daily_catalog.LiteratureHubClient.fetch_daily_digest",
                    return_value={
                        "date": "2026-07-28",
                        "stats": {"total_candidates": 2, "selected": 1},
                        "items": [
                            {
                                "paper_id": "p1",
                                "title": "Zinc battery study",
                                "summary": "A useful paper.",
                                "discovered_at": "2026-07-27T01:00:00Z",
                            }
                        ],
                    },
                ),
            ):
                result = refresh_daily_catalog(settings, business_date="2026-07-28")

            self.assertEqual(result["status"], "published")
            self.assertEqual(result["completeness"], "complete")
            query = DigestRepository(settings.database_path).query_papers(
                ["battery"],
                business_date="2026-07-28",
            )
            self.assertEqual(query["items"][0]["brief"], "A useful paper.")
            self.assertEqual(query["items"][0]["brief_source"], "hub")
            self.assertEqual(query["snapshot"]["window"]["end"], "2026-07-28T08:00:00+08:00")

    def test_near_24_hour_window_is_left_closed_and_right_open(self):
        window = daily_window("Asia/Shanghai", business_date="2026-07-28")
        payload, stats = filter_digest_by_window(
            {
                "items": [
                    {"paper_id": "start", "discovered_at": "2026-07-27T08:00:00+08:00"},
                    {"paper_id": "middle", "discovered_at": "2026-07-28T07:59:59+08:00"},
                    {"paper_id": "end", "discovered_at": "2026-07-28T08:00:00+08:00"},
                ]
            },
            window,
        )

        self.assertEqual([item["paper_id"] for item in payload["items"]], ["start", "middle"])
        self.assertEqual(stats["matched_items"], 2)

    def test_fetches_two_calendar_days_when_hub_has_no_window_metadata(self):
        settings = CatalogSettings(
            hub=HubSettings("http://example.invalid", 1),
            discipline="cond-mat",
            fetch_limit=50,
            keywords_path=Path("keywords.json"),
            taxonomy_path=None,
            enable_llm_classification=False,
            max_workers=1,
            database_path=Path("digest.sqlite3"),
            timezone="Asia/Shanghai",
        )
        client = unittest.mock.Mock()
        client.fetch_daily_digest.side_effect = [
            {"date": "2026-07-28", "items": [{"paper_id": "today"}]},
            {"date": "2026-07-27", "items": [{"paper_id": "yesterday"}]},
        ]

        result = fetch_window_digest(
            client,
            settings,
            daily_window("Asia/Shanghai", business_date="2026-07-28"),
        )

        self.assertEqual(client.fetch_daily_digest.call_count, 2)
        self.assertEqual({item["paper_id"] for item in result["items"]}, {"today", "yesterday"})

    def test_strict_filter_only_keeps_target_discovery_date(self):
        payload, stats = filter_digest_by_discovery_date(
            {
                "items": [
                    {"paper_id": "target", "discovered_at": "2026-07-27T02:00:00Z"},
                    {"paper_id": "old", "discovered_at": "2026-07-26T23:00:00Z"},
                    {"paper_id": "unknown"},
                ]
            },
            "2026-07-27",
        )

        self.assertEqual([item["paper_id"] for item in payload["items"]], ["target"])
        self.assertEqual(stats["excluded_items"], 2)

    def test_refresh_defers_when_discovery_timestamps_are_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keywords_path = root / "keywords.json"
            keywords_path.write_text(
                '{"categories":[{"id":"x","name":"X","terms":["example"]}]}',
                encoding="utf8",
            )
            settings = CatalogSettings(
                hub=HubSettings("http://example.invalid", 1),
                discipline="cond-mat",
                fetch_limit=50,
                keywords_path=keywords_path,
                taxonomy_path=None,
                enable_llm_classification=False,
                max_workers=1,
                database_path=root / "digest.sqlite3",
                timezone="Asia/Shanghai",
            )
            with (
                patch(
                    "literature_digest_agent.daily_catalog.LiteratureHubClient.get_automation_jobs",
                    return_value={"jobs": []},
                ),
                patch(
                    "literature_digest_agent.daily_catalog.LiteratureHubClient.fetch_daily_digest",
                    return_value={
                        "date": "2026-07-27",
                        "items": [{"paper_id": "historical", "title": "Historical paper"}],
                    },
                ),
            ):
                result = refresh_daily_catalog(settings, business_date="2026-07-27")

            self.assertEqual(result["status"], "deferred")
            self.assertEqual(result["reason"], "discovery_timestamp_unavailable")

    def test_refresh_defers_while_upstream_job_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keywords_path = root / "keywords.json"
            keywords_path.write_text(
                '{"categories":[{"id":"x","name":"X","terms":["example"]}]}',
                encoding="utf8",
            )
            settings = CatalogSettings(
                hub=HubSettings("http://example.invalid", 1),
                discipline="cond-mat",
                fetch_limit=50,
                keywords_path=keywords_path,
                taxonomy_path=None,
                enable_llm_classification=False,
                max_workers=1,
                database_path=root / "digest.sqlite3",
                timezone="Asia/Shanghai",
            )
            with patch(
                "literature_digest_agent.daily_catalog.LiteratureHubClient.get_automation_jobs",
                return_value={
                    "jobs": [
                        {
                            "job_id": "auto:arxiv:cond-mat.*",
                            "status": "active",
                            "last_run_status": "running",
                        }
                    ]
                },
            ):
                result = refresh_daily_catalog(settings, business_date="2026-07-28")

            self.assertEqual(result["status"], "deferred")


if __name__ == "__main__":
    unittest.main()
