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

export LDA_MCP_TRANSPORT="${LDA_MCP_TRANSPORT:-streamable-http}"
export LDA_MCP_HOST="${LDA_MCP_HOST:-0.0.0.0}"
export LDA_MCP_PORT="${LDA_MCP_PORT:-8002}"
export LDA_DATABASE_PATH="${LDA_DATABASE_PATH:-$ROOT/data/literature_digest/literature_digest.sqlite3}"
export LDA_DISCIPLINE="${LDA_DISCIPLINE:-cond-mat}"
export LDA_TIMEZONE="${LDA_TIMEZONE:-Asia/Shanghai}"
export LDA_CUTOFF_HOUR="${LDA_CUTOFF_HOUR:-8}"
export LDA_KEYWORDS_PATH="${LDA_KEYWORDS_PATH:-$ROOT/config/daily_categories.json}"

exec python3 -m literature_digest_agent.mcp_server \
  --transport "$LDA_MCP_TRANSPORT" \
  --host "$LDA_MCP_HOST" \
  --port "$LDA_MCP_PORT"
