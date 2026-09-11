"""live: routes that were declared on `app` in server.py.

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


@router.get("/live-stack/live", include_in_schema=False)
@router.get("/livestack/live", include_in_schema=False)
async def live_page() -> FileResponse:
    """SyMoNeuRaL Live, at the address he asked every app to be at.

    BOTH spellings, added 2026-08-22 with #81's image work. This page was born at
    `/livestack/live` alone, before `/live-stack/coder` established that the hyphenated
    form is served too -- so it was the one application on the rack reachable at one
    spelling, which #81's own title says it should not be: *"/livestack/<name> **and**
    /live-stack/<name> for every application"*. Found by the twin-spelling assertion in
    `apps/test_deploy_routes.py`, not by anyone typing the address.

    *"Applications from the live stack url as https://symoneural.com/chat.html for example.
    They all need to be as such https://symoneural.com/livestack/chat"* — so this one is born
    at `/livestack/live` rather than being migrated there later by #81.

    `/live.html` keeps working, and not by accident: `site/` is mounted at `/` below, so the
    file answers at its own name for anything that already links to it. Two addresses for one
    file is the migration path #81 has to walk for the other nine, and the reason it is cheap
    is that this route does not redirect — a redirect would break a `<video>` mid-playlist,
    since the player resolves segment URIs relative to the manifest it was handed.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = ctx.SITE / "live.html"
    if not f.is_file():
        # Deliberately NOT "run tools/build_<x>.py". There is no generator for this page and
        # there is not meant to be: *"Make sure to update the applications to be static with
        # js css and html"*, so `site/live.html` is hand-authored and tracked. If it is
        # missing, it was deleted or the checkout is partial, and sending the next person to
        # a generator that does not exist is the exact failure `/studio`'s docstring above
        # exists to avoid.
        raise HTTPException(status_code=404,
                            detail="site/live.html is missing. It is a tracked, "
                                   "hand-authored static page with no generator; "
                                   "restore it with git checkout -- site/live.html")
    return FileResponse(f, media_type="text/html")
@router.get("/live-stack/coder", include_in_schema=False)
@router.get("/livestack/coder", include_in_schema=False)
async def coder_page() -> FileResponse:
    """SyMoNeuRaL Coder: the browser surface.

    Hand-authored and tracked, exactly like `site/live.html`, so the 404 below sends the
    next person to `git checkout` rather than to a generator. There is no
    `tools/build_coder.py` and there is not meant to be -- *"Make sure to update the
    applications to be static with js css and html"*. Naming a generator that does not
    exist is the failure `/studio`'s docstring exists to avoid, arriving one page later.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = ctx.SITE / "coder.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="site/coder.html is missing. It is a tracked, "
                                   "hand-authored static page with no generator; "
                                   "restore it with git checkout -- site/coder.html")
    return FileResponse(f, media_type="text/html")
