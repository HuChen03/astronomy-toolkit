#!/usr/bin/env python3
"""端到端验证 2：经 MCP 驱动 Arepo（isolated galaxy）与 2LPTIC（与直接 CLI 参照对比）。

Arepo：复制 example 目录 → create.py 逻辑（cp ICs + 写 output_list）→ exec_start 跑
→ check_arepo_run.py。2LPTIC：经 MCP 跑一遍并与 runs/twolptic/small 的参照输出
逐字节对比（同参数同种子应可复现）。
"""
import asyncio
import os
import json
import sys
import time
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client_helpers import mcp_session, mcp_call

ROOT = Path(__file__).resolve().parents[2]
AREPO_RUN = ROOT / "runs" / "arepo" / "isogal" / "run"
AREPO_BIN = ROOT / "runs" / "arepo" / "isogal" / "Arepo"
AREPO_EX = ROOT / "sources/arepo/examples/isolated_galaxy_collisionless_3d"
LPT_RUN = ROOT / "runs" / "twolptic" / "via-mcp"
FAIL = []


def payload(r):
    if r.isError:
        raise RuntimeError(r.content[0].text)
    return json.loads(r.content[0].text)



def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}", flush=True)
    if not ok:
        FAIL.append(name)


async def main():
    async with mcp_session(ROOT / "environments" / "local.yaml", port=8782) as s:
        if True:

            # ---------- Arepo ----------
            param = (AREPO_EX / "param.txt").read_text()
            await mcp_call(s, "file_write", {"path": str(AREPO_RUN / "param.txt"), "content": param})
            # create.py 的实质：cp ICs/ICs snap_010 + 写 output_list.txt
            await mcp_call(s, "exec_run", {
                "argv": ["cp", str(AREPO_EX / "ICs" / "ICs"), str(AREPO_RUN / "snap_010")], "timeout": 60})
            ol = "\n".join(f"{t:g} 1" for t in [i / 9 for i in range(10)]) + "\n"
            await mcp_call(s, "file_write", {"path": str(AREPO_RUN / "output_list.txt"), "content": ol})
            bg = await mcp_call(s, "exec_start", {
                "argv": ["mpirun", "--allow-run-as-root", "-np", "4", str(AREPO_BIN), "param.txt"],
                "cwd": str(AREPO_RUN)})
            print(f"  arepo run_id={bg['run_id']}", flush=True)
            t0 = time.time()
            meta = {}
            while time.time() - t0 < 1500:
                try:
                    out = await mcp_call(s, "exec_output", {"run_id": bg["run_id"]})
                    meta = out["meta"]
                except Exception as e:
                    print(f"  [WARN] 轮询瞬态失败（继续）: {e}", flush=True)
                    await asyncio.sleep(30)
                    continue
                if meta.get("exit_code") is not None:
                    break
                await asyncio.sleep(10)
            check("Arepo isolated galaxy 运行", meta.get("exit_code") == 0,
                  f"exit={meta.get('exit_code')}")
            checker = (ROOT / "skills/arepo/scripts/check_arepo_run.py").read_text()
            await mcp_call(s, "file_write", {"path": str(AREPO_RUN / "check_arepo_run.py"), "content": checker})
            r = await mcp_call(s, "exec_run", {
                "argv": ["python3", "check_arepo_run.py", str(AREPO_RUN)], "timeout": 60})
            check("Arepo 输出检查", "[PASS]" in r["stdout"], r["stdout"].strip().splitlines()[-1] if r["stdout"] else "")

            # ---------- 2LPTIC（与直接 CLI 参照对比） ----------
            param = (ROOT / "skills/twolptic/assets/2LPT-small.param").read_text()
            await mcp_call(s, "file_write", {"path": str(LPT_RUN / "2LPT.param"), "content": param})
            await mcp_call(s, "exec_run", {
                "argv": ["python3", str(ROOT / "skills/twolptic/scripts/make_grid_glass.py"),
                         str(LPT_RUN / "glass.dat"), "1.0"], "timeout": 60})
            (LPT_RUN / "output").mkdir(parents=True, exist_ok=True)
            r = await mcp_call(s, "exec_run", {
                "argv": ["mpirun", "--allow-run-as-root", "-np", "2",
                         str(ROOT / "sources/2lptic/2LPTic"), "2LPT.param"],
                "cwd": str(LPT_RUN), "timeout": 300})
            check("2LPTIC 运行", "IC's generated." in r["stdout"], f"exit={r['exit_code']}")
            ref = (ROOT / "runs/twolptic/small/output/ics.0").read_bytes()
            new = (LPT_RUN / "output/ics.0").read_bytes()
            check("2LPTIC 与直接 CLI 参照一致", ref == new,
                  f"ref={len(ref)}B new={len(new)}B {'identical' if ref == new else 'DIFFER'}")

    print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)}", flush=True)
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
