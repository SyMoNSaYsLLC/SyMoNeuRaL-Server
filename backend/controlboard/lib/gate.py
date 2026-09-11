"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send  # for RackPowerGate, which is raw ASGI on purpose
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the



class RackPowerGate:
    """Refuse HTTP work on a surface an operator has taken off the rack.

    THIS IS WHAT MAKES THE BUTTON REAL. `.claude/CLAUDE.md`: *"No decorative status
    indicators."* A control that flips a rack row to `offline` while `POST /api/chat` keeps
    answering is the fake activity light with a worse failure mode -- an operator would
    believe a surface was down and act on it. The rack reading in `build_status()` and this
    gate are two halves of one fact, and neither may ship without the other.

    Deliberately a middleware and not an edit to any endpoint. The standing instruction is
    that `api.py`'s existing endpoints, image generation logic and `gpu-governor.sh` calls
    are not to be altered; this touches none of the three. It also means a surface added
    later inherits the switch by adding one line to `rackpower.ROUTES` rather than by
    remembering to paste a guard into a new handler.

    Cost when nothing is switched off: one dict walk over five prefixes. `is_disabled()`
    (which reads the file) is only reached for a path that actually belongs to a governed
    surface, so `/api/status` -- the polled one -- never touches the disk here.

    503 with `Retry-After`, not 404: the surface exists and is coming back. 404 would tell a
    visitor the feature was never built, and the honest answer is that an operator took it
    down and the detail line on the rack says when.

    **Written as a raw ASGI class rather than as `@app.middleware("http")`, and that is not a
    style choice -- it is load-bearing for a defect one layer down. Do not convert it back.**
    `@app.middleware("http")` is `BaseHTTPMiddleware`, which runs the endpoint in a task and
    hands it a *substitute* receive channel. `http.disconnect` never reaches the endpoint's
    own `Request`, so `await request.is_disconnected()` blocks forever instead of answering
    True, and `/api/chat`'s disconnect watchdog -- the thing that gives the GPU lease back
    when a visitor closes the tab -- never fires. Measured here 2026-08-21, four stacks, one
    handler, one abandoned socket:

        bare app                     -> RELEASED   ['saw disconnect', 'released']
        + GZipMiddleware             -> RELEASED   ['saw disconnect', 'released']
        + BaseHTTPMiddleware         -> LEAKED     []
        + this gate as raw ASGI      -> RELEASED   ['saw disconnect', 'released']

    Note the empty list on the third row: neither the watchdog nor the generator's `finally`
    ran at all, so nothing appears in any log to read. GZip is above this in the stack and is
    exonerated by row two -- it is pure ASGI and passes `receive` straight through, as this
    now does. `backend/SMOKE-lease-503.md` has the run.

    What it decides is unchanged from the `BaseHTTPMiddleware` version: same prefix walk, same
    503 body, same `Retry-After`, same position in the stack (added after GZip, so still the
    outer of the two and its 503 is still uncompressed).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # `Request(scope)` with no `receive` bound: this reads the path and nothing else, so
        # the endpoint downstream still owns the one real receive channel. That ownership is
        # the entire point of the class -- see the docstring.
        unit_id = rackpower.unit_for_path(Request(scope).url.path)
        if unit_id is not None and rackpower.is_disabled(unit_id):
            response = JSONResponse(
                status_code=503,
                headers={"Retry-After": "300"},
                content={"error": f"{unit_id} has been taken off the rack by an operator. "
                                  f"It is not faulty and nothing was lost; see the rack on the "
                                  f"home page for when it went down."},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
