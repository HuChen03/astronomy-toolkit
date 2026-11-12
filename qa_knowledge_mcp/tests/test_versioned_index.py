import json
import os
import tempfile
import unittest
from pathlib import Path

from qa_knowledge_mcp.versioned_index import active_index, build_versioned_index


class VersionedIndexTests(unittest.TestCase):
    def test_builds_and_publishes_active_index(self):
        previous = os.environ.get("QA_ENABLE_EMBEDDING")
        os.environ["QA_ENABLE_EMBEDDING"] = "false"
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "qa.jsonl"
                source.write_text(json.dumps({
                    "hash": "doc-1",
                    "result": {"qa_pairs": [{"question": "Question", "answer": "Answer"}]},
                }) + "\n", encoding="utf-8")
                result = build_versioned_index(source, index_root=root / "indexes", overlay_db=root / "missing.sqlite3")
                active = active_index(root / "indexes")
                self.assertIsNotNone(active)
                self.assertEqual(active.name, result["index_version"])
                self.assertTrue((active / "validation.json").exists())
                self.assertEqual(result["manifest"]["overlay_record_count"], 0)
        finally:
            if previous is None:
                os.environ.pop("QA_ENABLE_EMBEDDING", None)
            else:
                os.environ["QA_ENABLE_EMBEDDING"] = previous
