import json
from pathlib import Path

import numpy as np
import pytest

from lab_knowledge_platform.knowledge_store import KnowledgeStore
from qa_knowledge_mcp.build_kb import build
from qa_knowledge_mcp.evaluate import evaluate
from qa_knowledge_mcp.knowledge_base import KnowledgeBase
from qa_knowledge_mcp.knowledge_catalog import KnowledgeBaseCatalog


@pytest.fixture(autouse=True)
def lexical_only(monkeypatch):
    monkeypatch.setenv("QA_ENABLE_EMBEDDING", "false")
    monkeypatch.setenv("QA_ENABLE_RERANKER", "false")


def write_paper(path: Path, answer: str, *, key="10.1234_demo.42", title="Simulation timestep") -> None:
    paper = {"hash": "paper-1", "metadata": {"key": key, "title": title},
             "result": {"qa_pairs": [{"question": "What timestep is used?", "answer": answer}]}}
    path.write_text(json.dumps(paper) + "\n")


def test_rejects_stale_index_and_accepts_index_only(tmp_path):
    source = tmp_path / "source.jsonl"
    index = tmp_path / "index"
    write_paper(source, "Timestep is 10.")
    build(source, index, embedding=False, model_name="", device="cpu", batch_size=8)
    write_paper(source, "Timestep is 20.")

    kb = KnowledgeBase(source, index)
    assert "source hash" in kb.stats()["index_error"]
    assert kb.search("timestep")[0]["answer"] == "Timestep is 20."

    source.unlink()
    catalog = KnowledgeBaseCatalog(tmp_path, main_source=source, main_index=index)
    assert catalog.list()[0]["status"] == "active"
    assert catalog.search("timestep")["results"][0]["answer"] == "Timestep is 10."


def test_legacy_index_matches_content_and_rejects_changes(tmp_path):
    source = tmp_path / "source.jsonl"
    index = tmp_path / "index"
    write_paper(source, "Timestep is 10.")
    build(source, index, embedding=False, model_name="", device="cpu", batch_size=8)
    manifest = index / "manifest.json"
    manifest.write_text(json.dumps({"record_count": 1, "has_faiss_index": False}))
    assert KnowledgeBase(source, index).stats()["index_error"] == ""
    write_paper(source, "Timestep is 20.")
    assert "legacy index" in KnowledgeBase(source, index).stats()["index_error"]


def test_search_attaches_only_evidence_for_returned_version(tmp_path):
    source = tmp_path / "source.jsonl"
    write_paper(source, "Timestep is 10.")
    store = KnowledgeStore(tmp_path / "overlay.sqlite3")
    paper = store.upsert_paper({"paper_id": "paper", "legacy_doc_id": "paper-1", "title": "Demo"})
    versions = []
    for value in (10, 20):
        _, version = store.upsert_qa(paper_id=paper, pair_id=0, question="What timestep is used?",
                                    answer=f"Timestep is {value}.", source_line=1)
        versions.append(version)
        store.add_evidence(qa_version_id=version, paper_id=paper, evidence_text=f"Evidence for {value}.",
                           locator_quality="section", alignment_method="test", alignment_confidence=0.8)
    store.add_evidence(qa_version_id=versions[0], paper_id=paper, evidence_text="Rejected evidence.",
                       locator_quality="section", alignment_method="test", alignment_confidence=1.0,
                       review_status="rejected")
    catalog = KnowledgeBaseCatalog(tmp_path / "configs", main_source=source, overlay_path=store.path)
    result = catalog.search("timestep")["results"][0]
    assert result["qa_version_id"] == versions[0]
    assert result["source_paragraph"] == "Evidence for 10."


def test_doi_lookup_and_unmatched_query(tmp_path):
    source = tmp_path / "source.jsonl"
    write_paper(source, "Timestep is 10.")
    kb = KnowledgeBase(source)
    result = kb.search("https://doi.org/10.1234/demo.42")[0]
    assert result["paper_key"] == "10.1234_demo.42"
    assert result["score"] == 1.0
    assert kb.search("10.1234/demo.99") == []
    assert kb.search("noresultxyz282") == []


def test_vector_prefetch_is_bounded_and_filtered(tmp_path, monkeypatch):
    source = tmp_path / "source.jsonl"
    write_paper(source, "Timestep is 10.")
    kb = KnowledgeBase(source)

    class Index:
        d, ntotal = 3, 2000

        def search(self, query, count):
            assert query.shape == (1, 3)
            assert count == 20
            return np.array([[0.8, 0.05, float("nan")]]), np.array([[0, 1, 2]])

    kb.faiss_index = Index()
    kb.embedding_model = object()
    monkeypatch.setattr(kb, "_query_embedding", lambda query: np.ones((1, 3)))
    assert kb._vector_top("timestep", 20) == {0: 0.8}


def test_evaluation_counts_distinct_papers_and_no_answer_cases(tmp_path):
    source = tmp_path / "source.jsonl"
    write_paper(source, "Timestep is 10.")
    kb = KnowledgeBase(source)
    result = evaluate(kb, [
        {"query": "timestep", "paper_keys": ["10.1234/demo.42", "10.1234/other"]},
        {"query": "noresultxyz282", "paper_keys": []},
    ], top_k=2)
    assert result["hit_rate"] == 1
    assert result["recall_at_k"] == 0.5
    assert 0 < result["ndcg_at_k"] < 1
    assert result["no_answer_accuracy"] == 1
