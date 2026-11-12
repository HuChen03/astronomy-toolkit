import json
import os
import tempfile
import unittest
from pathlib import Path

from qa_knowledge_mcp.knowledge_base import KnowledgeBase
from qa_knowledge_mcp.build_kb import build


class KnowledgeBaseTests(unittest.TestCase):
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

    def test_load_and_match(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "qa.jsonl"
            source.write_text(
                json.dumps({"hash": "doc-1", "metadata": {
                    "key": "10.1234/example",
                    "title": "Knowledge Retrieval",
                    "category": "Methods",
                    "rank": 1,
                }, "result": {"qa_pairs": [
                    {"question": "什么是环境流？", "answer": "环境流是维持水生生态系统所需的水量、时机和质量。"},
                    {"question": "What is BM25?", "answer": "BM25 is a sparse lexical retrieval function."},
                    {"question": "如何做知识库混合检索？", "answer": "常见做法是稀疏检索加向量检索，再做重排。"},
                ]}}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            kb = KnowledgeBase(source)
            zh_results = kb.search("环境流需要什么")
            self.assertEqual(zh_results[0]["pair_id"], 0)
            self.assertIn("水生生态系统", zh_results[0]["answer"])
            self.assertIn("score_components", zh_results[0])
            self.assertNotIn("source_file", zh_results[0])
            self.assertNotIn("paper_source", zh_results[0])

            en_results = kb.search("sparse lexical retrieval function")
            self.assertEqual(en_results[0]["pair_id"], 1)
            self.assertIn("BM25", en_results[0]["question"])

            hybrid_results = kb.search("知识库 检索 怎么 做")
            self.assertEqual(hybrid_results[0]["pair_id"], 2)
            self.assertIn("混合检索", hybrid_results[0]["question"])

            pack = kb.evidence_pack("知识库检索", top_k=2, max_per_paper=2)
            self.assertTrue(pack["matched"])
            self.assertEqual(pack["papers"][0]["paper_key"], "10.1234/example")
            self.assertIsNone(pack["papers"][0]["doi"])
            self.assertEqual(pack["evidence"][0]["paper_title"], "Knowledge Retrieval")
            self.assertFalse(pack["provenance"]["generated_answer"])

    def test_missing_source_is_clear(self):
        with self.assertRaises(FileNotFoundError):
            KnowledgeBase(Path("/does/not/exist.jsonl"))

    def test_loads_offline_chunks_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qa.jsonl"
            index_dir = root / "index"
            source.write_text(
                json.dumps({"hash": "doc-1", "result": {"qa_pairs": [
                    {"question": "什么是BM25？", "answer": "BM25是一种关键词稀疏检索算法。"},
                ]}}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            build(source, index_dir, embedding=False, model_name="unused", device="cpu", batch_size=1)
            kb = KnowledgeBase(source, index_dir)
            self.assertEqual(kb.stats()["record_count"], 1)
            self.assertIn("BM25", kb.search("BM25关键词检索", top_k=1)[0]["question"])


if __name__ == "__main__":
    unittest.main()
