#!/usr/bin/env python3
"""The MCP surface: the same tools, over FastMCP, for clients that are not this website.

    backend/apps/studio/.venv/bin/python -m apps.studio.mcp_server
    # or, from the repo root:
    backend/apps/studio/.venv/bin/python backend/apps/studio/mcp_server.py

## Why this file has no tools in it

Because the tools are in `tools_impl/` and this module *iterates the registry*. Every function
here comes from `registry.TOOLS`, which is populated by the `@tool()` decorator on the real
implementations. Add a function to `tools_impl/` with a decorator and it appears on this
surface, on `/api/studio/tool/{name}` and in the agent's system prompt, without being named in
any of the three. There is no second copy of a tool to drift, and that is the entire point of
the two-layer split described in `registry.py`.

The consequence worth stating: **a broken or missing venv costs the MCP transport, not the
tools.** `api.py` imports `registry` and `tools_impl`, which are stdlib + httpx and live in the
serving path. This module is the only thing that needs FastMCP, and it is the only thing that
stops working without it.

## Transport

stdio by default -- that is what Claude Desktop, Claude Code and every other MCP client speaks
without configuration:

    {"mcpServers": {"symoneural-studio": {
        "command": "/home/google/Symoneural/backend/apps/studio/.venv/bin/python",
        "args": ["/home/google/Symoneural/backend/apps/studio/mcp_server.py"],
        "env": {"SYMONEURAL_STUDIO_ENABLED": "1", "SYMONEURAL_STUDIO_TOKEN": "..."}}}}

`--http PORT` serves FastMCP's streamable HTTP transport instead, for a client that cannot
spawn a process. It binds 127.0.0.1 and nothing in `ops/Caddyfile` exposes it; a stdio server
inherits its client's trust, an HTTP one does not, and this box has a public IP.

## The gate applies here too

An MCP client is not a browser and does not present `X-Symoneural-Token`, so the check is on the
*process*: `SYMONEURAL_STUDIO_ENABLED=1` must be set in the environment the server is launched with,
exactly as for the HTTP surface. Without it the server still starts and still lists its tools,
and every call returns the same "switched off" structure the API returns -- listing is how a
client discovers why it is being refused, and a server that exits on startup tells it nothing.

As of 2026-08-20 no content filtering, no path allow-list and no command blocklist are
implemented on this surface: with the switch set, `run_command` and `write_file` reach the
whole host. That is a deliberate pre-launch state, not a cleared posture -- see request ledger
R-98, held 2026-08-20, awaiting re-scope per surface.
"""
from __future__ import annotations

import argparse
import functools
import inspect
import pathlib
import sys

# Run as a script *or* as a module. As a script, `apps.studio` is not importable
# until `backend/` is on the path -- and it must be imported as a package, not as loose
# modules, because `tools_impl` registers itself through relative imports.
_HERE = pathlib.Path(__file__).resolve()
_BACKEND = _HERE.parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from apps.studio import gate, registry, workspace  # noqa: E402
from apps.studio import tools_impl  # noqa: E402,F401  -- imported to register

try:
    # The vendor name lives in `mcpframework.py` and nowhere else in this package
    # (task #74 item 5). The facade does not catch this itself: the message below is
    # the only place that can name the entrypoint to re-run, so it stays here.
    from apps.studio.mcpframework import FastMCP  # noqa: E402
except ImportError:  # pragma: no cover - the whole point of the message is that it is rare
    sys.exit(
        "fastmcp is not importable.\n"
        "\n"
        "This module is the only thing in the package that needs it, and it must not be\n"
        "installed into the system interpreter -- that is the serving path, and\n"
        ".claude/CLAUDE.md forbids it. Build the isolated venv instead:\n"
        "\n"
        f"    python3 -m venv {_HERE.parent}/.venv\n"
        f"    {_HERE.parent}/.venv/bin/pip install -r {_HERE.parent}/requirements.txt\n"
        f"    {_HERE.parent}/.venv/bin/python {_HERE}\n")

mcp = FastMCP(
    name="symoneural-studio",
    instructions=(
        "Tools for the machine SyMoNeuRaL runs on: its filesystem, its process table, its "
        "single RTX 5070 Ti behind a governor mutex, and its local image pipeline (ComfyUI, "
        "FLUX.1-schnell). Paths given without a leading slash resolve against the repository "
        "root, not the working directory. The GPU is one card shared by chat, image and "
        "training, so a render acquires a lease and gives it back; if a call reports the card "
        "is busy, that is another surface holding it and retrying later is the answer."),
)

_OFF = {
    "error": "studio_disabled",
    "detail": ("this MCP server was launched without SYMONEURAL_STUDIO_ENABLED=1 (and a "
               "SYMONEURAL_STUDIO_TOKEN). It reaches the whole host, so it is off unless the "
               "operator switches it on in the environment it is launched with."),
}


def _register(entry: registry.Tool) -> None:
    """Wrap one registry entry as a FastMCP tool.

    `functools.wraps` is load-bearing here, not tidiness. FastMCP derives its schema with
    `inspect.signature`, which follows `__wrapped__` -- so the client sees the *original*
    function's typed, defaulted, documented signature rather than the wrapper's. Without it
    FastMCP raises `Functions with **kwargs are not supported as tools` and the server does
    not start at all, which is the first thing that happened when this was written.

    The wrapper exists only to apply the process switch. It adds no logic to the tool.
    """
    @functools.wraps(entry.fn)
    async def run(*args, **kwargs):
        if not gate.enabled():
            return _OFF
        bound = inspect.signature(entry.fn).bind(*args, **kwargs)
        return await registry.call(entry.name, dict(bound.arguments))

    mcp.tool(
        name=entry.name,
        description=(entry.description
                     + ("\n\n[writes to the host]" if entry.dangerous else "")),
    )(run)


for _name in registry.names():
    _register(registry.TOOLS[_name])


@mcp.resource("symoneural://workspace")
def workspace_resource() -> dict:
    """Where this server decided the live stack is, and how it worked that out."""
    return workspace.describe()


@mcp.resource("symoneural://tools")
def tool_index() -> dict:
    """The registry itself, grouped -- a client can read this instead of guessing at names."""
    grouped: dict[str, list[dict]] = {}
    for name in registry.names():
        t = registry.TOOLS[name]
        grouped.setdefault(t.group, []).append(
            {"name": t.name, "writes": t.dangerous, "description": t.description})
    return {"enabled": gate.enabled(), "count": len(registry.names()), "groups": grouped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--http", type=int, metavar="PORT",
                    help="serve streamable HTTP on 127.0.0.1:PORT instead of stdio")
    args = ap.parse_args(argv)

    # stderr, never stdout: stdout *is* the MCP transport in the default mode, and a stray
    # print there corrupts the first frame in a way that reads as a client bug.
    # `workspace.ROOT`, not `workspace.root()`: this line is a banner. Raising here would mean
    # the server refuses to start on a checkout it cannot locate, when most of what it serves
    # (`env_get`, `gpu_status`, `service_status`) does not need a workspace at all.
    print(f"symoneural-studio: {len(registry.names())} tools, "
          f"workspace {workspace.ROOT or 'NOT FOUND (set SYMONEURAL_STUDIO_ROOT)'}, "
          f"switch {'on' if gate.enabled() else 'OFF'}", file=sys.stderr)

    if args.http:
        mcp.run(transport="http", host="127.0.0.1", port=args.http)
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
