"""Foreground and background process execution."""
from __future__ import annotations

import os
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import Config
from .ledger import Ledger
from .policy import ExecPolicy

HEAD_BYTES = 32 * 1024
TAIL_BYTES = 32 * 1024
DEFAULT_TIMEOUT_S = 300
MAX_TIMEOUT_S = 3600


def _process_identity(pid):
    try:
        # Linux /proc stat field 22, after a command name that may contain spaces.
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


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

    def _enforce_policy(self, argv, command, shell) -> None:
        """Apply the server command policy; every rejection is audited.

        Runs before cwd validation and before any run directory is created, so a
        rejected command leaves the ledger clean apart from its audit line.
        """
        try:
            self.policy.check(argv=argv, command=command, shell=shell)
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
        self._enforce_policy(argv, command, shell)
        cwd_path = self.config.check_path(cwd or self.config.allowed_roots[0])
        if cwd_path and not cwd_path.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {cwd_path}")
        cmd = self._build_cmd(argv, command, shell)
        timeout = max(1, min(int(timeout), MAX_TIMEOUT_S))
        env = os.environ.copy()
        if env_extra:
            env.update({str(k): str(v) for k, v in env_extra.items()})

        run_id, rdir = self.ledger.create(
            argv=argv if not shell else ["bash", "-c", command],
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
                proc = subprocess.Popen(cmd, shell=shell, executable='/bin/bash' if shell else None,
                                        cwd=cwd_path, env=env, stdout=stdout, stderr=stderr,
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
        self._enforce_policy(argv, command, shell)
        cwd_path = self.config.check_path(cwd or self.config.allowed_roots[0])
        if cwd_path and not cwd_path.is_dir():
            raise FileNotFoundError(f"cwd does not exist or is not a directory: {cwd_path}")
        cmd = self._build_cmd(argv, command, shell)
        env = os.environ.copy()
        if env_extra:
            env.update({str(k): str(v) for k, v in env_extra.items()})

        run_id, rdir = self.ledger.create(
            argv=argv if not shell else ["bash", "-c", command],
            cwd=cwd_path or Path.cwd(),
            shell=shell,
            env_extra=env_extra,
            background=True,
        )
        (rdir / 'stdout.log').touch()
        (rdir / 'stderr.log').touch()
        try:
            proc = subprocess.Popen(
                [sys.executable, str(Path(__file__).with_name('worker.py')), str(rdir)],
                cwd=cwd_path, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.ledger.update_meta(run_id, exit_code=127, finished_at=time.time(), spawn_error=str(exc))
            raise
        self._live[run_id] = proc
        self.ledger.update_meta(run_id, pid=proc.pid, supervisor=True, pid_start_ticks=_process_identity(proc.pid))
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

    def _refresh(self, run_id: str) -> dict:
        meta = self.ledger.read_meta(run_id)
        proc = self._live.get(run_id)
        result_file = self.ledger.dir(run_id) / 'result.json'
        if result_file.exists():
            if proc is not None:
                proc.poll()  # Reap the supervisor if it has exited.
            if meta['finished_at'] is None:
                meta = self.ledger.update_meta(run_id, **json.loads(result_file.read_text()))
            return meta
        if proc is not None and meta["exit_code"] is None:
            rc = proc.poll()
            if rc is not None:
                if result_file.exists():
                    self.ledger.update_meta(run_id, **json.loads(result_file.read_text()))
                else:
                    self.ledger.update_meta(run_id, exit_code=rc if rc else 127, finished_at=time.time(),
                                            **({'status_note': 'supervisor exited without terminal result; inspect logs'} if meta.get('supervisor') else {}))
                meta = self.ledger.read_meta(run_id)
        elif proc is None and meta["exit_code"] is None and meta.get("pid"):
            # server restarted (or process orphaned): check liveness by pid
            try:
                os.kill(meta["pid"], 0)
                meta["status_note"] = "process alive (tracked by pid after server restart)"
            except ProcessLookupError:
                meta["status_note"] = (
                    "process not running but exit code unknown (server restarted); "
                    "inspect log files and, for Slurm jobs, sacct/squeue"
                )
                meta["exit_code"] = None
            except PermissionError:
                meta["status_note"] = "process exists but owned by another user"
        return meta

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
        meta = self._refresh(run_id)
        if meta["exit_code"] is not None:
            return {"run_id": run_id, "stopped": False, "reason": "already finished", "meta": meta}
        pid = meta.get("pid")
        proc = self._live.get(run_id)
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except ProcessLookupError:
                pass
        elif pid:
            if not meta.get('pid_start_ticks') or _process_identity(pid) != meta['pid_start_ticks']:
                return {'run_id': run_id, 'stopped': False, 'reason': 'process identity cannot be verified after reconnect', 'meta': meta}
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError) as exc:
                return {"run_id": run_id, "stopped": False, "reason": str(exc), "meta": meta}
        else:
            return {"run_id": run_id, "stopped": False, "reason": "no pid recorded", "meta": meta}
        deadline = time.time() + 10
        while time.time() < deadline:
            meta = self._refresh(run_id)
            if meta["exit_code"] is not None:
                break
            time.sleep(0.2)
        return {"run_id": run_id, "stopped": True, "meta": self.ledger.read_meta(run_id)}
