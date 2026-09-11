"""image: routes that were declared on `app` in server.py.

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


@router.post("/api/image", response_model=ctx.ImageResult, tags=["surfaces"])
async def image(body: ctx.ImageRequest,
                _: Annotated[None, Depends(ctx.throttled_for("image"))]) -> ctx.ImageResult:
    """Render an image with ctx.FLUX.1-schnell.

    Taking the card means evicting chat first -- both weight sets do not fit -- so the
    first render after a chat may include a cold load. `seconds` is the render alone.
    """
    if ctx.denied(body.prompt):
        ctx.log.warning("ctx.denied image prompt: %r", body.prompt[:200])
        raise HTTPException(400, "That one specific combination is refused. Nothing else is.")
    if any(not p.exists() for p in ctx.FLUX.values()) or not ctx.DIFFUSE_ENGINE.exists():
        raise HTTPException(503, "Image surface is still warming up.")

    # secrets, not the clock. int(time.time()) % 100000 gave every render in the same
    # wall-clock second an identical "random" seed -- two visitors prompting at once got
    # correlated images -- and wrapped every ~27 hours.
    seed = body.seed if body.seed is not None else secrets.randbelow(2**31 - 1)
    stamp = f"gen-{int(time.time() * 1000)}-{seed}.png"
    out = ctx.RENDERS / stamp
    argv = [str(ctx.DIFFUSE_ENGINE),
            "--diffusion-model", str(ctx.FLUX["unet"]), "--vae", str(ctx.FLUX["vae"]),
            "--clip_l", str(ctx.FLUX["clip"]), "--t5xxl", str(ctx.FLUX["t5"]),
            "-p", body.prompt, "--cfg-scale", "1.0", "--sampling-method", "euler",
            "--steps", str(body.steps), "-W", str(body.size), "-H", str(body.size),
            "--seed", str(seed), "-o", str(out),
            # Without these a 768x768 render dies in VAE decode: it wants a 3.7 GB compute
            # buffer, and with the 5.2 GB T5 encoder also resident there is nothing left.
            # te=cpu moves the text encoder to system RAM (it runs once per prompt, so the
            # PCIe cost is paid once rather than per step), and vae-tiling decodes in tiles
            # instead of allocating the whole buffer at once.
            "--backend", "te=cpu", "--vae-tiling", "--diffusion-fa"]

    async with ctx.gpu.hold("image"):
        await ctx.stop_llama()
        started = time.time()
        # Run sd-cli directly. ctx.gpu.hold already owns the governor lock, and wrapping this
        # in `governor with image` made the process wait on a lock it was already holding --
        # a self-deadlock that only surfaced as the job timeout 120 s later.
        # is_engine: this IS the diffusion engine, so the governor should evict it by
        # identity. `ctx.run` sets start_new_session=True, so this child leads its own
        # group and a verified pgid is recorded -- children go with it.
        rc, _o, err = await ctx.run(*argv, is_engine=True)
        elapsed = time.time() - started

    if rc != 0 or not out.exists():
        ctx.log.error("image failed: %s", err.decode("utf-8", "replace")[-800:])
        raise HTTPException(500, "The render failed.")

    # Renders land in the served directory, so without this they grow without bound -- a
    # public endpoint producing ~800 KB per request fills a disk quietly and takes the whole
    # site down with it, which is a far worse outcome than an old image disappearing.
    await asyncio.to_thread(ctx.prune_gallery)

    return ctx.ImageResult(url=f"/api/gen/{stamp}", seconds=round(elapsed, 2), seed=seed,
                       steps=body.steps, size=body.size,
                       model="SymonImage F1 q4_k", bytes=out.stat().st_size)
@router.get("/api/gen/{name}", tags=["surfaces"],
         responses={200: {"content": {"image/png": {}}}, 404: {"description": "Gone or never existed"}})
async def gen(name: str) -> FileResponse:
    """Serve a render produced by `POST /api/image`.

    Renders used to be handed back as `/<file>`, a path in the deployed webroot. But the
    API writes them into the staging directory, and the web server serves the webroot -- so every
    image generated on the live site 404'd until somebody ran a deploy, which needs a
    password no process here has. Serving them from `/api` instead means they are visible
    the instant they exist, on the same proxied path as every other surface.

    Renders are pruned to the newest 60, so an old url legitimately becomes a 404.
    """
    # `name` is attacker-controlled and lands in a filesystem path. Match the exact shape
    # the generator emits rather than trying to sanitise traversal out of arbitrary input.
    if not re.fullmatch(r"gen-\d{13}-\d{1,10}\.png", name):
        raise HTTPException(404, "No such render.")
    path = ctx.RENDERS / name
    if not path.is_file():
        raise HTTPException(404, "That render has been pruned.")
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})
