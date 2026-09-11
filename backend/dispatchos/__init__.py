"""DispatchOS -- the dispatch application behind the customer preview.

Task #106. Garrett, 2026-08-26: *"donnie has requested to 'have one built' so we were
creating him a custom extension to the site with webui for /backend/dispatchos"*.

Four exports, and they are the whole contract with `backend/server.py`:

    import dispatchos
    app.include_router(dispatchos.router, prefix="/api/dispatchos", tags=["dispatchos"])
    app.include_router(dispatchos.ui_router, include_in_schema=False)   # /demo/dispatchos
    dispatchos.set_ask_model(guide_ask_model)      # optional; SyMon AI degrades without it
    Unit(**dispatchos.status())                    # the rack unit

## It owns no weights, and never takes the card

Everything this surface does is a read or a write to a small SQLite store: request a trip,
quote it, dispatch it, compose a reminder, record what happened. None of that is inference.
The one place a model is involved -- SyMon AI answering a question about the board -- goes
through an injected `str -> str` callable into the chat surface and **never starts it**. If
chat is not already resident the assistant degrades and says so.

That is RavenCalc's property adopted deliberately: the moment an operator most wants to look
at the board is the moment the card may be busy for hours, and a dispatch surface that
queued behind a fine-tune would be useless.

## Off by default

`SYMONEURAL_DISPATCHOS_ENABLED=1` or the API answers 503. One switch rather than the
switch-plus-token pattern `apps/project` and `apps/coder` use, because those surfaces have
no login of their own and their token is their authentication; this one has real accounts
with scrypt password hashes, and a shared bearer token beside them would be a second and
weaker credential for the same data.

The page at `/demo/dispatchos` additionally sits behind basicauth in `ops/Caddyfile`, which
is the outer door and is not the roles. See `routes.py`.
"""
from __future__ import annotations

from .lib import ai
from .apps import page
from .apps import quotes
from .lib import store
from .lib.ai import ModelUnusable, set_ask_model
from .router import router, ui_router
from .lib.store import DispatchError, enabled, init_db

__all__ = [
    "router", "ui_router", "set_ask_model", "status", "init_db", "enabled",
    "DispatchError", "ModelUnusable", "ai", "page", "quotes", "store",
]


def status() -> dict:
    """The rack unit for this surface. Keys match `api.py`'s `Unit` model.

    `bus="cpu"` because it is one: no GPU work happens here, and badging it `gpu` would put
    a unit on the rack that never moves the VRAM gauge.

    The state is READ, not asserted. `offline` when the switch is off, `ready` when it is
    on -- which is the same thing the miner, coder, gateway and studio rows do, and is the
    behaviour #95 exists to decide for the one row that does not. A row that reads `ready`
    with the surface switched off would be exactly the defect that task is about.
    """
    on = enabled()
    if not on:
        return {
            "id": "dispatchos", "label": "SyMoNeuRaL DispatchOS", "bus": "cpu", "slot": "1U",
            "state": "offline", "spec": "dispatch",
            "detail": "SYMONEURAL_DISPATCHOS_ENABLED is not set",
            "href": "/demo/dispatchos",
        }
    try:
        c = store.counts()
        live = c.get("confirmed", 0) + c.get("dispatched", 0)
        detail = f"{sum(c.values())} bookings, {live} live"
    except Exception:                              # noqa: BLE001
        # A store that cannot be read is a real state and says so, rather than reporting
        # `ready` on a surface whose database is missing.
        return {
            "id": "dispatchos", "label": "SyMoNeuRaL DispatchOS", "bus": "cpu", "slot": "1U",
            "state": "offline", "spec": "dispatch", "detail": "the store is unreadable",
            "href": "/demo/dispatchos",
        }
    return {
        "id": "dispatchos", "label": "SyMoNeuRaL DispatchOS", "bus": "cpu", "slot": "1U",
        "state": "ready", "spec": "dispatch", "detail": detail,
        "href": "/demo/dispatchos",
    }
