"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import throttled_for
from core.config import MAX_PROMPT_CHARS, _HAS_MATH, _OPERATION_WORDS, _VARIABLE

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


class CalcRequest(BaseModel):
    """A symbolic computation. Exact in, exact out -- no floats that lost the argument."""
    expression: str = Field(..., max_length=MAX_PROMPT_CHARS, examples=["x**2*sin(x)"])
    operation: Literal["differentiate", "integrate", "limit", "series",
                       "solve", "simplify", "evaluate"] = "simplify"
    variable: str | None = Field("x", max_length=64)
    point: str | None = Field(None, max_length=64,
                              description="Only meaningful for `limit`.")
def extract_math(prompt: str) -> tuple[str, str, str] | None:
    """Find (operation, expression, variable) in a natural-language question.

    Returns None far more often than not, and that is the correct behaviour -- a false
    positive here means an irrelevant "verified result" is handed to the model and it
    dutifully works it into an answer about something else. The parser is the gate: a
    candidate only survives if RavenCalc's own strict whitelist parser accepts it, so
    prose, code and pasted logs fall out on their own.
    """
    try:
        from ravencalc.apps import ravencalc
    except ImportError:
        return None

    operation = next((op for pattern, op in _OPERATION_WORDS if pattern.search(prompt)), None)
    if operation is None:
        return None

    variable = "x"
    if match := _VARIABLE.search(prompt):
        variable = match.group(1)

    # Fenced text wins outright -- if someone put it in backticks they meant it literally.
    for fenced in re.findall(r"`([^`]{2,120})`", prompt):
        if ctx._parses(ravencalc, fenced):
            return operation, fenced.strip(), variable

    # Otherwise search word spans, longest first, and let the parser decide. Trying to
    # strip English with a regex does not survive contact with real phrasing: "integrate
    # x**2 with respect to x" has prose on both sides, and one pass of prefix-removal
    # leaves the tail behind. Testing spans costs nothing on a sentence and is simply
    # correct -- the strict whitelist parser is a far better judge of "is this an
    # expression" than any pattern of mine.
    # Drop the operation words before searching. SymPy's namespace contains functions with
    # exactly these names, so "simplify (x**2-1)/(x-1)" parses happily as a call to
    # simplify() -- and "integrate (x)" would parse as an integral that we then integrate a
    # second time. The verb belongs to the request, not to the expression.
    cleaned = re.sub(r"\b(integrate|integral|antiderivative|differentiate|derivative|"
                     r"diff|limit|solve|simplify|expand|factor|series|taylor|evaluate|"
                     r"compute|calculate)\b", " ", prompt, flags=re.I)
    words = re.sub(r"[?]", " ", cleaned).split()
    n = len(words)
    for length in range(min(n, 14), 0, -1):
        for start in range(0, n - length + 1):
            candidate = " ".join(words[start:start + length]).strip(" .,?:;")
            if len(candidate) < 3 or not _HAS_MATH.search(candidate):
                continue
            if not any(ch.isalnum() for ch in candidate):
                continue
            if ctx._parses(ravencalc, candidate):
                return operation, candidate, variable
    return None
async def ws_calc(ws: WebSocket, msg: dict) -> None:
    try:
        body = CalcRequest(**{k: v for k, v in msg.items() if k != "t"})
    except Exception as exc:
        await ws.send_text(json.dumps({"t": "error", "code": 422, "error": str(exc)[:300]}))
        return
    try:
        from ravencalc.apps import ravencalc
    except ImportError:
        await ws.send_text(json.dumps({"t": "error", "code": 503,
                                       "error": "RavenCalc is unavailable."}))
        return
    doc = {"schema": "ravencalc/request/v1", "operation": body.operation,
           "expression": body.expression}
    if body.variable:
        doc["variable"] = body.variable
    if body.point:
        doc["point"] = body.point
    started = time.time()
    try:
        result = await asyncio.to_thread(ravencalc.run_request, doc)
    except ravencalc.RavenCalcError as exc:
        await ws.send_text(json.dumps({"t": "error", "code": 400, "error": exc.message}))
        return
    result["seconds"] = round(time.time() - started, 4)
    await ws.send_text(json.dumps({"t": "calc.result", **json.loads(json.dumps(result, default=str))},
                                  separators=(",", ":")))
async def calc(body: CalcRequest,
                _: Annotated[None, Depends(throttled_for("ravencalc"))]) -> dict:
    """Exact symbolic mathematics. No GPU, no lock, no queue.

    Returns a `ravencalc/result/v1` document. Note `check`: where verification is cheap the
    engine does it -- an antiderivative is differentiated back and simplified against zero --
    and `check.passed` is three-valued. `null` means the check could not confirm the result,
    which is reported rather than rounded up to success.
    """
    try:
        from ravencalc.apps import ravencalc
    except ImportError:
        raise HTTPException(503, "RavenCalc is unavailable.")

    doc = {"schema": "ravencalc/request/v1", "operation": body.operation,
           "expression": body.expression}
    if body.variable:
        doc["variable"] = body.variable
    if body.point:
        doc["point"] = body.point

    started = time.time()
    try:
        result = await asyncio.to_thread(ravencalc.run_request, doc)
    except ravencalc.RavenCalcError as exc:
        raise HTTPException(400, exc.message)
    result["seconds"] = round(time.time() - started, 4)
    return json.loads(json.dumps(result, default=str))
