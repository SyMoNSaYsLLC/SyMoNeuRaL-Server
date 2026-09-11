"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import LIMITS, MAX_PROMPT_CHARS, PORT, QUEUE_DEPTH

import asyncio
import subprocess
import time
from contextlib import asynccontextmanager
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from hardware.lib import telemetry
import asicminer  # noqa: E402
import gateway    # noqa: E402  -- TRON licensing surface, see backend/gateway/
from registry.lib import ports  # noqa: E402
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
import project  # noqa: E402  -- the shared workspace surface. Brings its
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
from streamer.guide import router as guide_routes  # noqa: E402  -- question ->
import studio  # noqa: E402  -- the local agent and the
import news  # noqa: E402  -- the ticker's collector. Bound to
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it
import dispatchos  # noqa: E402  -- the transport dispatch application for a named

from core.context import ctx


class AsicCache:
    """Last known rig readings, refreshed off the request path.

    `/api/status` is polled and also drives the websocket, so it must never block. Probing
    rigs means spawning a subprocess that waits on network timeouts -- up to 30s if a rig
    has been unplugged, which is exactly when it is slowest and exactly when someone is
    looking. So the endpoint reads whatever was last measured and a background task does the
    waiting.

    `None` means "not yet probed", which `asicminer.unit_state` reports as offline rather
    than inventing an optimistic default. A stale reading is labelled by `age_s` rather than
    being silently presented as current -- the whole rack argues that its numbers are real,
    and "real but N seconds old" is a different claim from "real right now".
    """

    TTL = 20.0

    def __init__(self) -> None:
        self._value: dict | None = None
        self._at: float = 0.0

    def get(self) -> dict | None:
        if self._value is None:
            return None
        return {**self._value, "age_s": round(time.monotonic() - self._at, 1)}

    def stale(self) -> bool:
        return time.monotonic() - self._at >= self.TTL

    def put(self, value: dict) -> None:
        self._value, self._at = value, time.monotonic()
async def asic_refresher() -> None:
    """Keep `ctx._asic_cache` warm while the surface is enabled. Started in the lifespan."""
    while True:
        try:
            if asicminer.enabled() and asicminer.installed():
                ctx._asic_cache.put(await asicminer.probe())
        except asyncio.CancelledError:
            raise
        except Exception:                      # never let this kill the loop
            ctx.log.exception("asic refresh failed")
        await asyncio.sleep(AsicCache.TTL)
async def telemetry_loop() -> None:
    """Keep the live modules actually live.

    ctx.push_rack only fired when a job started or ended, so between jobs the VRAM, power and
    temperature readings sat frozen -- on modules badged `live`, on a page whose argument is
    that its numbers are real. Worse, the HTTP polling fallback was fresher than the
    WebSocket we tell clients to prefer.

    Only runs while somebody is listening, and the delta filter means an idle machine still
    sends nothing: temperature that has not moved produces no frame.
    """
    while True:
        try:
            await asyncio.sleep(3)
            if ctx.bus.listeners:
                await telemetry.refresh_telemetry()
                await ctx.push_rack()
        except asyncio.CancelledError:
            raise
        except Exception:
            ctx.log.exception("telemetry loop hiccup")
