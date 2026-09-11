"""studio: routes that were declared on `app` in server.py.

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


@router.get("/api/studio/models", tags=["studio"],
         summary="Models on this machine, read from a pre-computed file",
         dependencies=[Depends(ctx.throttled_for("studio"))])
async def studio_models() -> dict:
    """The model list, as last written by `tools/build/build_registry.py`.

    **`latency_ms` is null on every row, and that is the honest answer today.** Nothing on this
    machine stores a per-model latency: the token rate on the site is a literal in
    `tools/build/build_console.py`, and the only measurement persisted to disk is peak VRAM. The field
    is present so the response shape does not change when a real reading appears; a number will
    only ever be written by something that measured it, for the row it measured.

    An empty `models` with `generated_at: null` means the file has not been written yet -- a
    200 rather than a 404, because this is a list a client polls and an empty list keeps its
    decode path intact. `detail` then names the generator to run, which is the useful half of
    the 404 the section routes raise.

    **Public and unauthenticated, deliberately.** Caddy delegates the whole `/api/*` subtree,
    so this answers anyone. That is a decision, not an oversight: every row states a model name
    the site already publishes, a size, a quantisation and a parameter count -- the numbers, and
    the site's argument is that the numbers are real and checkable. What it does *not* state is
    where any of it lives on disk; `path` is dropped at the validator above. Metered under the
    `studio` bucket so a ceiling can be set without touching this file.
    """
    try:
        doc = json.loads(ctx.STUDIO_REGISTRY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        doc = None
    if not isinstance(doc, dict):
        return {
            "models": [], "generated_at": None, "schema": None,
            "detail": ("run/registry.json has not been generated; "
                       "run python3 tools/build/build_registry.py"),
        }
    generated = doc.get("generated_at")
    schema = doc.get("schema")
    return {
        "models": ctx._studio_rows(doc.get("models")),
        "generated_at": generated if isinstance(generated, int) and not isinstance(generated, bool) else None,
        "schema": schema if isinstance(schema, int) and not isinstance(schema, bool) else None,
        "latency_note": ("null latency means unmeasured, not zero. See the route docstring: no "
                         "per-model timing is recorded on this machine yet."),
        "freshness_note": ("this file is written out-of-band and is not refreshed by this "
                           "request; re-run tools/build/build_registry.py after changing what is on "
                           "disk"),
    }
@router.get("/studio", include_in_schema=False)
async def studio_page() -> FileResponse:
    """The Studio, at a clean address.

    Its own route rather than a `SECTION_PAGES` entry, because `_section_route`'s 404 hardcodes
    *"run python3 tools/build/build_split.py"*. That is true of the four section pages and false of
    this one, and a 404 that names the wrong generator sends the next person to the wrong file.
    Same read-at-request-time behaviour, different instruction.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = ctx.SITE / "studio.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="studio.html has not been generated; "
                                   "run python3 tools/build/build_studio.py")
    return FileResponse(f, media_type="text/html")
