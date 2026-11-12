"""Run ledger: every command execution gets a persistent run directory.

Layout under <state_dir>/runs/<run_id>/:
    meta.json     command, argv, cwd, env additions, timestamps, pid, exit code
    stdout.log    full stdout (also for background processes)
    stderr.log    full stderr

The ledger survives MCP server restarts, so Slurm jobs and background
processes can be tracked after the client disconnects. A run_id is an
MCP-server-side identifier; it is distinct from the local OS pid and from
any Slurm job ID (which is stored in meta.json when known).

Calls that never spawn a process — file writes and policy rejections — have no
run directory, so they append one JSON line to <state_dir>/audit.jsonl instead.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


class Ledger:
    def __init__(self, state_dir: Path):
        self.runs_dir = state_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = state_dir / "audit.jsonl"

    def create(self, *, argv, cwd, shell, env_extra, background) -> tuple[str, Path]:
        run_id = new_run_id()
        rdir = self.runs_dir / run_id
        rdir.mkdir(parents=True)
        meta = {
            "run_id": run_id,
            "argv": argv,
            "shell": shell,
            "cwd": str(cwd),
            "env_extra": env_extra or {},
            "background": background,
            "created_at": time.time(),
            "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pid": None,
            "exit_code": None,
            "finished_at": None,
            "slurm_job_id": None,
        }
        self._write_meta(rdir, meta)
        return run_id, rdir

    def audit(self, event: str, **fields) -> dict:
        """Append one line to the append-only audit log.

        Covers the calls that would otherwise leave no trace: file writes and
        commands rejected by the server policy.
        """
        record = {
            "ts": time.time(),
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def dir(self, run_id: str) -> Path:
        return self.runs_dir / self._check_id(run_id)

    def read_meta(self, run_id: str) -> dict:
        rdir = self.dir(run_id)
        with open(rdir / "meta.json") as fh:
            return json.load(fh)

    def update_meta(self, run_id: str, **fields) -> dict:
        rdir = self.dir(run_id)
        meta = self.read_meta(run_id)
        meta.update(fields)
        self._write_meta(rdir, meta)
        return meta

    def list_runs(self, limit: int = 50) -> list[dict]:
        runs = []
        for rdir in sorted(self.runs_dir.iterdir(), reverse=True):
            if not rdir.is_dir():
                continue
            try:
                with open(rdir / "meta.json") as fh:
                    runs.append(json.load(fh))
            except (OSError, json.JSONDecodeError):
                continue
            if len(runs) >= limit:
                break
        return runs

    @staticmethod
    def _write_meta(rdir: Path, meta: dict) -> None:
        tmp = rdir / "meta.json.tmp"
        with open(tmp, "w") as fh:
            json.dump(meta, fh, indent=2)
        tmp.replace(rdir / "meta.json")

    @staticmethod
    def _check_id(run_id: str) -> str:
        # run_id is server-generated; keep it path-safe anyway
        if not run_id or any(c not in "0123456789abcdef-" and not c.isalnum() for c in run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        if "/" in run_id or ".." in run_id:
            raise ValueError(f"invalid run_id: {run_id!r}")
        return run_id