@asynccontextmanager
async def lifespan(_: FastAPI):
    ctx.log.info("symoneural api on 127.0.0.1:%d (loopback only)", PORT)
    global _LOOP
    _LOOP = asyncio.get_running_loop()
    guide_routes.ASK_MODEL = ctx.guide_ask_model
    # "0/min, 0/hr" would read as "nothing is allowed" in a ctx.log someone skims at 3am, when
    # it means the exact opposite. Print the state, not the number.
    metered = ", ".join(f"{s} {p}/min {h}/hr" for s, (p, h) in LIMITS.items() if p) or "none"
    ctx.log.info("caps: prompt<=%d chars, queue %d, rate limited: %s",
             MAX_PROMPT_CHARS, QUEUE_DEPTH, metered)
    # DispatchOS creates its tables once at startup rather than on the first request, so an
    # operator opening the page never races two requests both running CREATE TABLE. Guarded
    # by the switch: with the surface off this touches no disk at all, which keeps the
    # default state of this box free of a database nobody asked for.
    if dispatchos.enabled():
        try:
            dispatchos.init_db()
            ctx.log.info("dispatchos surface enabled; store at %s", dispatchos.lib.store.db_path())
        except Exception:
            # A store that will not open is a reason for that surface to answer 503, not a
            # reason for the whole API to fail to start. `status()` reports it as offline.
            ctx.log.exception("dispatchos store could not be initialised; surface stays down")
    ticker = asyncio.create_task(telemetry_loop())
    # Only run when an operator has switched the surface on. With the env unset this task
    # would loop forever doing nothing, so it is not started at all -- and the rack still
    # reports the ASIC unit correctly, because `unit_state` reads the switches directly.
    asic = asyncio.create_task(asic_refresher()) if asicminer.enabled() else None
    if asic:
        ctx.log.info("asic surface enabled; probing %d configured rig(s)", len(asicminer.rigs()))
    # Same reasoning as the ASIC probe, for the same reason: a public TRON node measured
    # 0.4-2.3 s from this box, and /api/status drives the rack websocket for every visitor.
    # A reading that slow cannot sit on the status path, so it is cached off it.
    gw = asyncio.create_task(gateway.refresher()) if gateway.enabled() else None
    # Same pattern again, and the same reason: a pass over thirteen third-party feeds took
    # 13.4-41.2 s measured on 2026-08-20, which cannot sit anywhere near a request. It is
    # cached off the path entirely and `/api/news/ticker` only ever reads the cache. With the
    # switch off no task is started, so the default state of this box makes no outbound
    # request at all. Not called `ticker`: that name is the telemetry loop's, four lines up.
    newsfeed = asyncio.create_task(news.refresher()) if news.enabled() else None
    # Only if something is actually delegated -- on a box where the monolith answers
    # everything this task would poll nothing forever.
    delegates = (asyncio.create_task(ctx.poll_delegated())
                 if ports.delegated_surfaces() else None)
    if newsfeed:
        ctx.log.info("news surface enabled; %d sources, %d search engines, %.0fs interval",
                 len(news.apps.feeds.SOURCES), len(news.apps.feeds.SEARCHES), news.interval_s())
    # The project store is created by `store.connect()`, which every write route goes
    # through -- but the rack poll uses `probe()`, read-only by design, so before this line
    # existed a fresh install reported "no project store initialised" until someone happened
    # to POST. Honest, and also permanently offline for a surface whose only prerequisite is
    # a file. `bootstrap()` is a no-op when the switch is off; it does not create a database
    # for a surface nobody enabled.
    store_path = project.bootstrap()
    if store_path:
        ctx.log.info("project surface enabled; store at %s", store_path)
    # The obs-websocket client. Started here and never from a route: a connection per request
    # would re-run the SHA256 challenge/response on every page load, and obs-websocket rate
    # limits nothing, so that fault is invisible except as latency. `start()` returns as soon
    # as the task is scheduled and never raises -- an absent OBS is the normal state of this
    # box, not an error, and it must not be able to stop the API booting.
    await live.bridge.start()
    yield
    ticker.cancel()
    if asic:
        asic.cancel()
    if gw:
        gw.cancel()
    if newsfeed:
        newsfeed.cancel()
    if delegates:
        delegates.cancel()
    # Without this a reload leaks one ffmpeg per live stream: the sessions outlive the
    # process that spawned them and nothing else knows their pids.
    streamer.lib.sessions.MANAGER.shutdown()
    # Closes the socket and cancels the reconnect loop. Without it a `--reload` cycle leaves
    # the old task backing off against an OBS the new process is also connecting to, which is
    # two clients holding one credential and a reconnect storm nobody can see from a ctx.log.
    await live.bridge.stop()
    await ctx.stop_llama()
