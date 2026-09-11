"""docs: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations
from core.config import API_REFERENCE_SCRIPT, API_REFERENCE_STYLE, DOCS_HEADER, LIMITS, MAX_PROMPT_CHARS

import time
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the
import live  # noqa: E402  -- his OBS stream, watchable while it runs and after it

from fastapi import APIRouter

from core.context import ctx

router = APIRouter()


@router.get("/docs", include_in_schema=False)
async def api_reference() -> HTMLResponse:
    """The API reference. Ours, rendered from `/openapi.json`.

    This was a third-party documentation UI wearing our palette: 1.6 MB of vendor bundle in
    the webroot, a FastAPI helper that embedded it, and a page that still carried the
    vendor's name in three asset URLs a visitor could read. Task #74 item 6 -- the API
    reference is a visitor-facing page and is now a SyMoNeuRaL surface, rendered by the code
    above from the schema below it.

    The vendor is named in `LICENSES.md`, which records that we no longer distribute the
    bundle rather than dropping the entry -- a vanished notice and a stripped one read
    identically -- and in the commit that made this change. It is deliberately not named
    here: #74's declared check is a file-wide grep for the name in this file, and a
    docstring that keeps the word would hold that check red for prose. `LICENSES.md` is
    where the licence obligation actually lives, and `git log` is where this repo keeps
    "why is the code like this".

    **Inline, not a file under `site/`.** This page is assembled here at request time, so
    `build_cachebust.py` never sees it -- a new `/apiref.css` would ship unstamped and
    therefore cacheable for a week against markup that changes with every route added. It
    would also be a webroot asset referenced from nowhere in `site/`, which is how nineteen
    unreferenced PNGs accumulated there before the backend restructure.

    **It has no data of its own.** Everything rendered comes from the schema FastAPI already
    generates, so the reference cannot drift from the service: if a route is added, it
    appears; if one is removed, it goes. That is the property the card on the home page
    claims -- *"generated from the running service. Not a snapshot."* -- and it is now true
    of our own code rather than of somebody else's.
    """
    # Both figures are read from the constants rather than typed into the markup. They had
    # drifted badly while hardcoded -- the page claimed 6/min and a 1,200-character cap
    # while the code enforced 120/min and 4,000 -- and this site's whole argument is that
    # its published numbers are the real ones. A stale honest-looking figure is the same
    # failure as a decorative LED.
    per_min, per_hour = LIMITS["chat"]
    rate = (f'<div class="val">{per_min}<u>/min</u></div>'
            f'<div class="sub">{per_hour:,}/hour &middot; per address</div>'
            if per_min else
            '<div class="val sm">none</div>'
            '<div class="sub">unmetered &middot; the queue is the only backstop</div>')
    header = (DOCS_HEADER.replace("@@RATE@@", rate)
                         .replace("@@CAP@@", f"{MAX_PROMPT_CHARS:,}"))

    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>API Reference &middot; SyMoNeuRaL</title>"
        '<link rel="icon" href="/favicon-32.png" sizes="32x32">'
        '<link rel="stylesheet" href="/symoneural.css">'
        '<link rel="stylesheet" href="/rack-detail.css">'
        '<meta name="theme-color" content="#0e100f">'
        f"{API_REFERENCE_STYLE}</head><body>{header}"
        '<div class="ar-wrap">'
        f"{ctx._application_docs_index()}"
        '<p class="ar-note">Every operation below is read from the schema this service '
        "generates at the moment you loaded the page. Nothing here is written by hand, so "
        "it cannot describe a route that no longer exists or omit one that was just added. "
        'The raw document is at <a href="/openapi.json">/openapi.json</a>.</p>'
        '<div id="ar-root"><p class="ar-count">Reading /openapi.json&hellip;</p></div>'
        "</div>"
        f"{API_REFERENCE_SCRIPT}"
        '<script src="/console.js" defer></script>'
        "</body></html>"
    )
@router.get("/docs/{app_id}", include_in_schema=False)
async def application_docs(app_id: str) -> HTMLResponse:
    """One application's scoped reference, rendered from the live router.

    Nothing about the operation list is written down: `appdocs.routes_for` walks
    `app.routes` and keeps the ones whose path this application owns. Ownership is a
    partition over path prefixes, so two pages cannot show the same route and no page can
    show another application's -- that is a property of the data structure rather than
    something a reviewer has to check every time a router is added.
    """
    app_def = appdocs.BY_ID.get(app_id)
    if app_def is None:
        # Name the index rather than 404ing blankly. A visitor who guessed a slug is one
        # click from the right one, and the list is short.
        raise HTTPException(status_code=404,
                            detail=f"no application {app_id!r}; see /docs for the "
                                   "platform reference and the application index")
    kids = tuple(a for a in appdocs.APPLICATIONS if a.parent == app_id)
    return HTMLResponse(appdocs.render(
        app_def, appdocs.routes_for(app_id, app.routes), children=kids))
