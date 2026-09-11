"""studio: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.ratelimit import throttled_for
from core.config import SITE, STUDIO_REGISTRY_FILE

import json
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/api/studio/models", tags=["studio"],
         summary="Models on this machine, read from a pre-computed file",
         dependencies=[Depends(throttled_for("studio"))])
async def studio_models() -> dict:
    """The model list, as last written by `tools/build/build_registry.py`.

    **`latency_ms` is null on every row, and that is the honest answer today.** Nothing on this
    machine stores a per-model latency: the token rate on the site is a literal in
    `tools/build/build_console.py`, and the only measurement persisted to disk is peak VRAM. The field
    is present so the response shape does not change when a real reading appears; a number will
    only ever be written by something that measured it, for the row it measured.

    An empty `models` with `generated_at: null` means the file has not been written yet -- a
    200 rather than a 404, because this is a list a client polls and an empty list keeps its
    decode path intact. `detail` then names the generator to run, which is the useful half of
    the 404 the section routes raise.

    **Public and unauthenticated, deliberately.** Caddy delegates the whole `/api/*` subtree,
    so this answers anyone. That is a decision, not an oversight: every row states a model name
    the site already publishes, a size, a quantisation and a parameter count -- the numbers, and
    the site's argument is that the numbers are real and checkable. What it does *not* state is
    where any of it lives on disk; `path` is dropped at the validator above. Metered under the
    `studio` bucket so a ceiling can be set without touching this file.
    """
    try:
        doc = json.loads(STUDIO_REGISTRY_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        doc = None
    if not isinstance(doc, dict):
        return {
            "models": [], "generated_at": None, "schema": None,
            "detail": ("run/registry.json has not been generated; "
                       "run python3 tools/build/build_registry.py"),
        }
    generated = doc.get("generated_at")
    schema = doc.get("schema")
    return {
        "models": ctx._studio_rows(doc.get("models")),
        "generated_at": generated if isinstance(generated, int) and not isinstance(generated, bool) else None,
        "schema": schema if isinstance(schema, int) and not isinstance(schema, bool) else None,
        "latency_note": ("null latency means unmeasured, not zero. See the route docstring: no "
                         "per-model timing is recorded on this machine yet."),
        "freshness_note": ("this file is written out-of-band and is not refreshed by this "
                           "request; re-run tools/build/build_registry.py after changing what is on "
                           "disk"),
    }
@router.get("/studio", include_in_schema=False)
async def studio_page() -> FileResponse:
    """The Studio, at a clean address.

    Its own route rather than a `SECTION_PAGES` entry, because `_section_route`'s 404 hardcodes
    *"run python3 tools/build/build_split.py"*. That is true of the four section pages and false of
    this one, and a 404 that names the wrong generator sends the next person to the wrong file.
    Same read-at-request-time behaviour, different instruction.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = SITE / "studio.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="studio.html has not been generated; "
                                   "run python3 tools/build/build_studio.py")
    return FileResponse(f, media_type="text/html")
