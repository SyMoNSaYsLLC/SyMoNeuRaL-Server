"""The DispatchOS HTTP surface.

Task #106. Mounted by `backend/server.py` at `/api/dispatchos`, plus a UI router that serves
the page at `/demo/dispatchos` -- the URL Garrett named.

## Two tiers, and they are enforced here rather than in the UI

`operator` sees the whole board and is the only role that can quote, dispatch, add drivers
or change rate rules. `customer` sees their own trips and can request one. Every route that
needs a tier calls `_operator()` or `_signed_in()`; nothing relies on the page hiding a
button, because the API is reachable by anything holding a session cookie.

## The edge auth is not this

`ops/Caddyfile` puts basicauth in front of `/demo/dispatchos` so the application is not on
the open internet at all. That is one flat tier and it authenticates rather than authorises
-- all four of its accounts reach the same door. The two tiers below are the application's
own, and they are what Garrett asked to test: *"garrett and ben logins (including test
customer level garrett and ben logins)"*.

`/api/dispatchos/*` is deliberately NOT behind that edge block: it answers 401 to a
stranger and 503 when the surface is switched off, which is the same posture as
`/api/accounts` and `/api/project`. Putting basicauth in front of the XHR path as well
would make every request depend on the browser volunteering credentials for a path it was
never challenged on.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from .lib import ai
from .apps import authz
from .apps import page
from .apps import quotes
from .lib import store

log = logging.getLogger("symoneural.dispatchos")

def _no_store(response: Response) -> None:
    """Dispatch data and session responses must not be reusable from a cache."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(tags=["dispatchos"], dependencies=[Depends(_no_store)])
ui_router = APIRouter(include_in_schema=False)

COOKIE = "symon_dispatchos"


# Every body model forbids unknown fields and defaults its strings. `extra="forbid"` means a
# typo'd field is a 422 the caller can see rather than a silently ignored value -- the shape
# `apps/accounts` settled on after a password ended up echoed inside a validation error.
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(_Body):
    username: str = ""
    password: str = ""


class BookingBody(_Body):
    rider: str = ""
    contact: str = ""
    pickup: str = ""
    dropoff: str = ""
    when_text: str = ""
    passengers: int = 1
    luggage: int = 0
    notes: str = ""


class AdvanceBody(_Body):
    to: str = ""
    driver_id: int | None = None
    detail: str = ""


class QuoteBody(_Body):
    distance_km: float | None = None


class RulesBody(_Body):
    rules: dict | None = None


class DriverBody(_Body):
    name: str = ""
    vehicle: str = ""


class MessageBody(_Body):
    kind: str = "reminder"


class AskBody(_Body):
    question: str = ""


def _require_enabled() -> None:
    if not store.enabled():
        # 503 and not 404: the surface exists and is switched off, and saying so is how an
        # operator finds out it needs SYMONEURAL_DISPATCHOS_ENABLED rather than filing a bug.
        raise HTTPException(503, "DispatchOS is not switched on on this box")


def _signed_in(request: Request) -> dict:
    _require_enabled()
    user = store.read_session(request.cookies.get(COOKIE, ""))
    if not user:
        raise HTTPException(401, "sign in to use DispatchOS")
    return user


def _operator(request: Request) -> dict:
    user = _signed_in(request)
    if user["role"] != "operator":
        raise HTTPException(403, "that is an operator action")
    return user


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token, max_age=store.SESSION_TTL_S, httponly=True, samesite="lax",
        # Secure whenever the request arrived over TLS. HttpOnly is the important half: a
        # session token readable by document.cookie is one any injected script can take.
        secure=request.url.scheme == "https", path="/")


