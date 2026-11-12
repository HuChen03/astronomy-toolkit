#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/run/literature_digest_mcp.pid"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  HOST="${LDA_MCP_PUBLIC_HOST:-127.0.0.1}"
  PORT="${LDA_MCP_PORT:-8002}"
  echo "running pid=$(cat "$PID_FILE") url=http://${HOST}:${PORT}/mcp"
  exit 0
fi
echo "stopped"
exit 1
