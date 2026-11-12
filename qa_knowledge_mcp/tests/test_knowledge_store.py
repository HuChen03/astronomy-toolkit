import json
import tempfile
import unittest
from pathlib import Path

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from pipelines.knowledge_acquisition.migrate_legacy_qa import migrate


class KnowledgeStoreTests(unittest.TestCase):
    def test_migrates_legacy_qa_with_stable_entities(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown = root / "paper.md"
            markdown.write_text("# Numerical Relaxation\n\nTwo-body relaxation affects small simulations.\n", encoding="utf-8")
            source = root / "qa.jsonl"
            source.write_text(
                json.dumps({
                    "hash": "legacy-1",
                    "metadata": {"key": "10.1234_example", "title": "Example", "source": str(markdown)},
                    "result": {"qa_pairs": [{"question": "What is two-body relaxation?", "answer": "Two-body relaxation affects small simulations."}]},
                }) + "\n",
                encoding="utf-8",
            )
            result = migrate(source, root / "overlay.sqlite3")
            self.assertEqual(result["papers"], 1)
            self.assertEqual(result["qa"], 1)
            self.assertEqual(result["evidence"], 1)
            store = KnowledgeStore(root / "overlay.sqlite3", read_only=True)
            stats = store.stats()
            self.assertEqual(stats["qa_versions"], 1)
            self.assertEqual(store.paper_evidence("doi:10.1234/example")[0]["locator_quality"], "section")

    def test_documents_and_incremental_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "overlay.sqlite3")
            store.upsert_document(
                document_id="topic:relaxation",
                source_type="topic",
                title="Numerical relaxation",
                body="Two-body relaxation limits small simulations.",
                review_status="reviewed",
            )
            documents = store.search_documents("two-body relaxation", source_types={"topic"})
            self.assertEqual(documents[0]["document_id"], "topic:relaxation")

            task_id = store.enqueue_task(
                stage="align_evidence",
                idempotency_key="paper-1:align:v1",
                input_hash="hash-1",
                payload={"paper_id": "paper-1"},
                max_attempts=2,
            )
            claimed = store.claim_task(stage="align_evidence")
            self.assertEqual(claimed["task_id"], task_id)
            self.assertEqual(claimed["payload"]["paper_id"], "paper-1")
            self.assertTrue(store.fail_task(task_id, "temporary", lease_token=claimed["lease_token"], retry_delay_seconds=0))
            reclaimed = store.claim_task()
            self.assertEqual(reclaimed["attempts"], 2)
            self.assertTrue(store.fail_task(task_id, "permanent", lease_token=reclaimed["lease_token"]))
            self.assertEqual(store.list_tasks(status="dead_letter")[0]["task_id"], task_id)


    def test_expired_lease_recovers_and_old_worker_cannot_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "store.sqlite3")
            task_id = store.enqueue_task(stage="import_documents", idempotency_key="doc-1", input_hash="demo")
            first = store.claim_task()
            self.assertTrue(store.renew_task(task_id, first["lease_token"]))
            self.assertIsNone(store.claim_task())
            with store.connect() as connection:
                connection.execute("UPDATE processing_tasks SET lease_expires_at=? WHERE task_id=?",
                                   ("2000-01-01T00:00:00+00:00", task_id))
            restarted = KnowledgeStore(store.path)
            second = restarted.claim_task()
            self.assertEqual(second["attempts"], 2)
            self.assertNotEqual(first["lease_token"], second["lease_token"])
            self.assertFalse(store.finish_task(task_id, lease_token=first["lease_token"]))
            self.assertFalse(store.fail_task(task_id, "late", lease_token=first["lease_token"]))
            self.assertTrue(restarted.finish_task(task_id, lease_token=second["lease_token"]))


if __name__ == "__main__":
    unittest.main()
