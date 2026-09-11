"""coders: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import ROOT

from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.responses import FileResponse, RedirectResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/coders", include_in_schema=False)
async def coders_page(request: Request) -> FileResponse:
    """The multi-coder page. LOCAL ONLY, like the surface it drives.

    `ctx._require_local` guards the page as well as the API beneath it. Serving the page
    publicly while the endpoints 404 would advertise an operator surface to the internet and
    hand a visitor a form that cannot work -- and `ops/Caddyfile` has no matcher for
    `/coders`, so it falls to `file_server`, which would find `site/coders.html` on disk and
    serve it happily. Hence the explicit route and the explicit refusal.
    """
    ctx._require_local(request)
    # The same switch the router beneath this page enforces, checked here too. Serving the
    # page while every endpoint it calls answers 404 would hand the operator a form that
    # cannot work and read as a broken surface rather than a switched-off one.
    from coders import enabled as _coders_enabled  # noqa: PLC0415
    if not _coders_enabled():
        raise HTTPException(status_code=404)
    f = ROOT / "backend" / "apps" / "coders" / "page.html"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="coders.html has not been generated")
    return FileResponse(f, media_type="text/html")
