"""Foreground and background process execution."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .ledger import Ledger
from .policy import HTTP_TOKEN_VAR

HEAD_BYTES = 32 * 1024
TAIL_BYTES = 32 * 1024
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600
STOP_WAIT_S = 10


def _process_identity(pid):
    try:
        # Linux /proc stat field 22, after a command name that may contain spaces.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A supervisor owned by another MCP session can still be a zombie.
    # Check group members so an exited group is not reported as still running.
    try:
        rows = subprocess.check_output(["/bin/ps", "-axo", "pgid=,stat="], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return True
    return any(group == str(pid) and not status.startswith("Z")
               for group, status in (line.split() for line in rows.splitlines() if line.strip()))


def _read_summary(path: Path) -> tuple[str, dict]:
    total = path.stat().st_size
    with path.open('rb') as fh:
        if total <= HEAD_BYTES + TAIL_BYTES:
            return _truncated(fh.read())
        head = fh.read(HEAD_BYTES).decode('utf-8', errors='replace')
        fh.seek(-TAIL_BYTES, os.SEEK_END)
        tail = fh.read(TAIL_BYTES).decode('utf-8', errors='replace')
    return (head + f'\n...[truncated {total - HEAD_BYTES - TAIL_BYTES} bytes; full output in log file]...\n' + tail,
            {'total_bytes': total, 'truncated': True, 'head_bytes': HEAD_BYTES, 'tail_bytes': TAIL_BYTES})


def _truncated(data: bytes) -> tuple[str, dict]:
    """Return text plus truncation metadata. Full output always lives in log files."""
    total = len(data)
    if total <= HEAD_BYTES + TAIL_BYTES:
        return data.decode("utf-8", errors="replace"), {
            "total_bytes": total,
            "truncated": False,
        }
    head = data[:HEAD_BYTES].decode("utf-8", errors="replace")
    tail = data[-TAIL_BYTES:].decode("utf-8", errors="replace")
    return (
        head
        + f"\n...[truncated {total - HEAD_BYTES - TAIL_BYTES} bytes; full output in log file]...\n"
        + tail,
        {
            "total_bytes": total,
            "truncated": True,
            "head_bytes": HEAD_BYTES,
            "tail_bytes": TAIL_BYTES,
        },
    )


class ProcessManager:
    """Tracks live background Popen objects for this server process.

    run_id doubles as the MCP-session process identifier returned to the
    client. It is *not* the OS pid (stored in meta.json) and *not* a Slurm
    job ID.
    """

    def __init__(self, config: Config, ledger: Ledger):
        self.config = config
        self.ledger = ledger
        self._live: dict[str, subprocess.Popen] = {}
        self.policy = config.exec_policy

    def _prepare_command(self, argv, command, shell, env_extra):
        cmd = self._build_cmd(argv, command, shell)
        try:
            self.policy.check(argv=argv, command=command, shell=shell)
            resolved = ["/bin/bash", "-c", cmd] if shell else self.policy.bind(cmd)
            return resolved, self.policy.environment(env_extra)
        except PermissionError as exc:
            self.ledger.audit('exec_denied', reason=str(exc), argv=argv,
                              command=command if shell else None, shell=shell)
            raise

    def _build_cmd(self, argv: list[str] | None, command: str | None, shell: bool):
        if shell:
            if not command:
                raise ValueError("shell=true requires `command`")
            return command
        if not argv or not all(isinstance(a, str) and a for a in argv):
            raise ValueError("argv must be a non-empty list of strings (or use shell=true with `command`)")
        return argv

    def run_foreground(
        self,
        argv: list[str] | None = None,
        command: str | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env_extra: dict[str, str] | None = None,
        timeout: int = DEFAULT_TIMEOUT_S,
    ) -> dict:
        cmd, env = self._prepare_command(argv, command, shell, env_extra)
        cwd_path = self.config.check_path(cwd or self.config.allowed_roots[0])
        if cwd_path and not cwd_path.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {cwd_path}")
        timeout = max(1, min(int(timeout), MAX_TIMEOUT_S))
        run_id, rdir = self.ledger.create(
            argv=cmd,
            cwd=cwd_path or Path.cwd(),
            shell=shell,
            env_extra=env_extra,
            background=False,
        )
        stdout_path, stderr_path = rdir / "stdout.log", rdir / "stderr.log"
        started = time.time()
        timed_out = False
        with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            try:
                proc = subprocess.Popen(cmd, cwd=cwd_path, env=env, stdin=subprocess.DEVNULL,
                                        stdout=stdout, stderr=stderr,
                                        start_new_session=True)
                self.ledger.update_meta(run_id, pid=proc.pid)
                try:
                    exit_code = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
                    stderr.write(f'\n[cosmo-exec] timed out after {timeout}s; process group killed\n'.encode())
                    exit_code = None
            except OSError as exc:
                stderr.write(f'[cosmo-exec] failed to start: {exc}\n'.encode())
                exit_code = 127
        self.ledger.update_meta(
            run_id, exit_code=exit_code, finished_at=time.time(), timed_out=timed_out
        )
        out_text, out_info = _read_summary(stdout_path)
        err_text, err_info = _read_summary(stderr_path)
        return {
            "run_id": run_id,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "duration_s": round(time.time() - started, 3),
            "stdout": out_text,
            "stderr": err_text,
            "stdout_info": out_info,
            "stderr_info": err_info,
            "log_files": {"stdout": str(stdout_path), "stderr": str(stderr_path)},
        }

    def start_background(
        self,
        argv: list[str] | None = None,
        command: str | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> dict:
        cmd, env = self._prepare_command(argv, command, shell, env_extra)
        cwd_path = self.config.check_path(cwd or self.config.allowed_roots[0])
        if cwd_path and not cwd_path.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {cwd_path}")
        run_id, rdir = self.ledger.create(
            argv=cmd,
            cwd=cwd_path or Path.cwd(),
            shell=shell,
            env_extra=env_extra,
            background=True,
        )
        (rdir / 'stdout.log').touch()
        (rdir / 'stderr.log').touch()
        supervisor_env = os.environ.copy()
        supervisor_env.pop(HTTP_TOKEN_VAR, None)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name('worker.py')), str(rdir)],
                cwd=cwd_path, env=supervisor_env, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.ledger.update_meta(run_id, exit_code=127, finished_at=time.time(), spawn_error=str(exc))
            raise
        try:
            with proc.stdin as pipe:
                pipe.write(json.dumps({"argv": cmd, "env": env}).encode())
        except OSError as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            self.ledger.update_meta(run_id, exit_code=127, finished_at=time.time(), spawn_error=str(exc))
            raise
        self._live[run_id] = proc
        self.ledger.update_meta(run_id, pid=proc.pid, supervisor=True, pid_start_ticks=_process_identity(proc.pid),
                                pid_boot_id=_boot_id())
        return {
            "run_id": run_id,
            "pid": proc.pid,
            "log_files": {
                "stdout": str(rdir / "stdout.log"),
                "stderr": str(rdir / "stderr.log"),
            },
            "note": "run_id is the ledger identifier; pid is the OS pid of the supervisor "
            "process that owns the command's process group (not the command's own pid); "
            "a Slurm job ID (if any) is separate and recorded in meta.json once known",
        }

    def _owns_supervisor(self, run_id: str, meta: dict) -> bool:
        pid = meta.get("pid")
        if not pid or not meta.get("supervisor"):
            return False
        proc = self._live.get(run_id)
        if proc is not None:
            return proc.poll() is None
        if not meta.get("pid_start_ticks") or _process_identity(pid) != meta["pid_start_ticks"]:
            return False
        if meta.get("pid_boot_id") and meta["pid_boot_id"] != _boot_id():
            return False
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            return os.fsencode(str(self.ledger.dir(run_id))) in args and os.getpgid(pid) == pid
        except OSError:
            return False

    def _refresh(self, run_id: str) -> dict:
        meta = self.ledger.read_meta(run_id)
        proc = self._live.get(run_id)
        code = proc.poll() if proc is not None else None
        if code is not None:
            self._live.pop(run_id, None)
        result = self.ledger.dir(run_id) / 'result.json'
        if meta["finished_at"] is None and result.is_file():
            meta = self.ledger.update_meta(run_id, **json.loads(result.read_text()))
        elif meta["finished_at"] is None and code is not None:
            meta = self.ledger.update_meta(
                run_id, exit_code=code or 127, finished_at=time.time(),
                status_note='supervisor exited without terminal result; inspect logs',
            )

        if meta["finished_at"] is not None:
            status = "timed_out" if meta.get("timed_out") else "exited"
        elif self._owns_supervisor(run_id, meta):
            status = "stopping" if meta.get("stop_requested_at") else "running"
        else:
            status = "unknown"
        return self.ledger.public_meta({**meta, "status": status})

    def list_runs(self, limit: int = 20) -> list[dict]:
        return [self._refresh(meta["run_id"]) for meta in self.ledger.list_runs(max(1, min(limit, 200)))]

    def read_output(self, run_id: str, offset: int = 0, max_bytes: int = 64 * 1024,
                    stderr_offset: int | None = None) -> dict:
        meta = self._refresh(run_id)
        rdir = self.ledger.dir(run_id)
        result = {"run_id": run_id, "meta": meta}
        for stream in ("stdout", "stderr"):
            path = rdir / f"{stream}.log"
            if not path.exists():
                result[stream] = ""
                result[f"{stream}_info"] = {"total_bytes": 0, "offset": offset, "next_offset": 0}
                continue
            total = path.stat().st_size
            # `offset` pages stdout only. stderr has its own cursor: when the caller
            # does not pass stderr_offset we start from 0, so incremental stdout reads
            # never silently skip an equal-length prefix of stderr.
            if stream == 'stderr':
                stream_offset = stderr_offset if stderr_offset is not None else 0
            else:
                stream_offset = offset
            off = min(max(stream_offset, 0), total)
            with path.open('rb') as fh:
                fh.seek(off)
                chunk = fh.read(max(1, min(max_bytes, 256 * 1024)))
            result[stream] = chunk.decode("utf-8", errors="replace")
            result[f"{stream}_info"] = {
                "total_bytes": total,
                "offset": off,
                "next_offset": off + len(chunk),
                "eof": off + len(chunk) >= total,
            }
        return result

    def stop(self, run_id: str, sig: int = signal.SIGTERM) -> dict:
        if sig not in {signal.SIGTERM, signal.SIGINT, signal.SIGKILL}:
            raise ValueError("stop accepts SIGTERM, SIGINT, or SIGKILL")
        meta = self._refresh(run_id)
        response = {"run_id": run_id, "stopped": False, "signal_sent": False}
        if meta["finished_at"] is not None:
            return {**response, "reason": "already finished", "meta": meta}
        if not self._owns_supervisor(run_id, meta):
            return {**response, "reason": "process identity cannot be verified", "meta": meta}
        pid = meta["pid"]
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, PermissionError) as exc:
            return {**response, "reason": str(exc), "meta": self._refresh(run_id)}

        self.ledger.update_meta(run_id, stop_requested_at=time.time())
        response["signal_sent"] = True
        deadline = time.monotonic() + STOP_WAIT_S
        while True:
            meta = self._refresh(run_id)
            if meta["status"] != "stopping" and not _group_alive(pid):
                return {**response, "stopped": True, "meta": meta}
            if time.monotonic() >= deadline:
                return {**response, "reason": "process group still exists", "meta": meta}
            time.sleep(0.1)
