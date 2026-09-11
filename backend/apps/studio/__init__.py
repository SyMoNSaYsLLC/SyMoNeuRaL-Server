"""SyMoNeuRaL Studio -- a local reasoning agent with tools, and the visual bench it drives.

Three exports, and they are the whole contract with `api.py`:

    from apps import symoneuralstudio as studio
    app.include_router(studio.router, prefix="/api/studio", tags=["studio"])   # before static
    app.include_router(studio.ui_router, prefix="/studio/editor")               # before static
    Unit(**studio.status())          # the rack row -- same rule as voice: page first
    "studio": (60, 900)              # already present in api.py's _RATE_SUGGESTED

## What is in here, and what is deliberately not

| Module | Does |
|---|---|
| `workspace.py` | finds the live stack on startup and resolves paths against it |
| `registry.py` | turns typed Python functions into JSON Schema tool specs, stdlib only |
| `tools_impl/` | the functions themselves -- filesystem, host, stack, ComfyUI |
| `inference.py` | one interface over llama.cpp and Ollama; neither is spawned here |
| `agent.py` | the cognitive loop: call, execute, feed the raw result back, synthesise |
| `comfy.py` | ComfyUI HTTP + WebSocket, wrapped in the GPU lease cycle |
| `graph.py` | canvas document <-> ComfyUI prompt graph, validated against `/object_info` |
| `workflows.py` | the stock FLUX.1-schnell graph, built for the weights on this disk |
| `mcp_server.py` | the same functions over MCP/FastMCP, from an isolated venv |

**No node canvas is written here.** ComfyUI ships `comfyui_frontend_package` -- the production
editor, with snap-to-grid, typed port wiring, a searchable palette, link-release node
suggestions, per-node progress and inline results. Reimplementing that in vanilla JS was the
original plan and it was the wrong plan: it would have been a worse editor maintained by us
instead of a better one maintained upstream. `ui_router` proxies it at `/studio/editor/` and
the Studio page frames it. Its frontend computes `api_base` from `location.pathname`, so it
addresses `/studio/editor/api/...` on its own with no URL rewriting -- that is a supported
sub-path deployment, not a trick.

## The gate

As of 2026-08-20 no content filtering is implemented on this surface: no content filter, no
path allow-list, no command blocklist -- `run_command` and `write_file` reach the whole host,
and `generate_image` renders whatever it is given. **This is a deliberate pre-launch state,
not a cleared posture.** The standing instruction this paragraph used to cite is held
(request ledger R-98, 2026-08-20) and is being re-scoped per surface, so nothing here should
be read as authority either to strip a control out or to leave one out.

What *is* here is the structural switch this repo already puts on every write-capable surface
(`apps/voice`, `apps/asicminer`): `SYMONEURAL_STUDIO_ENABLED=1` **and** `SYMONEURAL_STUDIO_TOKEN=<secret>`,
off unless both are set. That is not a filter on what the agent may do; it is the difference
between a shell on a box with a public IP being reachable by anyone and being reachable by
Garrett. With both set, it will happily `rm -rf` for him.

`GET /api/studio/state` stays tokenless and reports presence and absence only, following
`apps/gateway` -- the page has to be able to say "the surface is off" without holding a secret.
"""
from __future__ import annotations

import os
import socket
import urllib.parse

from .gate import enabled, token_ok  # noqa: F401

__all__ = ["router", "ui_router", "enabled", "token_ok", "status", "LABEL"]