def _client_ip(request: Request) -> str:
    """The address written by the trusted Caddy hop, or the socket as a fallback."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _visible(user: dict) -> list[dict]:
    """The board this user is allowed to see. One place, so no route can forget."""
    if user["role"] == "operator":
        return store.list_bookings()
    return store.list_bookings(owner_id=user["id"])


def _owned_or_403(user: dict, bid: int) -> dict:
    b = store.get_booking(bid)
    if user["role"] != "operator" and b.get("owner_id") != user["id"]:
        # 403 rather than 404: the caller is authenticated, and pretending the row does not
        # exist to a signed-in user makes a real bug indistinguishable from a permission one.
        raise HTTPException(403, "that booking is not yours")
    return b


# ------------------------------------------------------------------ session

@router.get("/status", summary="Whether DispatchOS is switched on here", dependencies=[Depends(authz.require(authz.PUBLIC_BOOTSTRAP))])
async def status_route() -> dict:
    on = store.enabled()
    return {
        "enabled": on,
        "assistant_connected": ai.available(),
        "rates_configured": quotes.configured(store.get_setting("rules") if on else None),
        "states": list(store.STATES),
    }


@router.post("/login", summary="Sign in to DispatchOS", dependencies=[Depends(authz.require(authz.SHARED_AUTH))])
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    _require_enabled()
    try:
        token = await asyncio.to_thread(store.login, body.username, body.password,
                                        ip=_client_ip(request))
    except store.DispatchThrottled as exc:
        raise HTTPException(429, str(exc),
                            headers={"Retry-After": str(exc.retry_after)}) from None
    if not token:
        # One answer for a wrong password and for an unknown username.
        raise HTTPException(401, "that username and password do not match an account")
    _set_cookie(request, response, token)
    user = store.read_session(token)
    return {"user": user}


@router.post("/logout", status_code=204, summary="Sign out", dependencies=[Depends(authz.require(authz.SHARED_AUTH))])
async def logout(request: Request, response: Response) -> Response:
    store.logout(request.cookies.get(COOKIE, ""))
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get("/me", summary="The signed-in user", dependencies=[Depends(authz.require(authz.AUTHENTICATED_APPLICATION))])
async def me(request: Request) -> dict:
    return {"user": _signed_in(request)}


# ------------------------------------------------------------------ the board

@router.get("/board", summary="Bookings visible to the signed-in user", dependencies=[Depends(authz.require(authz.ENTITLEMENT_REQUIRED))])
async def board(request: Request) -> dict:
    user = _signed_in(request)
    bookings = _visible(user)
    return {
        "user": user,
        "bookings": bookings,
        "counts": store.counts() if user["role"] == "operator" else {},
        "drivers": store.list_drivers() if user["role"] == "operator" else [],
        "rates_configured": quotes.configured(store.get_setting("rules")),
    }


@router.post("/bookings", status_code=201, summary="Request a trip", dependencies=[Depends(authz.require(authz.ENTITLEMENT_REQUIRED))])
async def create_booking(body: BookingBody, request: Request) -> dict:
    user = _signed_in(request)
    try:
        # A customer's own request is owned by them. An operator taking a booking over the
        # phone -- which the preview calls out explicitly, "whether the request came in by
        # phone or through the intake page" -- creates an unowned row.
        owner = user["id"] if user["role"] == "customer" else None
        b = store.create_booking(
            actor=user["username"], owner_id=owner, rider=body.rider or user["label"],
            contact=body.contact, pickup=body.pickup, dropoff=body.dropoff,
            when_text=body.when_text, passengers=body.passengers, luggage=body.luggage,
            notes=body.notes)
    except store.DispatchError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"booking": b}


@router.get("/bookings/{bid}", summary="One booking, with its record trail", dependencies=[Depends(authz.require(authz.ENTITLEMENT_REQUIRED))])
async def one_booking(bid: int, request: Request) -> dict:
    user = _signed_in(request)
    try:
        return {"booking": _owned_or_403(user, bid)}
    except store.DispatchError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/bookings/{bid}/quote", summary="Quote a trip against the operator's rules", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def quote_booking(bid: int, body: QuoteBody, request: Request) -> dict:
    user = _operator(request)
    try:
        b = store.get_booking(bid)
        q = quotes.quote(b, store.get_setting("rules"), distance_km=body.distance_km)
        return {"booking": store.set_quote(bid, q, actor=user["username"])}
    except store.DispatchError as exc:
        raise HTTPException(400, str(exc)) from None
    except quotes.RulesError as exc:
        # The operator's own configuration is broken; this is not a customer-facing string
        # but it is an operator-facing one, and it names the field.
        raise HTTPException(400, f"rate rules are invalid: {exc}") from None


@router.post("/bookings/{bid}/advance", summary="Move a booking one step", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def advance_booking(bid: int, body: AdvanceBody, request: Request) -> dict:
    user = _operator(request)
    try:
        b = store.advance(bid, body.to, actor=user["username"],
                          driver_id=body.driver_id, detail=body.detail)
    except store.DispatchError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"booking": b}


@router.post("/bookings/{bid}/message", status_code=201,
             summary="Compose a reminder or review request (never sent)", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def message(bid: int, body: MessageBody, request: Request) -> dict:
    user = _operator(request)
    b = store.get_booking(bid)
    text = _message_text(body.kind, b)
    try:
        m = store.compose_message(bid, body.kind, text, to_whom=b.get("contact", ""))
    except store.DispatchError as exc:
        raise HTTPException(400, str(exc)) from None
    log.info("dispatchos: %s composed %s for %s (not sent)", user["username"], body.kind, b["ref"])
    return {"message": m,
            # Repeated in the payload and not only in the docs, because this is the field a
            # UI would otherwise render as "sent".
            "delivery": "not sent -- live routing requires approved email configuration"}


def _message_text(kind: str, b: dict) -> str:
    when = b.get("when_text") or "the agreed time"
    if kind == "reminder":
        return (f"Reminder for {b['ref']}: pickup at {b.get('pickup')} at {when}. "
                f"Reply to this message if anything has changed.")
    if kind == "confirmation":
        return (f"Booking {b['ref']} is confirmed: {b.get('pickup')} to {b.get('dropoff')} "
                f"at {when}.")
    return (f"Thanks for travelling with us ({b['ref']}). If you have a moment, a short "
            f"review helps a great deal.")


# ------------------------------------------------------------------ operator configuration

@router.get("/rules", summary="The operator's rate rules", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def get_rules(request: Request) -> dict:
    _operator(request)
    r = store.get_setting("rules")
    return {"rules": r, "configured": quotes.configured(r)}


@router.put("/rules", summary="Set the operator's rate rules", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def put_rules(body: RulesBody, request: Request) -> dict:
    _operator(request)
    try:
        clean = quotes.validate_rules(body.rules)
    except quotes.RulesError as exc:
        raise HTTPException(400, str(exc)) from None
    store.set_setting("rules", clean)
    return {"rules": clean, "configured": quotes.configured(clean)}


@router.get("/drivers", summary="Drivers", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def get_drivers(request: Request) -> dict:
    _operator(request)
    return {"drivers": store.list_drivers()}


@router.post("/drivers", status_code=201, summary="Add a driver", dependencies=[Depends(authz.require(authz.OPERATOR_ONLY))])
async def post_driver(body: DriverBody, request: Request) -> dict:
    _operator(request)
    try:
        return {"driver": store.add_driver(body.name, body.vehicle)}
    except store.DispatchError as exc:
        raise HTTPException(400, str(exc)) from None


# ------------------------------------------------------------------ SyMon AI

@router.post("/ask", summary="Ask SyMon AI about the board", dependencies=[Depends(authz.require(authz.ENTITLEMENT_REQUIRED))])
async def ask(body: AskBody, request: Request) -> dict:
    user = _signed_in(request)
    bookings = _visible(user)
    counts = store.counts() if user["role"] == "operator" else {}
    try:
        # `asyncio.to_thread`, and it is NOT a tidy-up -- calling `ai.ask` directly from this
        # coroutine DEADLOCKS THE WHOLE API. The injected callable is `guide_ask_model`, which
        # does `asyncio.run_coroutine_threadsafe(...).result(timeout=45)`: it schedules work on
        # this event loop and then blocks waiting for it. Blocking the loop from inside the
        # loop means the scheduled coroutine can never run, so the call sits there until its
        # timeout while every other request on the box waits behind it.
        #
        # This is exactly why `guide` calls it from a worker thread (`asyncio.to_thread` in
        # its own path) and why `guide_ask_model`'s docstring says "called from a worker
        # thread". Found by the end-to-end smoke run, not by the unit tests: those inject a
        # plain synchronous stub, which cannot reproduce a deadlock that only exists when the
        # callable needs the loop it is being called from.
        out = await asyncio.to_thread(ai.ask, body.question, bookings, counts)
    except ai.ModelUnusable as exc:
        # Degrade, do not retry and do not start the model. The reason is carried to the UI
        # so the page can say the assistant was not consulted -- an answer that looks like
        # the assistant but was not is worse than no answer.
        out = ai.local_answer(body.question, bookings, counts)
        out["reason"] = str(exc)
    return out


# ------------------------------------------------------------------ the page

@ui_router.get("/demo/dispatchos", response_class=HTMLResponse)
async def dispatchos_page() -> HTMLResponse:
    """The application page.

    Served by the API rather than from `site/` because the path has no extension and
    `scripts/deploy.sh` publishes `site/` at `-maxdepth 1`. That also keeps it out of the
    #107 maintenance banner, which is stamped into the generated static pages.
    """
    return HTMLResponse(page.PAGE, headers={"Cache-Control": "no-store",
                                            "Pragma": "no-cache"})
