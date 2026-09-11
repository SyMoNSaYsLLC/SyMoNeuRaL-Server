"""dispatchos: routes that were declared on `app` in server.py.

Paths here are absolute, so this router is mounted WITHOUT a prefix.
Globals come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the

from fastapi import APIRouter


router = APIRouter()


@router.get("/demo/dispatchos/docs", include_in_schema=False)
async def dispatchos_docs() -> HTMLResponse:
    """DispatchOS documentation for the CUSTOMER surface, at the customer's own address.

    Two things make this its own route rather than a link to `/docs/dispatchos`.

    **The audience.** This page renders with `audience="customer"`, which drops every
    operator-only path -- quote, advance, message, rules and drivers. A customer account is
    refused all five, and listing them here would present actions Donnie will be told `403`
    for as things he is supposed to do. The operator's full view is still at
    `/docs/dispatchos`; nothing is hidden from the person entitled to it.

    **The address.** `ops/Caddyfile` puts `/demo/dispatchos` and `/demo/dispatchos/*` behind
    the door, so this page is reachable exactly where the application is and by exactly the
    same people. A customer handed one URL does not have to learn a second one, and the docs
    for a surface behind a door do not sit outside it.

    Declared above the StaticFiles mount, for the same reason every route here is.
    """
    app_def = appdocs.BY_ID["dispatchos"]
    return HTMLResponse(appdocs.render(
        app_def,
        appdocs.visible_routes("dispatchos", app.routes, audience="customer"),
        audience="customer", docs_root="/docs"))
