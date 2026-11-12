import json
import os
import tempfile
import unittest
from pathlib import Path

from qa_knowledge_mcp.knowledge_catalog import KnowledgeBaseCatalog


class KnowledgeCatalogTests(unittest.TestCase):
    def setUp(self):
        self.previous_embedding = os.environ.get("QA_ENABLE_EMBEDDING")
        self.previous_reranker = os.environ.get("QA_ENABLE_RERANKER")
        os.environ["QA_ENABLE_EMBEDDING"] = "false"
        os.environ["QA_ENABLE_RERANKER"] = "false"

    def tearDown(self):
        if self.previous_embedding is None:
            os.environ.pop("QA_ENABLE_EMBEDDING", None)
        else:
            os.environ["QA_ENABLE_EMBEDDING"] = self.previous_embedding
        if self.previous_reranker is None:
            os.environ.pop("QA_ENABLE_RERANKER", None)
        else:
            os.environ["QA_ENABLE_RERANKER"] = self.previous_reranker

    @staticmethod
    def write_source(path: Path, question: str, answer: str, paragraph: str) -> None:
        path.write_text(json.dumps({
            "hash": path.stem,
            "metadata": {"key": "10.1234/example", "title": path.stem},
            "result": {"qa_pairs": [{"question": question, "answer": answer, "source_paragraph": paragraph}]},
        }, ensure_ascii=False) + "\n", encoding="utf-8")

    def test_defaults_to_main_and_explicit_direction_augments_main(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_dir = root / "configs"
            config_dir.mkdir()
            main = root / "main.jsonl"
            direction = root / "direction.jsonl"
            self.write_source(main, "What is the main method?", "Main answer", "Main source paragraph")
            self.write_source(direction, "What is the special method?", "Direction answer", "Direction source paragraph")
            (config_dir / "main.json").write_text(json.dumps({"id": "main", "name": "Main", "source": str(main)}), encoding="utf-8")
            (config_dir / "special.json").write_text(json.dumps({"id": "special", "name": "Special", "source": str(direction)}), encoding="utf-8")
            catalog = KnowledgeBaseCatalog(config_dir, main_source=main)

            default = catalog.search("special", top_k=10)
            self.assertEqual(default["knowledge_base_ids"], ["main"])
            self.assertFalse(default["matched"])

            combined = catalog.search("special", knowledge_base_ids=["special"], top_k=10)
            self.assertEqual(combined["knowledge_base_ids"], ["main", "special"])
            self.assertEqual(combined["results"][0]["knowledge_base_id"], "special")
            self.assertEqual(combined["results"][0]["source_paragraph"], "Direction source paragraph")

    def test_unknown_direction_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "main.jsonl"
            self.write_source(source, "Question", "Answer", "Paragraph")
            catalog = KnowledgeBaseCatalog(root / "configs", main_source=source)
            with self.assertRaises(ValueError):
                catalog.search("Question", knowledge_base_ids=["missing"])
