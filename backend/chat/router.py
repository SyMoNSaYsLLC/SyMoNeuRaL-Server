"""chat: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import check_rate, throttled_for
from core.config import CHAT_MODEL, DISCONNECT_POLL_S, LIMITS, MAX_PROMPT_CHARS, QUEUE_DEPTH, SYSTEM_PROMPT

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


@router.websocket("/api/ws")
async def websocket(ws: WebSocket) -> None:
    """The three-way channel. See the protocol table in the API description above.

    Handshake: connect, receive `welcome`, then `rack` frames arrive whenever the machine
    changes. Send `{"t":"chat","prompt":"..."}` to generate over the same socket -- deltas
    come back as `{"t":"delta"}` and finish with `{"t":"done"}` carrying the measured rate.
    """
    await ws.accept()
    await ctx.bus.join(ws)
    try:
        await ws.send_text(json.dumps({
            "t": "welcome", "proto": 1,
            "caps": ["rack", "chat", "ravencalc", "remix", "ping"],
            "limits": {"prompt_chars": MAX_PROMPT_CHARS, "per_min": RATE_PER_MIN,
                       "per_hour": RATE_PER_HOUR, "queue_depth": QUEUE_DEPTH},
            "note": "One GPU. chat/image/remix take turns; calc never queues.",
        }, separators=(",", ":")))
        # One full snapshot, once. Everything after this is a patch against it -- so the
        # baseline is established here and the wire stays quiet until something moves.
        snapshot = ctx.build_status().model_dump()
        ctx.bus.seed(ws, snapshot)
        await ws.send_text(json.dumps({"t": "rack", **snapshot}, separators=(",", ":")))

        key = ctx.client_key_ws(ws)
        while True:
            raw = await ws.receive_text()
            if len(raw) > 8000:
                await ws.send_text(json.dumps({"t": "error", "code": 413,
                                               "error": "Frame too large."}))
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"t": "error", "code": 400,
                                               "error": "Not JSON."}))
                continue

            kind = msg.get("t")
            if kind == "ping":
                await ws.send_text('{"t":"pong"}')
                continue
            if kind == "rack":
                await ws.send_text(json.dumps({"t": "rack", **ctx.build_status().model_dump()},
                                              separators=(",", ":")))
                continue

            # The other half of the power switch. `rack_power_gate` covers HTTP; this covers
            # the socket, and BOTH are required for the button to be honest -- `console.js`
            # prefers the socket and falls back to polling, so an HTTP-only guard would
            # leave a "taken offline" unit still serving every client that works properly.
            #
            # Above the rate limiter deliberately: a unit that is off should not spend the
            # caller's token bucket to be told so, and `ping` and `rack` are already handled
            # and returned, so the operator can still read the rack while a surface is down.
            off_unit = rackpower.unit_for_frame(kind)
            if off_unit is not None and rackpower.is_disabled(off_unit):
                await ws.send_text(json.dumps({
                    "t": "error", "code": 503,
                    "error": f"{off_unit} has been taken off the rack by an operator. "
                             f"It is not faulty; the rack says when it went down."}))
                continue

            # Everything below spends the GPU or the CPU, so it is rate limited exactly
            # like the REST routes. Holding a socket open is not a way around the caps.
            if not await check_rate(kind if kind in LIMITS else "chat", key):
                per_min, per_hour = LIMITS.get(kind, LIMITS["chat"])
                await ws.send_text(json.dumps({
                    "t": "error", "code": 429,
                    "error": f"Easy -- {kind} is capped at {per_min}/min, "
                             f"{per_hour}/hour per address."}))
                continue

            if kind == "chat":
                await ctx.ws_chat(ws, msg)
            elif kind == "ravencalc":
                await ctx.ws_calc(ws, msg)
            elif kind == "remix":
                await ctx.ws_remix(ws, msg)
            else:
                await ws.send_text(json.dumps({
                    "t": "error", "code": 400, "error": f"Unknown frame type {kind!r}."}))
    except WebSocketDisconnect:
        pass
    except Exception:
        ctx.log.exception("websocket failed")
    finally:
        await ctx.bus.leave(ws)
@router.post("/api/chat", tags=["surfaces"])
async def chat(body: ctx.ChatRequest, request: Request,
                _: Annotated[None, Depends(throttled_for("chat"))]) -> StreamingResponse:
    """Ask the local model. Streams Server-Sent Events as the card produces tokens.

    Each event is `{"delta": "..."}`; the last is
    `{"done": true, "tokens": N, "seconds": S, "tok_per_s": R, "model": "...", "adapter": bool}`.
    The rate in that final event is measured, not claimed.
    """
    # Kick RavenCalc off first, then take the card. The calculator runs on the CPU and
    # deliberately never takes the lock, so it does its work inside the time the GPU
    # surface spends loading -- by the time the model can speak, the exact answer is
    # already sitting here waiting for it.
    thinking = asyncio.create_task(ctx.anticipate(body.prompt))

    # Take the lease HERE, in the handler, not inside the generator. R-173: a contended
    # card used to reach the visitor as a bodyless 500, because Starlette sends 200 OK the
    # moment a StreamingResponse is returned and the HTTPException was not raised until the
    # generator first ran -- after the status line had gone out, where it can only abort the
    # connection. Acquiring before the response exists means a full queue is an ordinary
    # 503 with a readable body.
    lease = ctx.gpu.hold("chat")
    try:
        await lease.__aenter__()
    except BaseException:
        # RavenCalc was started before the acquire on purpose (above), so an acquire that
        # raises leaves a task nobody will ever await. Left alone it logs "Task exception
        # was never retrieved" out of the event loop at collection time -- a stack trace
        # with no request attached to it, arriving whenever the GC happens to run.
        thinking.cancel()
        raise

    # Returning the card is the handler's job as well as the generator's, because a client
    # that hangs up is not an event the generator ever sees.
    #
    # Measured 2026-08-21 on starlette 0.46.1 / uvicorn 0.32.0 against a generator that
    # cannot finish on its own -- connect, send the request line, close the socket, wait:
    # the generator keeps being resumed and keeps yielding into a socket nobody is reading,
    # forever. Its `finally` never runs, so the lease is never dropped and the next tenant
    # waits out the full ACQUIRE_TIMEOUT_S. Two shapes were tried and measured NOT to fix
    # it, so do not reach for either again:
    #
    #   * subclassing StreamingResponse and releasing in a `try/finally` around
    #     `__call__` -- on an already-dead client `__call__` is never entered at all;
    #   * arming a watchdog on "has the generator started yet" -- it starts immediately,
    #     disarms the watchdog, and then runs on against nobody.
    #
    # `request.is_disconnected()` is the one signal that reflects the client rather than
    # us, so the watchdog polls that. `drop_lease` is idempotent because both it and the
    # generator's `finally` can reach it, and the generator checks `released` each turn so
    # it stops feeding a socket that has gone away instead of running to max_tokens.
    released = asyncio.Event()

    async def drop_lease():
        if released.is_set():
            return
        released.set()
        await lease.__aexit__(None, None, None)

    async def watchdog():
        try:
            while not released.is_set():
                if await request.is_disconnected():
                    ctx.log.info("chat client disconnected mid-stream; returning the card")
                    thinking.cancel()
                    await drop_lease()
                    return
                await asyncio.sleep(DISCONNECT_POLL_S)
        except asyncio.CancelledError:
            raise

    guard = asyncio.create_task(watchdog())
    # asyncio keeps only a weak reference to a task, and this one outlives the frame that
    # created it, so without a strong reference here it can be collected mid-flight.
    _WATCHDOGS.add(guard)
    guard.add_done_callback(_WATCHDOGS.discard)

    async def stream():
        try:
            if not await ctx.start_llama():
                thinking.cancel()
                yield f"data: {json.dumps({'error': 'Chat surface is not available.'})}\n\n"
                return

            # The caller's own system prompt wins outright when supplied. Previously the
            # persona was unconditional and a client could not replace it, because
            # Turn.role is Literal["user","assistant"] -- that Literal is still there and
            # still does its job (it stops a system turn being smuggled in mid-transcript
            # where it would be invisible), but overriding is now an explicit parameter
            # rather than something to work around.
            # `or not body.system.strip()` added 2026-08-26, and the empty case is the whole
            # point. `if body.system is None` alone treated "" as a deliberate override, so a
            # caller sending `{"system": ""}` got a model with NO identity at all -- measured,
            # it answered "I'm a 13.5B expert, fine-tuned for quality", inventing both the
            # size and the provenance.
            #
            # The failure underneath is upstream and is worth naming rather than hiding: this
            # GGUF's `tokenizer.chat_template` carries a Qwen fallback --
            #     {%- if messages[0]['role'] == 'system' %}{{ messages[0]['content'] }}
            #     {%- else %}{{ 'You are Qwen, created by Alibaba Cloud...' }}{%- endif %}
            # -- so an ABSENT system message makes the model introduce itself as Qwen. That
            # is truthful upstream provenance for the weights and it stays in the file; what
            # must never happen is the PRODUCT presenting it to a user as its own identity.
            #
            # Enforcing here rather than editing the GGUF is deliberate and is the narrowest
            # correct layer: it leaves upstream metadata untouched and honest, and it fixes
            # every caller of this route at once. A blank string is now treated as "no
            # override supplied" rather than as "erase the identity".
            system = SYSTEM_PROMPT if (body.system is None or not body.system.strip()) \
                else body.system
            try:
                exact = await asyncio.wait_for(thinking, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                exact = None
            if exact:
                system += ctx.exact_context(exact)
                yield "data: " + json.dumps({
                    "assist": {
                        "from": "ravencalc",
                        "operation": exact.get("_operation"),
                        "input": exact["input"].get("text"),
                        "result": exact["result"].get("text"),
                        "check": exact.get("check"),
                        "ms": exact.get("_anticipated_ms"),
                    }}) + "\n\n"

            messages = ([{"role": "system", "content": system}]
                        + [t.model_dump() for t in body.history]
                        + [{"role": "user", "content": body.prompt}])
            started, tokens, out = time.time(), 0, []
            async for piece in ctx.chat_deltas(messages, body.max_tokens, body.temperature):
                if released.is_set():
                    # The watchdog gave the card back: the visitor is gone. Stop here
                    # rather than generating the rest of max_tokens into a dead socket.
                    return
                tokens += 1
                out.append(piece)
                yield f"data: {json.dumps({'delta': piece})}\n\n"
            elapsed = time.time() - started
            yield "data: " + json.dumps({
                "done": True, "tokens": tokens, "seconds": round(elapsed, 2),
                "tok_per_s": round(tokens / elapsed, 1) if elapsed else None,
                "model": CHAT_MODEL.stem, "adapter": ctx.adapter_applies(),
            }) + "\n\n"
        finally:
            # Every exit from the generator returns the card: a clean finish, a client that
            # hangs up mid-stream, and an exception on the way through. `drop_lease` is
            # idempotent because the watchdog above can also have reached it.
            guard.cancel()
            await drop_lease()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
