"""dispatchos: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
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


@router.get("/demo/dispatchos/docs", include_in_schema=False)
async def dispatchos_docs() -> HTMLResponse:
    """DispatchOS documentation for the CUSTOMER surface, at the customer's own address.

    Two things make this its own route rather than a link to `/docs/dispatchos`.

    **The audience.** This page renders with `audience="customer"`, which drops every
    operator-only path -- quote, advance, message, rules and drivers. A customer account is
    refused all five, and listing them here would present actions Donnie will be told `403`
    for as things he is supposed to do. The operator's full view is still at
    `/docs/dispatchos`; nothing is hidden from the person entitled to it.

    **The address.** `ops/Caddyfile` puts `/demo/dispatchos` and `/demo/dispatchos/*` behind
    the door, so this page is reachable exactly where the application is and by exactly the
    same people. A customer handed one URL does not have to learn a second one, and the docs
    for a surface behind a door do not sit outside it.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    app_def = appdocs.BY_ID["dispatchos"]
    return HTMLResponse(appdocs.render(
        app_def,
        appdocs.visible_routes("dispatchos", app.routes, audience="customer"),
        audience="customer", docs_root="/docs"))
