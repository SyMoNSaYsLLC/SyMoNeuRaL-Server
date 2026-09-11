"""status: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import signal
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send  # for RackPowerGate, which is raw ASGI on purpose
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from hardware.lib.gpu import record_engine
from hardware.lib import telemetry
from hardware.lib import modelmetrics  # noqa: E402
from hardware import router as metricsroutes  # noqa: E402
from runtime.lib import runtimeconfig  # noqa: E402
from runtime.lib import symoneuralenv  # noqa: E402
import asicminer  # noqa: E402
import cryptominer  # noqa: E402  -- the GPU miner. A DIFFERENT surface from asicminer:
import coder      # noqa: E402  -- local-only developer surface. Takes NO GPU lease and
import gateway    # noqa: E402  -- TRON licensing surface, see backend/gateway/
import licensing  # noqa: E402  -- contract keys and the dev-fee disclosure
from registry.lib import ports  # noqa: E402
import httpx  # noqa: E402  -- only for polling a delegated surface's /healthz; see poll_delegated
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
import project  # noqa: E402  -- the shared workspace surface. Brings its
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
from streamer.guide import router as guide_routes  # noqa: E402  -- question ->
import sigils  # noqa: E402  -- the sticker surface. Bound to the package for
from accounts import router as accounts_routes  # noqa: E402  -- signup,
import voice  # noqa: E402  -- speech to text on the CPU. Bound to the package so
from studio.plugins import reinforce  # noqa: E402  -- the training bay. Bound to the package so its
import studio  # noqa: E402  -- the local agent and the
from studio.plugins import exp  # noqa: E402  -- the plugin runtime. Bound to an
import news  # noqa: E402  -- the ticker's collector. Bound to
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it
import dispatchos  # noqa: E402  -- the transport dispatch application for a named

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
