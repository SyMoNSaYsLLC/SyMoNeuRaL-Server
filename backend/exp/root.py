"""exp: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import SITE

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter


router = APIRouter()


@router.get("/exp", include_in_schema=False)
async def exp_page() -> FileResponse:
    """The plugin runtime's page, at a clean address.

    Its own route rather than a `SECTION_PAGES` entry, for the same reason `/studio` has one:
    `_section_route`'s 404 hardcodes *"run python3 tools/build/build_split.py"*, which would send the
    next person to the wrong generator. Same read-at-request-time behaviour, right instruction.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = SITE / "exp.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="exp.html has not been generated; "
                                   "run python3 tools/build/build_exp.py")
    return FileResponse(f, media_type="text/html")
