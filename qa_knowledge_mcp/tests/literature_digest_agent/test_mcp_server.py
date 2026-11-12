import asyncio
import tempfile
import unittest
from pathlib import Path

from literature_digest_agent.config import CatalogSettings, HubSettings
from literature_digest_agent.mcp_server import create_server, resolve_query_date
from literature_digest_agent.repository import DigestRepository


class McpServerTests(unittest.TestCase):
    def test_query_date_uses_explicit_value(self):
        self.assertEqual(resolve_query_date("2026-07-20", "Asia/Shanghai"), "2026-07-20")

    def test_server_exposes_query_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            keywords_path = root / "keywords.json"
            keywords_path.write_text(
                '{"categories":[{"id":"battery","name":"Battery","terms":["battery"]}]}',
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
            DigestRepository(settings.database_path).publish(
                {
                    "items": [
                        {
                            "paper_id": "p1",
                            "title": "Battery",
                            "brief": "Brief",
                            "authors": [],
                            "upstream_score": 1,
                            "priority_score": 2,
                            "keyword_matched": True,
                            "keyword_categories": [
                                {
                                    "category_id": "battery",
                                    "category": "Battery",
                                    "matched_terms": ["battery"],
                                    "match_score": 2,
                                }
                            ],
                        }
                    ]
                },
                business_date="2026-07-28",
                discipline="cond-mat",
                completeness="complete",
                total_candidates=1,
                tag_config_version="test-v1",
                started_at="2026-07-28T20:00:00+08:00",
                automation_jobs=[],
            )
            server = create_server(settings)

            tools = asyncio.run(server.list_tools())
            _, result = asyncio.run(
                server.call_tool("get_daily_papers", {"tags": ["battery"], "date": "2026-07-28"})
            )
            _, categories = asyncio.run(
                server.call_tool("list_categories", {"date": "2026-07-28"})
            )
            _, digest = asyncio.run(
                server.call_tool(
                    "get_daily_digest",
                    {"category_ids": ["battery"], "date": "2026-07-28"},
                )
            )

            self.assertIn("get_daily_papers", {tool.name for tool in tools})
            self.assertIn("get_daily_digest", {tool.name for tool in tools})
            self.assertEqual(result["items"][0]["paper_id"], "p1")
            self.assertEqual(categories["categories"][0]["id"], "battery")
            self.assertEqual(digest["items"][0]["paper_id"], "p1")


if __name__ == "__main__":
    unittest.main()
