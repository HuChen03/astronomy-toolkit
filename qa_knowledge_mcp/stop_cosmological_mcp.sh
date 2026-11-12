#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$ROOT/run/cosmological_mcp.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "cosmological MCP is not running"
  exit 0
fi
PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  for _ in $(seq 1 30); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 1
  done
fi
rm -f "$PID_FILE"
echo "stopped cosmological MCP"
