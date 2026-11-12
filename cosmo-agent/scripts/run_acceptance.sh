#!/usr/bin/env bash
# 验收驱动：128^3 粒子 / 200 Mpc 盒子纯暗物质模拟，经 cosmo-exec MCP 执行。
# 链路：2LPTIC 生成 IC -> GADGET-4（50 快照 + 内建 FoF）-> HBT+（subhalo + merger tree）。
# 用法: run_acceptance.sh [stage] [experiment-dir]   stage ∈ {all,ic,gadget,hbt}
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE="${1:-all}"
EXP="${2:-$ROOT/runs/acceptance/dm128-200mpc-prepared}"
exec python3 "$ROOT/mcp_server/tests/e2e_pipeline.py" "$EXP" \
    --stage "$STAGE" \
    --gadget-binary "$ROOT/sources/Gadget4/build-cosmo-dm128/Gadget4" \
    --timeout 200000 \
    --max-resumes "${MAX_RESUMES:-8}" \
    --port "${PORT:-8787}" \
    --transport http
