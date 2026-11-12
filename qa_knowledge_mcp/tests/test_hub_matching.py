import tempfile
import unittest
from pathlib import Path

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from pipelines.knowledge_acquisition.match_hub_papers import match_papers


class FakeHub:
    def read_paper(self, **kwargs):
        if kwargs.get("doi") == "10.1234/example":
            return {"id": "hub-1", "doi": "10.1234/example", "title": "Example"}
        return None

    def offline_search(self, query, per_page=10):
        return []

    def online_search(self, query, top_k=10, ingest=True):
        return []


class HubMatchingTests(unittest.TestCase):
    def test_exact_doi_match_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "overlay.sqlite3")
            paper_id = store.stable_paper_id("legacy-1", "10.1234/example")
            store.upsert_paper({"paper_id": paper_id, "doi": "10.1234/example", "legacy_doc_id": "legacy-1", "title": "Example", "match_status": "legacy_unmatched"})
            result = match_papers(store, FakeHub())
            self.assertEqual(result["matched"], 1)
            paper = store.resolve_paper(paper_id)
            self.assertEqual(paper["hub_paper_id"], "hub-1")
            self.assertEqual(paper["match_method"], "doi_exact")


if __name__ == "__main__":
    unittest.main()
