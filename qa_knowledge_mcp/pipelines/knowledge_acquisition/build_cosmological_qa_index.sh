#!/usr/bin/env bash
set -euo pipefail

MCP_ROOT="${QA_KNOWLEDGE_MCP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SOURCE="${1:-$MCP_ROOT/data/knowledge_acquisition/cosmological_simulation_qa_cache/generate_paper.jsonl}"
OUTPUT="${2:-$MCP_ROOT/data/knowledge_acquisition/cosmological_simulation_qa_index}"

cd "$MCP_ROOT"
export PYTHONPATH="$MCP_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
python -m qa_knowledge_mcp.build_kb "$SOURCE" --output-dir "$OUTPUT" --no-embedding
