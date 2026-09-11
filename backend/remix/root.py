"""remix: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import throttled_for

import json
import re
import time
from typing import Annotated, Literal
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

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