def __getattr__(name: str):
    """`router` and `ui_router` are imported on first access, not at package import.

    PEP 562, and not for elegance. `routes.py` imports FastAPI; the tools, the registry and
    the workspace do not. `mcp_server.py` runs from an isolated venv holding only `fastmcp`
    -- the house convention for extra dependencies here, and every other app venv in this
    repo is `include-system-site-packages = false` -- so an eager `from .routes import router`
    at the top of this file made `import apps.studio` fail with
    `ModuleNotFoundError: fastapi` inside that venv, which is a real thing that happened
    rather than a hypothetical.

    The alternatives were worse: installing FastAPI into the MCP venv to satisfy an import
    nothing there uses, or letting the MCP server reach into the modules by file path and
    lose the package-relative imports `tools_impl` needs. This costs one function and no
    behaviour -- `api.py` touches `studio.router` at import time, so the routes module is
    still loaded during startup, and a syntax error in it still fails the boot loudly.
    """
    if name in ("router", "ui_router"):
        from . import routes
        return getattr(routes, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


LABEL = "SyMoNeuRaL Studio"

# `enabled()` and `token_ok()` live in `gate.py` and are re-exported here so callers can keep
# saying `studio.enabled()`. See that module for why the split exists (import cycle, not taste).


def comfy_probe() -> tuple[bool, str]:
    """(listening, "host:port") -- one TCP connect to wherever `comfy.base_url()` points.

    A listener is the floor of "confirmed running", not proof of health: the proxy still
    503s a broken server as `comfyui_unreachable` per request. But it is a real reading,
    which is what a rack LED owes (CLAUDE.md: no decorative status indicators), and it is
    cheap -- loopback connection refusal returns in microseconds, so the 0.25 s timeout is
    only ever paid to a hung listener. `comfy` is imported lazily because it imports httpx,
    which the MCP venv does not carry -- the same constraint that keeps `routes` lazy above.
    """
    from . import comfy
    parts = urllib.parse.urlsplit(comfy.base_url())
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True, f"{host}:{port}"
    except OSError:
        return False, f"{host}:{port}"


def status() -> dict:
    """The rack unit, keys matching `api.py`'s `Unit` model.

    Everything reported here is read at call time -- the workspace root from disk, the tool
    count from the registry that actually loaded, the bench from a live TCP connect. `state`
    is `offline` when the switches are unset, when no stack can be found, and when nothing
    answers where `comfy.base_url()` points: `ready` is earned, never assumed. That last arm
    is audit item 27, decided 2026-08-20 -- nothing starts ComfyUI at boot, so a green row
    used to outlive the bench it advertises, and the live rack read `ready` that morning
    while :8188 had nothing listening. It is never `busy`: this row describes the
    orchestrator, and the work it orchestrates is already reported by the surface that does
    it (`comfy`, `chat`). A second row lighting up for somebody else's job is the
    decorative-indicator failure CLAUDE.md forbids.
    """
    from . import registry, workspace, tools_impl  # noqa: F401  (imported for registration)

    if not enabled():
        state = "offline"
        detail = ("set SYMONEURAL_STUDIO_ENABLED=1 to switch it on; "
                  "off by default because it can write to the host")
    else:
        state = "ready"
        if workspace.ROOT is None:
            # A rack row must not be the thing that raises. `workspace.root()` raises when
            # discovery found nothing, and `api.py:build_status()` calls this inline, so one
            # unlocatable checkout took down the whole dashboard. Reported as `offline` because
            # `Unit.state` is `Literal["ready","busy","queued","offline"]` and because a Studio
            # that cannot find the stack cannot do the job the row advertises -- the detail says
            # which switch fixes it.
            state = "offline"
            detail = ("no stack found: set SYMONEURAL_STUDIO_ROOT to the checkout "
                      f"({len(registry.names())} tools registered, none can reach disk)")
        else:
            up, addr = comfy_probe()
            if not up:
                state = "offline"
                detail = (f"ComfyUI is not answering at {addr} -- scripts/symoneural-ui.sh start "
                          "brings the bench back (nothing starts it at boot)")
            else:
                detail = (f"{len(registry.names())} tools · workspace {workspace.ROOT} "
                          f"(found by {workspace.found_by()})")
    return {
        "id": "studio",
        "label": LABEL,
        "slot": "1U",
        "state": state,
        "bus": "gpu",
        "href": "/studio",
        "spec": "local agent · MCP tools · ComfyUI bench",
        "detail": detail,
    }
