from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

from .knowledge_base import KnowledgeBase, doi_from_paper_key
from .knowledge_catalog import KnowledgeBaseCatalog
from .paths import COSMOLOGICAL_DATA_ROOT, INDEX_ROOT, PROJECT_ROOT
from .versioned_index import active_index


def evaluate(kb: KnowledgeBase | KnowledgeBaseCatalog, cases: list[dict[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    hits = 0
    reciprocal_sum = 0.0
    recall_sum = 0.0
    ndcg_sum = 0.0
    answerable = 0
    no_answer = 0
    correct_abstentions = 0
    latencies = []
    rows = []
    for case in cases:
        started = perf_counter()
        if isinstance(kb, KnowledgeBaseCatalog):
            results = kb.search(case["query"], knowledge_base_ids=case.get("knowledge_base_ids"), top_k=top_k)["results"]
        else:
            results = kb.search(case["query"], top_k=top_k)
        latencies.append((perf_counter() - started) * 1000)
        expected = {_paper_key(key) for key in case["paper_keys"] if key}
        matched_ranks = []
        seen = set()
        for rank, result in enumerate(results[:top_k], start=1):
            key = _paper_key(result.get("paper_key") or "")
            if key in expected and key not in seen:
                matched_ranks.append(rank)
                seen.add(key)
        first = matched_ranks[0] if matched_ranks else None
        if expected:
            answerable += 1
            if first is not None:
                hits += 1
                reciprocal_sum += 1.0 / first
            recall_sum += len(matched_ranks) / len(expected)
            ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(top_k, len(expected)) + 1))
            ndcg_sum += sum(1.0 / math.log2(rank + 1) for rank in matched_ranks) / ideal
        else:
            no_answer += 1
            correct_abstentions += not results
        rows.append({"query": case["query"], "rank": first, "expected": sorted(expected),
                     "matched_papers": sorted(seen), "returned": len(results)})
    latencies.sort()
    return {
        "cases": len(cases),
        "answerable_cases": answerable,
        "no_answer_cases": no_answer,
        "hit_rate": hits / answerable if answerable else 0.0,
        "mrr": reciprocal_sum / answerable if answerable else 0.0,
        "recall_at_k": recall_sum / answerable if answerable else 0.0,
        "ndcg_at_k": ndcg_sum / answerable if answerable else 0.0,
        "no_answer_accuracy": correct_abstentions / no_answer if no_answer else None,
        "p95_ms": round(latencies[math.ceil(len(latencies) * 0.95) - 1], 3) if latencies else None,
        "top_k": top_k,
        "results": rows,
    }


def _paper_key(key: str) -> str:
    key = key.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        key = key.removeprefix(prefix)
    return doi_from_paper_key(key) or key


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against a small paper-level regression set.")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "config/retrieval_eval.json")
    parser.add_argument("--source", type=Path, default=COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--knowledge-base-config", type=Path, default=PROJECT_ROOT / "config/knowledge_bases")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    index = args.index
    if index is None and args.source.resolve() == (COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl").resolve():
        index = active_index(INDEX_ROOT) or COSMOLOGICAL_DATA_ROOT / "index"
    kb = KnowledgeBaseCatalog(args.knowledge_base_config, main_source=args.source, main_index=index)
    print(json.dumps(evaluate(kb, cases, top_k=args.top_k), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
