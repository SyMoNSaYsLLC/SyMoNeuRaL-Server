"""remix: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import throttled_for

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


@router.post("/api/remix", response_model=ctx.RemixResult, tags=["surfaces"])
async def remix(body: ctx.RemixRequest,
                _: Annotated[None, Depends(throttled_for("remix"))]) -> ctx.RemixResult:
    """Build a sequenced tracklist.

    Remix has no weights of its own -- it asks the chat surface, which is what "one server
    underneath" means in practice, and why it queues behind chat and image.

    Generation only. Resolving tracks against Spotify and writing a playlist needs OAuth
    against a real account, and a stranger's prompt should not reach one; that half runs on
    the box behind admin auth.
    """
    messages = [
        {"role": "system", "content":
         "You are SyMoNeuRaL Remix, a playlist builder. Return exactly a JSON array of "
         f"{body.count} objects, each {{\"artist\": str, \"title\": str, \"why\": str}}, "
         "ordered so the sequence actually flows -- tempo and key matter, this is an "
         "ordered set rather than a pile of songs. 'why' is at most 12 words. Output the "
         "JSON array and nothing else."},
        {"role": "user", "content": body.prompt},
    ]
    async with ctx.gpu.hold("chat"):
        if not await ctx.start_llama():
            raise HTTPException(503, "Chat surface is not available.")
        started = time.time()
        text = "".join([p async for p in ctx.chat_deltas(messages, 900, 0.8)])
        elapsed = time.time() - started

    match = re.search(r"\[.*]", text, re.S)
    try:
        raw = json.loads(match.group(0)) if match else []
    except json.JSONDecodeError:
        raw = []
    tracks = [ctx.Track(**{k: str(t.get(k, ""))[:200] for k in ("artist", "title", "why")})
              for t in raw[:body.count] if isinstance(t, dict)]
    return ctx.RemixResult(
        tracks=tracks, seconds=round(elapsed, 2),
        note=("Generated locally. Resolving these against Spotify and writing the playlist "
              "runs on the box behind admin auth, not from this page."))
