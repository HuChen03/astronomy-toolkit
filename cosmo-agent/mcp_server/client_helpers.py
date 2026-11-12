"""MCP client sessions with bounded waits and read-only retries.

A lost response to exec_start/exec_run/file_write may mean the operation happened.
Such calls must be reconciled against the ledger; never repeat them blindly.
"""
import asyncio
import contextlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

READ_ONLY = {'env_info', 'file_read', 'file_list', 'exec_output', 'run_list', 'run_get'}


async def mcp_call(session, name, args=None, timeout=120, tries=3):
    attempts = tries if name in READ_ONLY else 1
    for attempt in range(attempts):
        try:
            result = await session.call_tool(name, args or {}, read_timeout_seconds=timedelta(seconds=timeout))
            if result.isError:
                raise RuntimeError(result.content[0].text)
            return json.loads(result.content[0].text)
        except Exception as exc:
            # SDK request deadlines raise McpError; handle only timeout failures.
            timed_out = isinstance(exc, TimeoutError) or 'Timed out while waiting for response' in str(exc)
            if not timed_out:
                raise
            if attempt + 1 == attempts:
                note = ' Check the execution ledger before retrying this operation.' if name not in READ_ONLY else ''
                raise TimeoutError(f'{name}: no response after {attempts} attempt(s).{note}') from exc
            await asyncio.sleep(min(attempt + 1, 3))


@contextlib.asynccontextmanager
async def mcp_session(env_manifest, transport='stdio', port=8777, state=None):
    args = ['-m', 'cosmo_exec.server', '--env', str(env_manifest)]
    if state is not None:
        args += ['--state-dir', str(state)]
    if transport == 'stdio':
        params = StdioServerParameters(command=sys.executable, args=args)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=120)) as session:
                await session.initialize()
                yield session
        return
    if transport != 'http':
        raise ValueError('transport must be stdio or http')
    import httpx
    from mcp.client.streamable_http import streamable_http_client
    # Keep proxy changes local to this client and fail if the port belongs to another server.
    import socket
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
    log_path = Path(state or Path(env_manifest).resolve().parent) / 'http-client-server.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('ab') as log:
        proc = subprocess.Popen([sys.executable, *args, '--transport', 'streamable-http', '--port', str(port)],
                                stdout=log, stderr=log, start_new_session=True)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=120) as http_client:
                # Server startup can take tens of seconds on a loaded compute node.
                for _ in range(600):
                    if proc.poll() is not None:
                        raise RuntimeError(f'MCP server exited; see {log_path}')
                    try:
                        await http_client.get(f'http://127.0.0.1:{port}/mcp')
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.1)
                else:
                    raise TimeoutError(f'MCP HTTP server did not start; see {log_path}')
                async with streamable_http_client(f'http://127.0.0.1:{port}/mcp', http_client=http_client) as (r, w, _):
                    async with ClientSession(r, w, read_timeout_seconds=timedelta(seconds=120)) as session:
                        await session.initialize()
                        yield session
        finally:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.to_thread(proc.wait)
