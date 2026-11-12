#!/usr/bin/env python3
"""Call cosmo-exec MCP tools from a shell, one tool per invocation.

This is a transport bridge, not a second API: it speaks to the same MCP server
as a natively mounted client would, so the tool names, arguments and return
values are exactly those in the cosmo-exec Skill. Use it when the Agent client
does not mount MCP servers (or for scripted checks), not as a replacement for
the Skill's execution conventions.

Usage:
  mcp_cli.py [options] --list-tools
  mcp_cli.py [options] <tool> '{json args}'
  mcp_cli.py [options] <tool> key=value [key=value ...]
  mcp_cli.py [options] <tool> -            # read the JSON args object from stdin

Examples:
  mcp_cli.py env_info
  mcp_cli.py file_list path=runs
  mcp_cli.py exec_run '{"argv":["rg","-n","OutputListOn","sources/Gadget4/documentation"],"cwd":"."}'
  mcp_cli.py exec_run 'argv=["/bin/echo","hi"]' cwd=/tmp

Value parsing: a bare value that is valid JSON (number, true/false/null, quoted
string, array, object) is passed through as that type; anything else is a plain
string. Quote values that contain spaces.

Options:
  --transport {stdio,http}  MCP transport (default: stdio)
  --port N                  HTTP port for --transport http (default: 8788)
  --url URL                 attach to an already running streamable-HTTP MCP
                            server instead of spawning one (e.g. the cosmo-exec
                            server another process started, or a remote login
                            node); no local socket setup, so this also works
                            where spawning servers is not permitted
  --env PATH                environment manifest (default: environments/local.yaml)
  --state-dir PATH          ledger directory override
  --timeout S               per-call timeout in seconds (default: 300)
  --raw                     print compact single-line JSON
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'mcp_server'))
from client_helpers import mcp_session, mcp_call  # noqa: E402


def parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_args(tokens: list[str]) -> dict:
    if len(tokens) == 1:
        token = tokens[0]
        if token == '-':
            data = json.load(sys.stdin)
            if not isinstance(data, dict):
                raise SystemExit('stdin JSON must be an object')
            return data
        if token.lstrip().startswith('{'):
            data = json.loads(token)
            if not isinstance(data, dict):
                raise SystemExit('the JSON argument must be an object')
            return data
    if not tokens:
        return {}
    args: dict = {}
    for token in tokens:
        if '=' not in token:
            raise SystemExit(f'expected key=value or a JSON object, got {token!r}')
        key, value = token.split('=', 1)
        args[key] = parse_value(value)
    return args


@contextlib.asynccontextmanager
async def connect(url: str, timeout: int):
    """Attach to an existing streamable-HTTP MCP server (no local process)."""
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(trust_env=False, timeout=timeout) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write,
                                     read_timeout_seconds=timedelta(seconds=timeout)) as session:
                await session.initialize()
                yield session


async def run(args) -> int:
    manifest = args.env
    if args.url:
        session_cm = connect(args.url, args.timeout)
    else:
        session_cm = mcp_session(manifest, transport=args.transport, port=args.port, state=args.state_dir)
    async with session_cm as session:
        if args.list_tools:
            tools = await session.list_tools()
            for tool in tools.tools:
                first = (tool.description or '').strip().splitlines()
                print(f'{tool.name}\t{first[0] if first else ""}')
            return 0
        if not args.tool:
            raise SystemExit('no tool given; see --help')
        result = await mcp_call(session, args.tool, args.call_args, timeout=args.timeout)
        print(json.dumps(result, ensure_ascii=False) if args.raw else json.dumps(result, ensure_ascii=False, indent=2))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--transport', choices=['stdio', 'http'], default='stdio')
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--env', type=Path, default=ROOT / 'environments' / 'local.yaml')
    parser.add_argument('--url', default=None, help='attach to a running MCP HTTP server')
    parser.add_argument('--state-dir', type=Path, default=None)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--raw', action='store_true')
    parser.add_argument('--list-tools', action='store_true')
    parser.add_argument('tool', nargs='?')
    parser.add_argument('call', nargs='*', help='JSON object or key=value pairs')
    args = parser.parse_args()
    args.call_args = parse_args(args.call)
    args.env = args.env.resolve()
    if not args.env.is_file():
        raise SystemExit(f'manifest not found: {args.env}')
    try:
        return asyncio.run(run(args))
    except Exception as exc:  # surface the server-side message, not a traceback
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
