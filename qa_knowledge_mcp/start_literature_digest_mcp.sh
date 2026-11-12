#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/run/literature_digest_mcp.pid"
LOG_FILE="$ROOT/logs/literature_digest_mcp.log"
mkdir -p "$ROOT/run" "$ROOT/logs"
if [[ -f "$PID_FILE" ]]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    echo "daily literature MCP already running: pid=$PID"
    exit 0
  fi
  rm -f "$PID_FILE"
fi
nohup "$ROOT/run_literature_digest_mcp.sh" >>"$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"
echo "started daily literature MCP: pid=$PID log=$LOG_FILE"
