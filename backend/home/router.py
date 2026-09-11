"""home: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from fastapi.responses import FileResponse, RedirectResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter


router = APIRouter()


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Send the bare domain to /overview.

    302, deliberately NOT 301. A permanent redirect is cached by browsers indefinitely and
    is painful to walk back -- anyone who visited once would keep being bounced even after
    the rule was removed. This is a presentation choice that may well be revisited, so it
    stays reversible.

    `site/index.html` is still built and still served at /index.html. It is the assembled
    page tools/build/build_split.py reads to produce the four section pages, so it cannot simply
    stop being generated.
    """
    return RedirectResponse("/overview", status_code=302)
