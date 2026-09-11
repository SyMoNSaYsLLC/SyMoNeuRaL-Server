"""asicminer: routes that were declared on `app` in server.py.

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


@router.get("/api/asicminer/firmware", tags=["asicminer"],
         summary="Firmware packages actually present on this machine")
async def asic_firmware(request: Request) -> dict:
    ctx._asic_auth(request)
    # Read off disk rather than from a list in the page, so the model picker cannot claim
    # firmware that is not there, or miss firmware that is.
    return {"packages": asicminer.packages()}
@router.post("/api/asicminer/scan", tags=["asicminer"],
          summary="Discover rigs on a private network")
async def asic_scan(request: Request, body: ctx.ScanBody) -> dict:
    ctx._asic_auth(request)
    if not body.cidr.strip():
        raise HTTPException(400, "give a CIDR, e.g. 10.0.0.0/24")
    return await asicminer.discover(body.cidr.strip())
@router.post("/api/asicminer/emulator", tags=["asicminer"],
          summary="Start, stop or query the QEMU emulator")
async def asic_emulator(request: Request, body: ctx.EmuBody) -> dict:
    ctx._asic_auth(request)
    if body.action == "status":
        return asicminer.emulator_status()
    if body.action == "stop":
        return asicminer.emulator_stop()
    if not body.package:
        raise HTTPException(400, "no package id given")
    return asicminer.emulator_start(body.package)
