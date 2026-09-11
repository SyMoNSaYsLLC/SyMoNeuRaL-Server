"""HTTP surface for the per-unit power switch. Mounted by `api.py` at `/api/rack`.

Two routes and nothing else: read the panel, flip one unit. There is deliberately no
"disable everything" route -- that already exists and is `scripts/symoneural.sh off`, which
is a shell command on the box rather than an HTTP call, and making the destructive-in-bulk
version reachable over the network would be a strictly worse version of a thing that works.

## 404, not 403, when the surface is off

With `SYMONEURAL_RACK_ENABLED` unset every route here answers **404**, the same answer an
unmounted path gives. That is not security theatre standing in for the token: the token is
the gate, and it is compared in constant time. It is that the public rack is served to
anyone, and a 403 from `/api/rack/power` tells a visitor that this installation has an
operator control worth attacking. A 404 tells them the same thing an absent feature does.

Once the surface IS on, a bad token gets **403** and a non-loopback peer gets **403** with
the reason, because at that point the caller is an operator who mistyped something and
needs to know which of the three gates refused them.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import TOGGLEABLE, authorize, disable, enable, enabled, status_rows

router = APIRouter()


class PowerRequest(BaseModel):
    # `offline: true` takes the unit down, `false` puts it back. One field rather than two
    # routes so the panel's toggle is one call in both directions and cannot get into a
    # state where it knows how to switch a unit off but not on.
    offline: bool


def peer_of(request: Request) -> str | None:
    """The real client address, read the same way `api.py:client_key` reads it.

    THIS IS LOAD-BEARING AND IT IS NOT `request.client.host`. Caddy and the gateway both sit
    in front, so `request.client.host` is `127.0.0.1` for every request that has ever
    arrived from the internet -- using it would make `peer_ok()` return True for the entire
    world and quietly delete the loopback gate.

    Reading the forwarded chain is safe *here specifically* because of two facts that hold
    on this box and are worth stating rather than assuming:

      - `api.py` binds `127.0.0.1:8800` (see `uvicorn.run`), so nothing off-box can reach
        this process without passing through the proxy chain first.
      - Caddy ≥2.7 defaults `trusted_proxies` to none and therefore **replaces** an inbound
        `X-Forwarded-For` with the real peer -- tested, and recorded in `ops/Caddyfile`.

    So a visitor cannot forge `X-Forwarded-For: 127.0.0.1` to pass the loopback gate. If
    either fact changes -- the API binds a public interface, or Caddy is configured to trust
    an upstream -- this gate weakens and `SYMONEURAL_RACK_TOKEN` becomes the only thing left.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    first = fwd.split(",")[0].strip()
    if first:
        return first
    return request.client.host if request.client else None


def _guard(request: Request) -> str:
    """Evaluate all three gates, or raise. Returns the peer, for attribution."""
    if not enabled():
        # See the module docstring: absent, not forbidden.
        raise HTTPException(status_code=404, detail="Not Found")
    peer = peer_of(request)
    # New header name first, then the one it replaced -- `site/console.js:412` is cached
    # JavaScript, so an operator's browser can still be sending the old name after deploy.
    # `request.headers` is case-insensitive, hence the lowercase spellings kept from before.
    ok, why = authorize(request.headers.get("x-symoneural-token")
                        or request.headers.get("x-sym-token"), peer)
    if not ok:
        raise HTTPException(status_code=403, detail=why)
    return peer or "unknown"


@router.get("/power", summary="Which units an operator has taken off the rack")
def read_power(request: Request):
    _guard(request)
    return {"units": status_rows(), "toggleable": list(TOGGLEABLE)}


@router.post("/power/{unit_id}", summary="Take one unit off the rack, or put it back")
async def set_power(unit_id: str, request: Request):
    """The body is parsed by hand, AFTER the gate, and that ordering is the point.

    Measured 2026-09-08 with the switch disabled: `GET /api/rack/power` answered 404 as the
    module docstring promises, and `POST /api/rack/power/{unit_id}` answered **422 naming
    its required field** -- because a declared `body: PowerRequest` parameter makes FastAPI
    validate the body before the handler runs, so `_guard` was never consulted. A visitor
    learned that this installation has an operator control, and learned the shape of its
    payload, which is exactly what the 404-rather-than-403 argument exists to prevent.

    The token gate was never bypassed. What was bypassed was the concealment, by the
    framework, one layer above the code that implements it.

    So `request` is taken raw and the JSON is read after `_guard` returns. The 422 for a
    genuinely malformed body is still produced -- it is raised below, once the caller has
    proved they are an authorised operator on this box and telling them what is wrong with
    their payload is a kindness rather than a disclosure.
    """
    peer = _guard(request)
    try:
        body = PowerRequest(**(await request.json()))
    except Exception as exc:                       # malformed JSON, or the field missing
        raise HTTPException(status_code=422, detail=f"want {{\"offline\": bool}}: {exc}")
    if unit_id not in TOGGLEABLE:
        # 404 rather than 400: an id that is not on the allowlist has no switch, and saying
        # "that unit exists but you may not touch it" would be a distinction this surface
        # does not offer. The allowlist is in the GET response for anyone who needs it.
        raise HTTPException(status_code=404,
                            detail=f"{unit_id!r} has no power switch. "
                                   f"Switchable: {', '.join(TOGGLEABLE)}")
    if body.offline:
        # `changed` is False when the unit was already off -- the panel uses it to avoid
        # reporting an action that did not happen, and `disable()` deliberately keeps the
        # original timestamp so a double-press cannot erase how long a surface has been down.
        rec, changed = disable(unit_id, peer)
        return {"id": unit_id, "disabled": True, "at": rec["at"], "by": rec["by"],
                "changed": changed}
    changed = enable(unit_id)
    return {"id": unit_id, "disabled": False, "changed": changed}
