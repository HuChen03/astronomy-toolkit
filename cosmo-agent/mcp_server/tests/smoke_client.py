"""Smoke test: drive cosmo-exec MCP server through a real MCP client (stdio).

Covers: env_info, file write/read/list, foreground exec, error exit code,
missing input, oversized output truncation, timeout, background process +
incremental output + stop, ledger listing, path escape rejection.
"""
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
SERVER_CMD = [
    "python3", "-m", "cosmo_exec.server",
    "--env", str(ROOT / "environments" / "local.yaml"),
]
PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def payload(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


async def main():
    params = StdioServerParameters(command=SERVER_CMD[0], args=SERVER_CMD[1:])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as s:
            await s.initialize()
            tools = await s.list_tools()
            names = {t.name for t in tools.tools}
            expected = {"file_read", "file_write", "file_list", "exec_run", "exec_start",
                        "exec_output", "exec_stop", "run_list", "run_get",
                        "run_attach_slurm", "env_info"}
            check("tool list", expected <= names, str(sorted(names)))

            env = payload(await s.call_tool("env_info", {}))
            check("env_info", env["cpu_count"] > 0 and env["state_dir"], env["hostname"])
            check("env_info slurm absent", env["slurm_available"] is False)

            wdir = ROOT / "runs" / "smoke"
            w = payload(await s.call_tool("file_write", {
                "path": str(wdir / "hello.txt"), "content": "line1\nline2\n"}))
            check("file_write", w["bytes_written"] == 12)
            r = payload(await s.call_tool("file_read", {"path": str(wdir / "hello.txt")}))
            check("file_read", r["content"] == "line1\nline2\n" and r["eof"])
            lst = payload(await s.call_tool("file_list", {"path": str(wdir)}))
            check("file_list", any(e["name"] == "hello.txt" for e in lst["entries"]))

            ok_run = payload(await s.call_tool("exec_run", {
                "argv": ["bash", "-c", "echo out; echo err 1>&2; exit 0"],
                "cwd": str(wdir)}))
            check("exec_run ok", ok_run["exit_code"] == 0 and "out" in ok_run["stdout"])

            bad = payload(await s.call_tool("exec_run", {"argv": ["false"]}))
            check("exec_run nonzero exit", bad["exit_code"] == 1)

            missing = payload(await s.call_tool("exec_run", {
                "argv": ["cat", "does_not_exist.txt"], "cwd": str(wdir)}))
            check("missing input error visible", missing["exit_code"] != 0
                  and "No such file" in missing["stderr"])

            big = payload(await s.call_tool("exec_run", {
                "argv": ["python3", "-c", "print('x'*300000)"]}))
            check("oversized output truncated", big["stdout_info"]["truncated"]
                  and big["stdout_info"]["total_bytes"] > 300000)

            to = payload(await s.call_tool("exec_run", {
                "argv": ["sleep", "30"], "timeout": 2}))
            check("timeout", to["timed_out"] and to["exit_code"] is None)

            bg = payload(await s.call_tool("exec_start", {
                "argv": ["bash", "-c", "for i in 1 2 3; do echo tick$i; sleep 1; done"]}))
            await asyncio.sleep(1.5)
            out1 = payload(await s.call_tool("exec_output", {"run_id": bg["run_id"]}))
            await asyncio.sleep(2.5)
            off = out1["stdout_info"]["next_offset"]
            out2 = payload(await s.call_tool("exec_output", {"run_id": bg["run_id"], "offset": off}))
            check("background incremental output",
                  "tick1" in out1["stdout"] and "tick3" in out2["stdout"]
                  and out2["meta"]["exit_code"] == 0)

            bg2 = payload(await s.call_tool("exec_start", {"argv": ["sleep", "60"]}))
            stopped = payload(await s.call_tool("exec_stop", {"run_id": bg2["run_id"]}))
            check("exec_stop", stopped["stopped"] or stopped["meta"]["exit_code"] is not None)

            runs = payload(await s.call_tool("run_list", {"limit": 5}))
            check("run_list ledger", len(runs["runs"]) >= 3)

            res = await s.call_tool("file_read", {"path": "/etc/passwd"})
            check("path escape rejected", res.isError
                  and ("allowed_roots" in res.content[0].text or "outside" in res.content[0].text))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
