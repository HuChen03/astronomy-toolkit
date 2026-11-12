#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/run/cosmological_mcp.pid"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  HOST="${QA_MCP_PUBLIC_HOST:-127.0.0.1}"
  PORT="${QA_MCP_PORT:-8001}"
  echo "running pid=$(cat "$PID_FILE") url=http://${HOST}:${PORT}/mcp"
  exit 0
fi
echo "stopped"
exit 1
