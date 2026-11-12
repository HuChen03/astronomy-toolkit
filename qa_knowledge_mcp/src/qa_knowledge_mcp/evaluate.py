from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .knowledge_base import KnowledgeBase
from .paths import COSMOLOGICAL_DATA_ROOT, PROJECT_ROOT


def evaluate(kb: KnowledgeBase, cases: list[dict[str, Any]], *, top_k: int = 10) -> dict[str, Any]:
    hits = 0
    reciprocal_sum = 0.0
    ndcg_sum = 0.0
    rows = []
    for case in cases:
        results = kb.search(case["query"], top_k=top_k)
        expected = set(case.get("paper_keys") or [])
        matched_rank = None
        for rank, result in enumerate(results, start=1):
            if result.get("paper_key") in expected:
                matched_rank = rank
                break
        if matched_rank is not None:
            hits += 1
            reciprocal_sum += 1.0 / matched_rank
            ndcg_sum += 1.0 / math.log2(matched_rank + 1)
        rows.append({"query": case["query"], "rank": matched_rank, "expected": sorted(expected)})
    total = len(cases)
    return {
        "cases": total,
        "hit_rate": hits / total if total else 0.0,
        "mrr": reciprocal_sum / total if total else 0.0,
        "recall_at_k": hits / total if total else 0.0,
        "ndcg_at_k": ndcg_sum / total if total else 0.0,
        "top_k": top_k,
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval against a small paper-level regression set.")
    parser.add_argument("--cases", type=Path, default=PROJECT_ROOT / "config/retrieval_eval.json")
    parser.add_argument("--source", type=Path, default=COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl")
    parser.add_argument("--index", type=Path, default=COSMOLOGICAL_DATA_ROOT / "index")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    kb = KnowledgeBase(args.source, args.index)
    print(json.dumps(evaluate(kb, cases, top_k=args.top_k), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
