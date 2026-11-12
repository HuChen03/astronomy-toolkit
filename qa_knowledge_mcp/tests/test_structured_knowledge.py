import tempfile
import unittest
from pathlib import Path

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from pipelines.knowledge_acquisition.import_structured_knowledge import import_structured


class StructuredKnowledgeTests(unittest.TestCase):
    def test_imports_reading_card_topic_and_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "knowledge"
            (root / "papers").mkdir(parents=True)
            (root / "topics").mkdir()
            (root / "decisions").mkdir()
            (root / "papers" / "001_10.1234_example.knowledge.md").write_text(
                "# 2. 一句话核心结论\n\nAuthor claim.\n\n# 5. 方法与技术路线\n\nMethod details.\n",
                encoding="utf-8",
            )
            (root / "topics" / "simulation.md").write_text(
                "---\nid: simulation\ntitle: Simulation\nstatus: active\n---\n# 当前共识\n\nNeeds review.\n",
                encoding="utf-8",
            )
            (root / "decisions" / "tool.md").write_text(
                "---\nid: tool-choice\ntitle: Tool choice\nstatus: draft\n---\n# 决策\n\nPending.\n",
                encoding="utf-8",
            )
            store_path = root / "overlay.sqlite3"
            store = KnowledgeStore(store_path)
            paper_id = store.stable_paper_id("legacy", "10.1234/example")
            store.upsert_paper({"paper_id": paper_id, "doi": "10.1234/example", "legacy_doc_id": "legacy", "title": "Example", "match_status": "legacy_unmatched"})
            result = import_structured(root, store_path)
            self.assertEqual(result["reading_cards"], 1)
            self.assertEqual(result["topics"], 1)
            self.assertEqual(result["decisions"], 1)
            self.assertEqual(store.list_topics()[0]["topic_id"], "simulation")
            self.assertEqual(store.get_decision("tool-choice")["status"], "draft")
            cards = store.get_reading_card("reading_card:" + __import__("hashlib").sha256("papers/001_10.1234_example.knowledge.md".encode()).hexdigest()[:24])
            self.assertEqual(cards["author_claims"], "Author claim.")


if __name__ == "__main__":
    unittest.main()
