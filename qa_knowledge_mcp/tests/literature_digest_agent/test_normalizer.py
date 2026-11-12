import unittest

from literature_digest_agent.normalizer import normalize_digest_payload


class NormalizerTests(unittest.TestCase):
    def test_normalize_digest_payload_accepts_summary_as_abstract(self):
        result = normalize_digest_payload(
            {
                "items": [
                    {
                        "id": "p1",
                        "title": "Example",
                        "summary": "Short summary",
                        "authors": "A, B",
                    }
                ]
            }
        )
        item = result["items"][0]
        self.assertEqual(item["paper_id"], "p1")
        self.assertEqual(item["abstract"], "Short summary")
        self.assertEqual(item["authors"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
