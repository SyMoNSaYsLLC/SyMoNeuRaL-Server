"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import _try
from core.config import ACQUIRE_TIMEOUT_S, GOVERNOR

import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

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
