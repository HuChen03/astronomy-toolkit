"""MCP server: generic file/process/ledger tools for scientific CLI software.

Transport: stdio (default) or streamable-http. The server runs where the
software runs (cluster login node or workstation); all paths are server-side
paths.

HTTP transports carry FastMCP's DNS-rebinding protection. FastMCP auto-enables
it whenever the bind host is a loopback address, allowing only
``127.0.0.1:*`` / ``localhost:*`` / ``[::1]:*``. A request forwarded by a
reverse proxy, tunnel or SSH -L hop keeps the *client-facing* Host header, so
it is rejected with ``421 Invalid Host header``. Use ``--allowed-host`` to
name the front-facing host(s), or ``--no-dns-rebinding-protection`` to drop
the check on a trusted network (see docs/install_and_client.md §2.3).
"""
from __future__ import annotations

import argparse
import hmac
import ipaddress
import os
import platform
import shutil
import signal
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import load_config
from .ledger import Ledger
from .policy import HTTP_TOKEN_VAR
from .processes import ProcessManager

MAX_READ_BYTES = 256 * 1024
MAX_WRITE_BYTES = 4 * 1024 * 1024
MAX_LIST_ENTRIES = 1000

# Mirrors the defaults FastMCP installs for a loopback bind host.
LOOPBACK_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOOPBACK_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _with_http_token(app, token: str):
    expected = f"Bearer {token}".encode()

    async def authenticated(scope, receive, send):
        if scope["type"] == "http":
            actual = Request(scope).headers.get("authorization", "").encode()
            if not hmac.compare_digest(expected, actual):
                response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await app(scope, receive, send)

    return authenticated


def _expand_host(entry: str) -> list[str]:
    """A bare hostname matches only a Host header without port; add the wildcard."""
    entry = entry.strip()
    if not entry:
        return []
    return [entry, f"{entry}:*"] if ":" not in entry else [entry]


