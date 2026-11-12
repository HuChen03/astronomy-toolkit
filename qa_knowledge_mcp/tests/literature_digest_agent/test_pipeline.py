import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from literature_digest_agent.config import HubSettings, RunSettings, SmtpSettings
from literature_digest_agent.pipeline import run


class PipelineTests(unittest.TestCase):
    def test_run_ranks_classifies_and_writes_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            keywords_path = tmp / "keywords.json"
            output_path = tmp / "digest.json"
            keywords_path.write_text(
                json.dumps(
                    {
                        "categories": [
                            {
                                "id": "battery",
                                "name": "Battery",
                                "terms": ["zinc-ion battery"],
                                "weight": 5,
                            }
                        ]
                    }
                ),
                encoding="utf8",
            )
            settings = RunSettings(
                hub=HubSettings(base_url="http://example.invalid", timeout_seconds=1),
                digest_date="2026-05-06",
                discipline="cond-mat",
                limit=2,
                keywords_path=keywords_path,
                taxonomy_path=None,
                input_digest_path=None,
                output_path=output_path,
                enable_llm_classification=False,
                max_workers=1,
                email=False,
                smtp=SmtpSettings(
                    server="smtp.example.invalid",
                    port=587,
                    use_ssl=False,
                    sender="",
                    password="",
                    recipients=(),
                ),
            )
            payload = {
                "date": "2026-05-06",
                "items": [
                    {"paper_id": "high", "title": "Unrelated", "summary": "", "score": 99},
                    {
                        "paper_id": "match",
                        "title": "Zinc-ion battery electrolyte",
                        "summary": "",
                        "score": 0.1,
                    },
                ],
            }
            with patch(
                "literature_digest_agent.hub_client.LiteratureHubClient.fetch_daily_digest",
                return_value=payload,
            ):
                result = run(settings)

            self.assertEqual(result["items"][0]["paper_id"], "match")
            self.assertEqual(result["items"][0]["classification"]["primary_category"]["id"], "battery")
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
