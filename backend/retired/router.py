"""retired: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import _RETIRED_PAGES

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.responses import FileResponse, RedirectResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter


router = APIRouter()


@router.get("/tuner.html", include_in_schema=False)
@router.get("/tuner-watch.html", include_in_schema=False)
async def retired_streamer_pages(request: Request) -> RedirectResponse:
    """Send a retired page name to the one that replaced it."""
    return RedirectResponse(_RETIRED_PAGES[request.url.path], status_code=302)
