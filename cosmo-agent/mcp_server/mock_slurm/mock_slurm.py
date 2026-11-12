#!/usr/bin/env python3
"""Mock Slurm backend for testing the agent submission workflow WITHOUT a real cluster.

Implements sbatch / squeue / sacct / scancel / sinfo with the same CLI shapes
as real Slurm (including --parsable), but runs the job script immediately as a
local background process. State is kept under $MOCK_SLURM_STATE
(default ~/.mock_slurm). This is NOT a scheduler: no queuing semantics, no
resource limits, no nodes. Passing against this backend does not constitute
real-cluster validation.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get("MOCK_SLURM_STATE", Path.home() / ".mock_slurm"))


def _state_dir() -> Path:
    (STATE / "jobs").mkdir(parents=True, exist_ok=True)
    return STATE / "jobs"


def _next_job_id() -> int:
    _state_dir()
    counter = STATE / "next_id"
    n = 1000
    if counter.exists():
        n = int(counter.read_text().strip())
    counter.write_text(str(n + 1))
    return n


def _job_dir(job_id: str) -> Path:
    return _state_dir() / str(job_id).split(".")[0]


def _load(job_id: str) -> dict | None:
    f = _job_dir(job_id) / "meta.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())


def _save(job_id: str, meta: dict) -> None:
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    (_job_dir(job_id) / "meta.json").write_text(json.dumps(meta, indent=2))


def _refresh(meta: dict) -> dict:
    """Recompute state from process liveness / recorded exit code."""
    if meta["state"] in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"):
        return meta
    pid = meta.get("pid")
    alive = False
    if pid:
        try:
            os.kill(pid, 0)
            alive = True
        except (ProcessLookupError, PermissionError):
            alive = False
    now = time.time()
    if alive:
        if meta.get("time_limit_s") and now - meta["start"] > meta["time_limit_s"]:
            _kill(meta)
            meta.update(state="TIMEOUT", exit_code="0:9", end=now)
        elif now - meta["submit"] < 1.0:
            meta["state"] = "PENDING"  # brief pending window to mimic scheduling
        else:
            meta["state"] = "RUNNING"
            meta.setdefault("start", now)
    else:
        ecfile = _job_dir(str(meta["job_id"])) / "exit_code"
        ec = int(ecfile.read_text().strip()) if ecfile.exists() else (meta.get("exit_code_int") or 1)
        meta.update(
            state="COMPLETED" if ec == 0 else "FAILED",
            exit_code=f"{ec}:0",
            end=ecfile.stat().st_mtime if ecfile.exists() else now,
        )
    _save(str(meta["job_id"]), meta)
    return meta


def _kill(meta: dict) -> None:
    pid = meta.get("pid")
    if pid:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass


def _parse_sbatch_script(path: Path) -> dict:
    opts = {}
    for line in path.read_text().splitlines():
        m = re.match(r"#SBATCH\s+(--?\S+?)(?:[ =](.*))?$", line.strip())
        if m:
            opts[m.group(1).lstrip("-")] = (m.group(2) or "").strip()
    return opts


def cmd_sbatch(argv: list[str]) -> int:
    parsable = "--parsable" in argv
    args = [a for a in argv if a != "--parsable"]
    cli_opts = {}
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "--partition", "-J", "--job-name", "-o", "--output", "-e", "--error", "-t", "--time"):
            cli_opts[a.lstrip("-")] = args[i + 1]
            i += 2
        else:
            rest.append(a)
            i += 1
    if not rest:
        print("sbatch: error: no script specified", file=sys.stderr)
        return 1
    script = Path(rest[0])
    if not script.is_file():
        print(f"sbatch: error: Unable to open file {script}", file=sys.stderr)
        return 1
    sopts = _parse_sbatch_script(script)
    get = lambda *names: next((cli_opts.get(n) or sopts.get(n) for n in names if cli_opts.get(n) or sopts.get(n)), None)
    job_id = _next_job_id()
    name = get("J", "job-name") or script.name
    output = get("o", "output") or f"slurm-{job_id}.out"
    time_limit = get("t", "time")
    limit_s = None
    if time_limit:
        try:
            parts = str(time_limit).split(":")
            limit_s = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)  # MM:SS
        except ValueError:
            limit_s = None
    out_path = (script.parent / output).resolve() if not os.path.isabs(output) else Path(output)
    log = open(out_path, "wb")
    jdir = _state_dir() / str(job_id)
    jdir.mkdir(parents=True, exist_ok=True)
    wrapper = f"bash {script.resolve()}; echo $? > {jdir}/exit_code"
    proc = subprocess.Popen(
        ["bash", "-c", wrapper], cwd=script.parent, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    now = time.time()
    meta = {
        "job_id": job_id, "name": name, "partition": get("p", "partition") or "mock",
        "state": "PENDING", "submit": now, "start": now, "end": None,
        "exit_code": None, "pid": proc.pid, "script": str(script.resolve()),
        "output": str(out_path), "time_limit_s": limit_s,
    }
    _save(str(job_id), meta)
    print(job_id if parsable else f"Submitted batch job {job_id}")
    return 0


def _all_jobs() -> list[dict]:
    jobs = []
    for d in sorted(_state_dir().iterdir()):
        meta = _load(d.name)
        if meta:
            jobs.append(_refresh(meta))
    return jobs


def cmd_squeue(argv: list[str]) -> int:
    job_filter = None
    fmt = None
    noheader = "-h" in argv or "--noheader" in argv
    i = 0
    while i < len(argv):
        if argv[i] in ("-j", "--jobs"):
            job_filter = set(argv[i + 1].split(","))
            i += 2
        elif argv[i] in ("-o", "--format"):
            fmt = argv[i + 1]
            i += 2
        else:
            i += 1
    jobs = [j for j in _all_jobs() if j["state"] in ("PENDING", "RUNNING")]
    if job_filter:
        jobs = [j for j in jobs if str(j["job_id"]) in job_filter]
    st_map = {"PENDING": "PD", "RUNNING": "R"}
    if fmt:
        if not noheader:
            print(fmt)
        for j in jobs:
            line = (fmt.replace("%i", str(j["job_id"])).replace("%j", j["name"])
                       .replace("%T", st_map.get(j["state"], j["state"]))
                       .replace("%P", j["partition"])
                       .replace("%M", "0:00").replace("%R", "(mock)"))
            print(line)
    else:
        if not noheader:
            print("JOBID PARTITION     NAME     STATE    TIME")
        for j in jobs:
            print(f"{j['job_id']:>8} {j['partition']:>10} {j['name']:>8} {j['state']:>8} 0:00")
    return 0


def cmd_sacct(argv: list[str]) -> int:
    job_filter = None
    fields = "JobID,JobName,Partition,State,ExitCode,Elapsed"
    noheader = "-n" in argv or "--noheader" in argv
    parsable = "-P" in argv or "--parsable2" in argv or "-p" in argv
    i = 0
    while i < len(argv):
        if argv[i] == "-j":
            job_filter = set(argv[i + 1].split(","))
            i += 2
        elif argv[i].startswith("--format="):
            fields = argv[i].split("=", 1)[1]
            i += 1
        else:
            i += 1
    jobs = _all_jobs()
    if job_filter:
        jobs = [j for j in jobs if str(j["job_id"]) in job_filter]

    def fmt_time(t):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) if t else "Unknown"

    rows = []
    for j in jobs:
        end = j.get("end") or time.time()
        elapsed = int(end - j.get("start", j["submit"]))
        rec = {
            "JobID": str(j["job_id"]), "JobName": j["name"], "Partition": j["partition"],
            "State": j["state"], "ExitCode": j.get("exit_code") or "0:0",
            "Elapsed": f"{elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}",
            "Start": fmt_time(j.get("start")), "End": fmt_time(j.get("end")),
            "NodeList": "mocknode", "AllocCPUS": "1",
        }
        rows.append([rec.get(f, "") for f in fields.split(",")])
    sep = "|" if parsable else "  "
    if not noheader:
        print(sep.join(fields.split(",")))
    for r in rows:
        print(sep.join(r))
    return 0


def cmd_scancel(argv: list[str]) -> int:
    quiet = "-Q" in argv or "--quiet" in argv
    ids = [a for a in argv if a.isdigit()]
    rc = 0
    for jid in ids:
        meta = _load(jid)
        if meta is None:
            if not quiet:
                print(f"scancel: error: Invalid job id {jid}", file=sys.stderr)
            rc = 1
            continue
        meta = _refresh(meta)
        if meta["state"] in ("PENDING", "RUNNING"):
            _kill(meta)
            meta.update(state="CANCELLED", exit_code="0:15", end=time.time())
            _save(jid, meta)
    return rc


def cmd_sinfo(argv: list[str]) -> int:
    print("PARTITION AVAIL  TIMELIMIT  NODES  STATE NODELIST")
    print("mock*        up 7-00:00:00      1   idle mocknode")
    return 0


def main() -> None:
    prog = Path(sys.argv[0]).name
    cmds = {"sbatch": cmd_sbatch, "squeue": cmd_squeue, "sacct": cmd_sacct,
            "scancel": cmd_scancel, "sinfo": cmd_sinfo}
    if prog not in cmds:
        print(f"mock-slurm: unknown command {prog}", file=sys.stderr)
        sys.exit(1)
    sys.exit(cmds[prog](sys.argv[1:]))


if __name__ == "__main__":
    main()
