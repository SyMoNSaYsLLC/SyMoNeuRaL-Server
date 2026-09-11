"""status: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

import time
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from starlette.types import ASGIApp, Receive, Scope, Send  # for RackPowerGate, which is raw ASGI on purpose
from hardware.lib import telemetry
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/api/status", response_model=ctx.Status, tags=["status"],
         responses={304: {"description": "Unchanged since the ETag you sent."}})
async def get_status(request: Request, response: Response) -> ctx.Status | Response:
    """Rack state over plain HTTP, for clients that cannot hold a socket.

    Supports conditional requests. Send back the `ETag` from a previous response as
    `If-None-Match` and an unchanged rack costs a bare `304` instead of the full body --
    which is most of the time, since the machine is idle more than it is busy.

    Prefer the WebSocket at `/api/ws` if you can: it costs one handshake and then sends
    nothing at all until something changes, rather than a request every few seconds to be
    told the same thing.
    """
    # Refresh the card reading OFF the loop before building the rack.
    #
    # `smi()` is synchronous and, on a TTL miss, execs nvidia-smi itself with an 8 s timeout.
    # `telemetry_loop` only refreshes `if bus.listeners` and sleeps 3 s against a 1.0 s TTL --
    # so with no WebSocket client connected it never runs at all, and every poll of this
    # endpoint did that exec ON the event loop. Not latent: it is the normal path, on the one
    # route everything polls, including the watchdog.
    #
    # Guarded by the same TTL so this adds no nvidia-smi traffic -- it only moves the exec
    # that was already happening off the loop. `refresh_telemetry()` is the existing
    # `to_thread` wrapper; :1216 already used it correctly and this call site did not.
    if time.monotonic() - telemetry._telemetry_at > telemetry._TELEMETRY_TTL:
        await telemetry.refresh_telemetry()
    payload = ctx.build_status()
    body = payload.model_dump()
    etag = '"' + ctx.semantic_etag(body) + '"'

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=http.HTTP_304_NOT_MODIFIED,
                        headers={"ETag": etag, "Cache-Control": "no-cache"})

    response.headers["ETag"] = etag
    # no-cache means "revalidate", not "do not store" -- the client keeps the body and
    # spends a conditional request instead of a full one.
    response.headers["Cache-Control"] = "no-cache"
    return payload
