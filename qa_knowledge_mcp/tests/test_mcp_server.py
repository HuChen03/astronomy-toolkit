import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from qa_knowledge_mcp.mcp_server import create_server
from lab_knowledge_platform.knowledge_store import KnowledgeStore


class UnifiedMcpTests(unittest.TestCase):
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

    def test_exposes_only_knowledge_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qa.jsonl"
            source.write_text(json.dumps({
                "hash": "doc-1",
                "metadata": {"key": "10.1/test", "title": "Test Paper", "category": "Test"},
                "result": {"qa_pairs": [{"question": "What is the result?", "answer": "The result is evidence."}]},
            }) + "\n", encoding="utf-8")
            server = create_server(source, catalog_path=root)

            tools = {tool.name for tool in asyncio.run(server.list_tools())}
            _, databases = asyncio.run(server.call_tool("list_knowledge_bases", {}))
            _, search = asyncio.run(server.call_tool("search_knowledge", {"query": "result evidence"}))

            self.assertEqual(tools, {"list_knowledge_bases", "search_knowledge"})
            self.assertEqual(databases["knowledge_bases"][0]["id"], "main")
            self.assertTrue(search["matched"])

    def test_search_returns_source_paragraph(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "qa.jsonl"
            source.write_text(json.dumps({
                "hash": "doc-1",
                "metadata": {"key": "10.1234_test", "title": "Test Paper", "category": "Methods"},
                "result": {"qa_pairs": [{"question": "What is the method?", "answer": "The method is reproducible."}]},
            }) + "\n", encoding="utf-8")
            overlay = root / "overlay.sqlite3"
            store = KnowledgeStore(overlay)
            paper_id = store.stable_paper_id("doc-1", "10.1234/test")
            store.upsert_paper({
                "paper_id": paper_id,
                "doi": "10.1234/test",
                "legacy_doc_id": "doc-1",
                "legacy_key": "10.1234_test",
                "title": "Test Paper",
                "category": "Methods",
                "match_status": "legacy_unmatched",
            })
            _, version_id = store.upsert_qa(
                paper_id=paper_id,
                pair_id=0,
                question="What is the method?",
                answer="The method is reproducible.",
                source_line=1,
                review_status="reviewed",
            )
            store.add_evidence(
                qa_version_id=version_id,
                paper_id=paper_id,
                evidence_text="The method is reproducible.",
                locator_quality="section",
                alignment_method="test",
                alignment_confidence=1.0,
                section_path="Methods",
                review_status="reviewed",
            )
            server = create_server(source, overlay_path=overlay)
            tools = {tool.name for tool in asyncio.run(server.list_tools())}
            _, search = asyncio.run(server.call_tool("search_knowledge", {"query": "reproducible method"}))
            self.assertEqual(search["results"][0]["knowledge_base_id"], "main")
            self.assertEqual(search["results"][0]["source_paragraph"], "The method is reproducible.")
            self.assertEqual({tool.name for tool in asyncio.run(server.list_tools())}, {"list_knowledge_bases", "search_knowledge"})


if __name__ == "__main__":
    unittest.main()
