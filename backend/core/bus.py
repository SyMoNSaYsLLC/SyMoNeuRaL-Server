"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
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

from core.context import ctx


class Bus:
    """The three-way channel: frontend <-> backend, agent <-> agent, agent <-> user.

    Polling was the alternative and it is genuinely wasteful. The rack asked /api/status
    every 2.5 seconds per open tab and almost always learned nothing -- a full request,
    response, and header set to be told the state had not changed. One upgraded connection
    plus a push when something actually happens is fewer bytes, fewer wakeups, and less
    power on both ends.

    Two rules keep it that way:

    **Only on change.** Every publish is diffed against the last frame sent and dropped if
    identical. A socket that chatters on a timer is just polling with extra steps.

    **Agents publish, they do not address.** A surface announces what it did -- acquired the
    card, started a render, released -- and every listener decides what that means to it.
    The rack redraws, a waiting client learns why it is waiting, and another agent can react,
    all from one event and one send.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._last: str | None = None
        # Baseline per connection, not one global. A single shared snapshot let a late
        # joiner reset the diff baseline for everybody: the delta against the newer
        # baseline came out empty, so clients already connected never learned about the
        # change and stayed wrong for those fields forever.
        self._snapshots: dict[int, dict] = {}

    async def join(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def leave(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
            self._snapshots.pop(id(ws), None)

    @property
    def listeners(self) -> int:
        return len(self._clients)

    def seed(self, ws: WebSocket, snapshot: dict) -> None:
        """Record the baseline this particular client was just given."""
        self._snapshots[id(ws)] = snapshot

    async def publish_delta(self, snapshot: dict) -> None:
        """Send only what moved since the last push.

        The client holds the rack state and patches it, so the wire carries the change
        rather than the world. A chat request starting is genuinely four fields --
        one unit's state, the holder, the queue depth, a VRAM figure -- and re-sending the
        whole rack to say that is most of a kilobyte to communicate about forty bytes of
        news. Over a night of traffic with several tabs open that is the difference between
        a socket that whispers and one that shouts the same sentence repeatedly.

        The baseline comes from the snapshot sent at handshake, so a client is never asked
        to patch state it does not have.
        """
        async with self._lock:
            targets = list(self._clients)
        dead = []
        for ws in targets:
            baseline = self._snapshots.get(id(ws))
            delta = ctx._diff(baseline, snapshot) if baseline else {}
            self._snapshots[id(ws)] = snapshot
            if not delta:
                continue
            try:
                await ws.send_text(json.dumps({"t": "patch", **delta}, separators=(",", ":")))
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
                    self._snapshots.pop(id(ws), None)

    async def publish(self, frame: dict, *, dedupe_key: str | None = None) -> None:
        """Broadcast a frame. If dedupe_key is given, skip identical consecutive frames."""
        text = json.dumps(frame, separators=(",", ":"))
        if dedupe_key is not None:
            if text == self._last:
                return
            self._last = text
        async with self._lock:
            dead = []
            for ws in self._clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)

    async def announce(self, source: str, event: str, **fields) -> None:
        """An agent saying what it just did, to whoever is listening."""
        await self.publish({"t": "bus", "from": source, "event": event, **fields})
