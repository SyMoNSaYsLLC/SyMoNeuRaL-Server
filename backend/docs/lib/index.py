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


def _application_docs_index() -> str:
    """The index of scoped application documentation, grouped by functional runtime.

    This sits at the TOP of `/docs` rather than at the bottom, and grouped by runtime rather
    than listed flat, because the two questions a visitor arrives with are "which application
    am I looking for" and "what actually runs it" -- and a flat alphabetical list of
    twenty-two slugs answers neither. The grouping is read from the registry, so a new
    application appears here the moment it is given an owner and never has to be added twice.

    Global versus scoped is stated rather than implied: this page is the platform-wide
    reference and every link below narrows it to one application's own routes.
    """
    by_runtime: dict[str, list] = {}
    for a in appdocs.APPLICATIONS:
        by_runtime.setdefault(a.runtime, []).append(a)

    blocks = []
    for runtime in appdocs.RUNTIMES:
        apps_here = [a for a in by_runtime.get(runtime, []) if a.parent is None]
        children = {a.parent: [] for a in by_runtime.get(runtime, []) if a.parent}
        for a in by_runtime.get(runtime, []):
            if a.parent:
                children.setdefault(a.parent, []).append(a)
        if not apps_here and not children:
            continue
        rows = []
        for a in apps_here:
            kids = children.get(a.id, [])
            kid_links = "".join(
                f'<a class="ar-appkid" href="/docs/{k.id}">{appdocs.e(k.label)}</a>'
                for k in kids)
            rows.append(
                f'<div class="ar-app"><a class="ar-applink" href="/docs/{a.id}">'
                f'<b>{appdocs.e(a.label)}</b></a>'
                + (f'<div class="ar-appkids">{kid_links}</div>' if kid_links else "")
                + "</div>")
        # A child whose parent runs on a DIFFERENT runtime still needs a home here, or it
        # would be silently absent from the index while having a perfectly good page.
        for parent_id, kids in children.items():
            if any(a.id == parent_id for a in apps_here):
                continue
            for k in kids:
                rows.append(f'<div class="ar-app"><a class="ar-applink" href="/docs/{k.id}">'
                            f'<b>{appdocs.e(k.label)}</b></a></div>')
        blocks.append(
            f'<div class="ar-rt"><h3>{appdocs.e(runtime)}</h3>'
            f'<p>{appdocs.e(appdocs.RUNTIMES[runtime])}</p>'
            f'<div class="ar-apps">{"".join(rows)}</div></div>')

    return (
        '<div class="ar-index">'
        '<h2>Documentation by application</h2>'
        '<p class="ar-note">This page is the <strong>platform-wide</strong> reference: every '
        'route this service mounts, from the schema it generates. Each link below is a '
        '<strong>scoped</strong> page carrying only that application&rsquo;s own routes, its '
        'runtime owner, its authentication boundary and its operational limits. Applications '
        'are grouped by the runtime that executes their work; indented entries are child '
        'surfaces of the application above them, not runtimes of their own.</p>'
        f'<div class="ar-runtimes">{"".join(blocks)}</div>'
        '</div>'
    )