def build_transport_security(allowed_hosts=None, allowed_origins=None,
                             disable=False) -> TransportSecuritySettings:
    """Explicit DNS-rebinding policy for HTTP transports.

    Passing a settings object to FastMCP skips its loopback auto-enable, so the
    policy is exactly what is configured here: loopback defaults stay allowed,
    plus every caller-supplied host/origin.

    `disable` turns the Host/Origin check off entirely. It is meant for servers
    reachable only from a trusted network (private cluster, SSH tunnel); the
    JSON-RPC Content-Type check is enforced by the protocol layer regardless.
    """
    hosts = list(LOOPBACK_HOSTS)
    for entry in allowed_hosts or []:
        for host in _expand_host(entry):
            if host not in hosts:
                hosts.append(host)
    origins = list(LOOPBACK_ORIGINS)
    for entry in allowed_origins or []:
        entry = entry.strip()
        if entry and entry not in origins:
            origins.append(entry)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=not disable,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_server(config, transport_security: TransportSecuritySettings | None = None) -> FastMCP:
    ledger = Ledger(config.state_dir)
    procs = ProcessManager(config, ledger)
    mcp = FastMCP(
        "cosmo-exec",
        instructions=(
            "Generic execution layer for scientific CLI software. Paths are "
            "server-side. Prefer argv arrays over shell; use shell=true only "
            "when pipes/redirects/module commands are required. Slurm is "
            "driven through its native CLI (sbatch --parsable, squeue, sacct, "
            "scancel) via exec_run. Every execution is recorded in a ledger "
            "that survives server restarts."
        ),
        transport_security=transport_security,
    )

    # ---------- files ----------

    @mcp.tool()
    def file_read(path: str, offset: int = 0, max_bytes: int = 64 * 1024) -> dict:
        """Read a text file on the server. Returns content plus truncation info.

        offset is a byte offset (use next_offset from a previous call to page).
        """
        p = config.check_path(path)
        if ledger.is_private(p):
            raise PermissionError("run metadata and audit logs are available to the operator only")
        if not p.is_file():
            raise FileNotFoundError(f"not a file: {p}")
        max_bytes = max(1, min(max_bytes, MAX_READ_BYTES))
        total = p.stat().st_size
        off = min(max(offset, 0), total)
        with p.open('rb') as fh:
            fh.seek(off)
            chunk = fh.read(max_bytes)
        return {
            "path": str(p),
            "content": chunk.decode("utf-8", errors="replace"),
            "total_bytes": total,
            "offset": off,
            "next_offset": off + len(chunk),
            "eof": off + len(chunk) >= total,
        }

    @mcp.tool()
    def file_write(path: str, content: str, mode: str = "overwrite") -> dict:
        """Write text to a file on the server. mode: 'overwrite' or 'append'.

        Parent directories are created. Large payloads must be written in
        append chunks (limit 4 MiB per call). Paths inside the server's own
        code, the environment manifest and `paths.protected` are refused; every
        write and every refusal is appended to <state_dir>/audit.jsonl.
        """
        try:
            p = config.check_write_path(path)
        except PermissionError as exc:
            ledger.audit('file_write_denied', path=str(path), reason=str(exc))
            raise
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ValueError(f"content exceeds {MAX_WRITE_BYTES} bytes; split into append chunks")
        p.parent.mkdir(parents=True, exist_ok=True)
        if mode == "overwrite":
            p.write_bytes(data)
        elif mode == "append":
            with open(p, "ab") as fh:
                fh.write(data)
        else:
            raise ValueError("mode must be 'overwrite' or 'append'")
        ledger.audit('file_write', path=str(p), mode=mode, bytes_written=len(data))
        return {"path": str(p), "bytes_written": len(data), "total_bytes": p.stat().st_size, "mode": mode}

    @mcp.tool()
    def file_list(path: str, pattern: str | None = None) -> dict:
        """List a directory on the server (non-recursive). Optional glob pattern."""
        p = config.check_path(path)
        if not p.is_dir():
            raise NotADirectoryError(f"not a directory: {p}")
        entries = []
        it = sorted(p.glob(pattern) if pattern else p.iterdir())
        for child in it:
            try:
                config.check_path(child)
                st = child.stat()
                entries.append(
                    {
                        "name": child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    }
                )
            except OSError:
                continue
            if len(entries) >= MAX_LIST_ENTRIES:
                break
        return {"path": str(p), "entries": entries, "truncated": len(entries) >= MAX_LIST_ENTRIES}

    # ---------- execution ----------

    @mcp.tool()
    def exec_run(
        argv: list[str] | None = None,
        command: str | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env_extra: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> dict:
        """Run a command in the foreground and wait for it (max 3600s).

        Prefer argv (parameter array, no shell interpretation). Set shell=true
        with `command` only when pipes, redirects, or shell built-ins (e.g.
        `module load`) are required. Returns exit code, truncated stdout/stderr
        with truncation metadata, and full-log paths. Long-running work should
        use exec_start or be submitted to Slurm instead. The command is checked
        against the server-side exec policy (deny patterns, optional allowlist,
        shell switch) before anything is spawned; a rejection raises
        PermissionError and is recorded in the audit log.
        """
        return procs.run_foreground(argv, command, shell, cwd, env_extra, timeout)

    @mcp.tool()
    def exec_start(
        argv: list[str] | None = None,
        command: str | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> dict:
        """Start a background process. Returns run_id (the ledger identifier).

        run_id is distinct from the OS pid and from any Slurm job ID. The cwd
        must already exist and lie inside allowed_roots. Output accumulates in
        log files; read it incrementally with exec_output. The recorded `pid`
        is the supervisor process (same process group as the command), not the
        pid of the command itself. The server-side exec policy applies here
        exactly as in exec_run.
        """
        return procs.start_background(argv, command, shell, cwd, env_extra)

    @mcp.tool()
    def exec_output(run_id: str, offset: int = 0, max_bytes: int = 64 * 1024,
                    stderr_offset: int | None = None) -> dict:
        """Read incremental output and status of a background process by run_id.

        offset pages stdout; stderr starts at stderr_offset, or at 0 when that
        is omitted. Returns per-stream {total_bytes, offset, next_offset, eof};
        out-of-range offsets are clamped to the end of the file. A process
        killed by a signal reports a negative exit code (SIGTERM -> -15).
        """
        return procs.read_output(run_id, offset, max(1, min(max_bytes, MAX_READ_BYTES)), stderr_offset)

    @mcp.tool()
    def exec_stop(run_id: str, sig: int = int(signal.SIGTERM)) -> dict:
        """Send SIGTERM, SIGINT or SIGKILL to a background group and report whether it exited."""
        return procs.stop(run_id, sig)

    # ---------- ledger ----------

    @mcp.tool()
    def run_list(limit: int = 20) -> dict:
        """List recent execution records (newest first), including past server sessions."""
        return {"runs": procs.list_runs(limit)}

    @mcp.tool()
    def run_get(run_id: str) -> dict:
        """Get one execution record, refreshed with live process state."""
        return {"meta": procs._refresh(run_id)}

    @mcp.tool()
    def run_attach_slurm(run_id: str, slurm_job_id: str) -> dict:
        """Record the Slurm job ID obtained from `sbatch --parsable` on the submitting run."""
        if not slurm_job_id.strip().isdigit():
            raise ValueError(f"invalid slurm job id: {slurm_job_id!r}")
        meta = ledger.update_meta(run_id, slurm_job_id=slurm_job_id.strip())
        return {"meta": meta}

    # ---------- environment ----------

    @mcp.tool()
    def env_info() -> dict:
        """Server-side environment: host, OS, CPU/RAM, Slurm/MPI tool availability,
        allowed roots, state dir, and the loaded environment manifest summary."""
        slurm = {t: shutil.which(t) for t in ("sbatch", "squeue", "sacct", "scancel", "sinfo")}
        mpi = {t: shutil.which(t) for t in ("mpirun", "mpiexec")}
        slurm_manifest = config.manifest.get("slurm") or {}
        mock_backend = slurm_manifest.get("mock_backend")
        manifest_summary = {
            "path": str(config.manifest_path) if config.manifest_path else None,
            "name": config.manifest.get("name"),
            "software": list((config.manifest.get("software") or {}).keys()),
            "partitions": slurm_manifest.get("partitions"),
        }
        try:
            mem_kb = int(
                next(
                    line.split()[1]
                    for line in open("/proc/meminfo")
                    if line.startswith("MemTotal")
                )
            )
        except Exception:
            mem_kb = None
        return {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "mem_total_gb": round(mem_kb / 1048576, 1) if mem_kb else None,
            "slurm_available": all(slurm.values()),
            "slurm_tools": slurm,
            "slurm_mock_backend": mock_backend,
            "slurm_mock_available": bool(mock_backend) and Path(mock_backend).is_dir(),
            "mpi_tools": mpi,
            "allowed_roots": [str(r) for r in config.allowed_roots],
            "state_dir": str(config.state_dir),
            "audit_log": str(ledger.audit_path),
            "exec_policy": config.exec_policy.describe(),
            "protected_paths": [str(r) for r in config.protected_paths],
            "environment_manifest": manifest_summary,
            "documentation": config.manifest.get("documentation", {}),
        }

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="cosmo-exec MCP server (stdio)")
    parser.add_argument("--env", help="path to environment manifest YAML", default=None)
    parser.add_argument("--state-dir", default=None)
    parser.add_argument("--allowed-root", action="append", default=None,
                        help="repeatable; overrides manifest/env-var roots")
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio",
                        help="stdio（默认，本地/ssh 拉起）或 HTTP 系（长会话更稳，适合常驻登录节点）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--allowed-host", action="append", default=None, metavar="HOST",
                        help="repeatable; extra Host header(s) accepted by DNS-rebinding "
                             "protection, e.g. a proxy/tunnel front name. A bare name also "
                             "accepts any port; use 'host:port' for an exact match. "
                             "Env: COSMO_EXEC_ALLOWED_HOSTS (comma-separated).")
    parser.add_argument("--allowed-origin", action="append", default=None, metavar="ORIGIN",
                        help="repeatable; extra Origin header(s) accepted (browser clients)")
    parser.add_argument("--deny-pattern", action="append", default=None, metavar="REGEX",
                        help="repeatable; adds a site-specific deny regex on top of the "
                             "built-in catastrophic-command table")
    parser.add_argument("--disable-deny-pattern", action="append", default=None, metavar="NAME",
                        help="repeatable; drops one named rule of the built-in deny table "
                             "(names are listed by env_info and quoted in rejections)")
    parser.add_argument("--no-builtin-deny-patterns", action="store_true",
                        help="drop the whole built-in deny table (only for a server whose "
                             "callers are fully trusted)")
    parser.add_argument("--allow-command", action="append", default=None, metavar="NAME",
                        help="repeatable; bind each command to an approved absolute path "
                             "or resolve a name using the server PATH; shell=true is refused")
    parser.add_argument("--no-shell", action="store_true",
                        help="refuse exec_run/exec_start with shell=true")
    parser.add_argument("--protected-path", action="append", default=None, metavar="PATH",
                        help="repeatable; extra path file_write must refuse to write under")
    parser.add_argument("--no-dns-rebinding-protection", action="store_true",
                        help="disable the Host/Origin check on HTTP transports; only for "
                             "servers reachable from a trusted network")
    args = parser.parse_args()

    http_token = os.environ.get(HTTP_TOKEN_VAR, "")
    if args.transport != "stdio" and not _loopback(args.host) and not http_token:
        parser.error(f"non-loopback HTTP requires {HTTP_TOKEN_VAR}")

    allowed_hosts = list(args.allowed_host or [])
    allowed_hosts += [h.strip() for h in os.environ.get("COSMO_EXEC_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if args.no_dns_rebinding_protection and (allowed_hosts or args.allowed_origin):
        parser.error("--no-dns-rebinding-protection conflicts with --allowed-host/--allowed-origin")

    config = load_config(args.env, args.state_dir, args.allowed_root,
                         protected_paths=args.protected_path,
                         deny_patterns=args.deny_pattern,
                         allow_commands=args.allow_command,
                         allow_shell=False if args.no_shell else None,
                         builtin_deny_patterns=False if args.no_builtin_deny_patterns else None,
                         disabled_deny_patterns=args.disable_deny_pattern)
    # None keeps FastMCP's own defaults (loopback bind => protection on) untouched.
    security = None
    if allowed_hosts or args.allowed_origin or args.no_dns_rebinding_protection:
        security = build_transport_security(allowed_hosts, args.allowed_origin,
                                            disable=args.no_dns_rebinding_protection)
        if args.transport == "stdio":
            print("note: --allowed-host/--no-dns-rebinding-protection have no effect on stdio",
                  file=sys.stderr)
    mcp = build_server(config, transport_security=security)
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if http_token:
            import uvicorn

            app = mcp.sse_app() if args.transport == "sse" else mcp.streamable_http_app()
            uvicorn.run(_with_http_token(app, http_token), host=args.host, port=args.port,
                        log_level=mcp.settings.log_level.lower())
        else:
            mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
