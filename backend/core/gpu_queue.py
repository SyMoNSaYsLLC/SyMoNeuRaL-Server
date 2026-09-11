"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import _try
from core.config import ACQUIRE_TIMEOUT_S, GOVERNOR

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

from core.context import ctx


class GpuQueue:
    """Serialises GPU work.

    The lock is global rather than per-surface because the constraint is physical: 15.92
    GiB does not hold both weight sets, so 'chat is busy' and 'image is busy' are the same
    condition wearing different names.
    """

    def __init__(self, depth: int):
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(depth)
        self.waiting = 0
        self.current: str | None = None

    @asynccontextmanager
    async def hold(self, surface: str):
        """Hold the card for the duration of one job -- and only that.

        This used to be an in-process lock only, while the *governor* lock was taken once
        when llama-server started and kept for as long as the weights stayed loaded. The
        card was therefore marked busy during the 99% of the time chat was merely resident
        and idle, and nothing outside this process could ever get in: a CLI image request
        sat behind it until the 300 s acquire timeout expired.

        Residency and work are different things. llama-server staying loaded is residency,
        tracked by the governor's `resident` file. Holding the lock is work. So the
        governor lock is now taken here, per job, and released the moment the job ends --
        which is what lets `symoneural-cli image` from a terminal take its turn like any other
        tenant, and lets the governor evict a resident-but-idle surface to make room.
        """
        if not _try(self._slots):
            raise HTTPException(
                http.HTTP_503_SERVICE_UNAVAILABLE,
                "The box is busy and the queue is full. Try again shortly.")
        contended = self._lock.locked()
        # Count waiters, not the holder. Incrementing before taking the lock meant a single
        # job with nobody behind it reported queued=1, which tripped the rack into an amber
        # "1 job(s) waiting" banner while the queue was in fact empty.
        if contended:
            self.waiting += 1
        try:
            if contended:
                # Say so before blocking. A client that knows it is third in line behind an
                # image render can show that, or go use RavenCalc, instead of watching a
                # spinner that explains nothing.
                await ctx.bus.announce(surface, "queued", behind=self.current, depth=self.waiting)
            async with self._lock:
                # Now take the cross-process lock. This can block on a CLI job or a
                # fine-tune, so it gets the full acquire timeout and reports honestly if it
                # loses the race rather than proceeding onto a card somebody else owns.
                rc, _out, _err = await ctx.run(str(GOVERNOR), "acquire", surface,
                                           timeout=ACQUIRE_TIMEOUT_S + 15, env_owner=True)
                if rc != 0:
                    raise HTTPException(
                        http.HTTP_503_SERVICE_UNAVAILABLE,
                        "Something else is using the GPU right now -- RavenCalc is on the "
                        "CPU and still available.")
                self.current = surface
                await ctx.bus.announce(surface, "acquired")
                await ctx.push_rack()
                try:
                    yield
                finally:
                    self.current = None
                    await ctx.run(str(GOVERNOR), "release", surface, timeout=90)
                    await ctx.bus.announce(surface, "released")
                    await ctx.push_rack()
        finally:
            if contended:
                self.waiting -= 1
            self._slots.release()
