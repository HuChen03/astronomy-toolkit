import unittest
from unittest.mock import patch

from literature_digest_agent.config import HubSettings
from literature_digest_agent.hub_client import (
    LiteratureHubClient,
    normalize_daily_digest_response,
    normalize_domain,
)


class HubClientTests(unittest.TestCase):
    def test_normalizes_current_daily_digest_response(self):
        result = normalize_daily_digest_response(
            {
                "status": "success",
                "date": "2026-07-28",
                "candidate_count": 2,
                "overall_summary": "Daily summary",
                "all_papers_metadata": [
                    {
                        "paper_id": "p1",
                        "title": "Paper",
                        "abstract": "Abstract",
                        "relevance_score": 3.5,
                    }
                ],
                "papers": [
                    {
                        "paper_id": "p1",
                        "summary": {"brief": "Generated brief"},
                        "fulltext": {"pdf_path": "/private/paper.pdf"},
                    }
                ],
            }
        )

        self.assertEqual(result["items"][0]["summary"], "Generated brief")
        self.assertEqual(result["items"][0]["brief"], "Generated brief")
        self.assertEqual(result["items"][0]["brief_source"], "hub")
        self.assertEqual(result["items"][0]["score"], 3.5)
        self.assertEqual(result["stats"]["total_candidates"], 2)

    def test_normalizes_cond_mat_domain(self):
        self.assertEqual(normalize_domain("cond-mat"), "condmat")

    def test_automation_jobs_accepts_list_response(self):
        client = LiteratureHubClient(HubSettings())
        with patch.object(client, "_get_json_value", return_value=[{"id": "job-1"}]):
            result = client.get_automation_jobs()
        self.assertEqual(result["jobs"][0]["id"], "job-1")


if __name__ == "__main__":
    unittest.main()
