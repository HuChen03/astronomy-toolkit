#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export QA_SOURCE="${QA_SOURCE:-$ROOT/data/cosmological_simulation/generate_paper.jsonl}"
export QA_MCP_TRANSPORT="${QA_MCP_TRANSPORT:-streamable-http}"
export QA_MCP_HOST="${QA_MCP_HOST:-0.0.0.0}"
export QA_MCP_PORT="${QA_MCP_PORT:-8001}"
export QA_ENABLE_EMBEDDING="${QA_ENABLE_EMBEDDING:-false}"
export QA_ENABLE_RERANKER="${QA_ENABLE_RERANKER:-false}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

MCP_ARGS=(
  --transport "$QA_MCP_TRANSPORT"
  --host "$QA_MCP_HOST"
  --port "$QA_MCP_PORT"
  --source "$QA_SOURCE"
)
if [[ -n "${QA_INDEX:-}" ]]; then
  MCP_ARGS+=(--index "$QA_INDEX")
fi

exec python3 -m qa_knowledge_mcp.mcp_server \
  "${MCP_ARGS[@]}"
