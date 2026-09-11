"""live: routes that were declared on `app` in server.py.

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
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it

from fastapi import APIRouter


router = APIRouter()


@router.get("/live-stack/live", include_in_schema=False)
@router.get("/livestack/live", include_in_schema=False)
async def live_page() -> FileResponse:
    """SyMoNeuRaL Live, at the address he asked every app to be at.

    BOTH spellings, added 2026-08-22 with #81's image work. This page was born at
    `/livestack/live` alone, before `/live-stack/coder` established that the hyphenated
    form is served too -- so it was the one application on the rack reachable at one
    spelling, which #81's own title says it should not be: *"/livestack/<name> **and**
    /live-stack/<name> for every application"*. Found by the twin-spelling assertion in
    `apps/test_deploy_routes.py`, not by anyone typing the address.

    *"Applications from the live stack url as https://symoneural.com/chat.html for example.
    They all need to be as such https://symoneural.com/livestack/chat"* — so this one is born
    at `/livestack/live` rather than being migrated there later by #81.

    `/live.html` keeps working, and not by accident: `site/` is mounted at `/` below, so the
    file answers at its own name for anything that already links to it. Two addresses for one
    file is the migration path #81 has to walk for the other nine, and the reason it is cheap
    is that this route does not redirect — a redirect would break a `<video>` mid-playlist,
    since the player resolves segment URIs relative to the manifest it was handed.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = SITE / "live.html"
    if not f.is_file():
        # Deliberately NOT "run tools/build_<x>.py". There is no generator for this page and
        # there is not meant to be: *"Make sure to update the applications to be static with
        # js css and html"*, so `site/live.html` is hand-authored and tracked. If it is
        # missing, it was deleted or the checkout is partial, and sending the next person to
        # a generator that does not exist is the exact failure `/studio`'s docstring above
        # exists to avoid.
        raise HTTPException(status_code=404,
                            detail="site/live.html is missing. It is a tracked, "
                                   "hand-authored static page with no generator; "
                                   "restore it with git checkout -- site/live.html")
    return FileResponse(f, media_type="text/html")
@router.get("/live-stack/coder", include_in_schema=False)
@router.get("/livestack/coder", include_in_schema=False)
async def coder_page() -> FileResponse:
    """SyMoNeuRaL Coder: the browser surface.

    Hand-authored and tracked, exactly like `site/live.html`, so the 404 below sends the
    next person to `git checkout` rather than to a generator. There is no
    `tools/build_coder.py` and there is not meant to be -- *"Make sure to update the
    applications to be static with js css and html"*. Naming a generator that does not
    exist is the failure `/studio`'s docstring exists to avoid, arriving one page later.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    f = SITE / "coder.html"
    if not f.is_file():
        raise HTTPException(status_code=404,
                            detail="site/coder.html is missing. It is a tracked, "
                                   "hand-authored static page with no generator; "
                                   "restore it with git checkout -- site/coder.html")
    return FileResponse(f, media_type="text/html")
