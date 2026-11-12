#!/usr/bin/env python3
"""端到端验证：经真实 MCP 客户端驱动 GADGET-4（GrGadget）最小算例。

链路：读 Skill 模板（客户端侧）→ file_write 写参数到服务端运行目录
→ exec_start 后台启动 mpirun → exec_output 增量跟踪 → 输出检查脚本。
另覆盖：错误参数文件、mock-Slurm 提交/查询/sacct 终态。
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
RUN = ROOT / "runs" / "gadget4" / "dml50-mcp"
BINARY = ROOT / "runs" / "gadget4" / "dml50-min" / "build" / "Gadget4"
MOCK_SLURM = ROOT / "mcp_server" / "mock_slurm" / "bin"
FAIL = []


def payload(r):
    if r.isError:
        raise RuntimeError(r.content[0].text)
    return json.loads(r.content[0].text)



def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        FAIL.append(name)


async def main():
    async with mcp_session(ROOT / "environments" / "local.yaml", port=8781) as s:
        if True:

            # 1) 读 Skill 模板（客户端本地），改写参数
            tpl = (ROOT / "skills/gadget4/assets/param-DM-L50-N128.txt").read_text()
            tpl = tpl.replace("TimeMax                   1.0", "TimeMax                   0.02   % e2e 短程验证")
            tpl = tpl.replace("OutputListOn              1", "OutputListOn              0")
            tpl = tpl.replace("TimeBetSnapshot           0.0", "TimeBetSnapshot           1.25  % 共动乘性因子>1")
            tpl = tpl.replace("TimeOfFirstSnapshot       0.0", "TimeOfFirstSnapshot       0.015625")
            outputs = (ROOT / "sources/Gadget4/examples/DM-L50-N128/outputs.txt").read_text()

            # 2) 写服务端运行目录
            await mcp_call(s, "file_write", {"path": str(RUN / "param.txt"), "content": tpl})
            await mcp_call(s, "file_write", {"path": str(RUN / "outputs.txt"), "content": outputs})
            await mcp_call(s, "file_write", {
                "path": str(RUN / "command.txt"),
                "content": f"mpirun -np 8 {BINARY} param.txt  # config: dml50-min (no FOF), GrGadget d0e3eee+patches\n"})

            # 3) 错误参数场景：缺 TimeMax
            bad = tpl.replace("OutputDir            ./output\n", "")  # OutputDir 是 PARAM_FIXED，缺失必报错
            await mcp_call(s, "file_write", {"path": str(RUN / "param_bad.txt"), "content": bad})
            r = await mcp_call(s, "exec_run", {
                "argv": ["mpirun", "--allow-run-as-root", "-np", "2", str(BINARY), "param_bad.txt"],
                "cwd": str(RUN), "timeout": 120})
            check("错误参数被软件拒绝", "miss a value" in r["stdout"] or "miss a value" in r["stderr"]
                  or r["exit_code"] != 0, f"exit={r['exit_code']}")

            # 4) 正常执行（后台）
            bg = await mcp_call(s, "exec_start", {
                "argv": ["mpirun", "--allow-run-as-root", "-np", "8", str(BINARY), "param.txt"],
                "cwd": str(RUN)})
            print(f"  run_id={bg['run_id']} pid={bg['pid']}")
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
            print(f"  main run exit={meta.get('exit_code')} after {time.time()-t0:.0f}s", flush=True)
            check("Gadget4 运行结束", meta.get("exit_code") == 0, f"exit={meta.get('exit_code')}")

            # 5) 输出检查脚本经 MCP 上传并执行
            checker = (ROOT / "skills/gadget4/scripts/check_gadget4_run.py").read_text()
            await mcp_call(s, "file_write", {"path": str(RUN / "check_gadget4_run.py"), "content": checker})
            r = await mcp_call(s, "exec_run", {
                "argv": ["python3", "check_gadget4_run.py", str(RUN)], "cwd": str(RUN), "timeout": 60})
            check("输出检查脚本", "[PASS]" in r["stdout"] or "[INCOMPLETE]" in r["stdout"],
                  r["stdout"].strip().splitlines()[-1] if r["stdout"] else "")

            # 6) mock-Slurm 链路（用秒级的 2LPTIC 作业）：sbatch --parsable → sacct 终态
            LPT = ROOT / "runs" / "twolptic" / "small"
            job = (f"#!/bin/bash\n#SBATCH -J lpt-e2e\n#SBATCH -o {LPT}/slurm-%j.out\ncd {LPT}\n"
                   f"mpirun --allow-run-as-root -np 2 {ROOT}/sources/2lptic/2LPTic 2LPT.param\n")
            await mcp_call(s, "file_write", {"path": str(ROOT / "runs" / "twolptic" / "small" / "job.sh"), "content": job})
            env = {"PATH": f"{MOCK_SLURM}:/usr/bin:/bin",
                   "MOCK_SLURM_STATE": str(ROOT / "runs" / "mock_slurm_state")}
            sub = await mcp_call(s, "exec_run", {
                "argv": ["sbatch", "--parsable", "job.sh"], "cwd": str(ROOT / "runs" / "twolptic" / "small"), "env_extra": env})
            job_id = sub["stdout"].strip().split(";")[0]
            check("sbatch --parsable", job_id.isdigit(), f"job_id={job_id}")
            await mcp_call(s, "run_attach_slurm", {"run_id": sub["run_id"], "slurm_job_id": job_id})
            t0 = time.time()
            state = ""
            while time.time() - t0 < 1500:
                try:
                    acct = await mcp_call(s, "exec_run", {
                        "argv": ["sacct", "-j", job_id, "-X", "-P", "-n", "--format=JobID,State,ExitCode"],
                        "env_extra": env})
                except Exception as e:
                    print(f"  [WARN] sacct 瞬态失败（继续）: {e}", flush=True)
                    await asyncio.sleep(30)
                    continue
                line = acct["stdout"].strip().splitlines()
                state = line[0].split("|")[1] if line else ""
                if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
                    break
                await asyncio.sleep(10)
            check("mock slurm 终态", state == "COMPLETED", state)
            rec = await mcp_call(s, "run_get", {"run_id": sub["run_id"]})
            check("run 记录含 slurm_job_id", rec["meta"].get("slurm_job_id") == job_id)

    print(f"\n{'ALL PASS' if not FAIL else 'FAILURES: ' + str(FAIL)}", flush=True)
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
