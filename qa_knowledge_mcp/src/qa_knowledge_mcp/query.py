from __future__ import annotations

import argparse
import json
from pathlib import Path

from .knowledge_base import KnowledgeBase
from .paths import COSMOLOGICAL_DATA_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description="Query the QA knowledge base.")
    parser.add_argument("question")
    parser.add_argument("--source", type=Path, default=COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl")
    parser.add_argument("--index", type=Path)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    index = args.index
    if index is None and args.source.resolve() == (COSMOLOGICAL_DATA_ROOT / "generate_paper.jsonl").resolve():
        index = COSMOLOGICAL_DATA_ROOT / "index"
    kb = KnowledgeBase(args.source, index)
    print(json.dumps({"query": args.question, "results": kb.search(args.question, args.top_k)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
