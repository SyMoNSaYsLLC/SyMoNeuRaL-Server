"""The HTTP surface for accounts. Mounted at `/api/accounts` by `backend/server.py`.

The module beside this one does all the thinking -- hashing, throttling, session rows.
This file is deliberately thin, and everything in it is about the boundary: what a
stranger may send, what a stranger may see, and what goes in the cookie.

Four decisions that are easy to get wrong and are made here on purpose:

**The cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` in production.** HttpOnly is the
whole point -- a session token readable by `document.cookie` is a session token that any
injected script exfiltrates. `Secure` is conditional on the request scheme rather than
hardcoded, because hardcoding it breaks `http://127.0.0.1:8800` for anybody developing
against the API directly, and hardcoding it off would ship a token over plaintext.

**A wrong password and an unknown address give the same answer.** `verify()` already pays
for a full scrypt against a dummy hash so the timing does not answer "is this person a
customer"; returning a different *message* would give away for free what that cost buys.

**The throttle's `Retry-After` is reported, because a lockout the visitor cannot see is
indistinguishable from a broken login.** That is a reading, not a leak: it is about the
request in front of us and says nothing about whether the account exists.

**Nothing here invents a plan, a tier or a price.** `.claude/CLAUDE.md` forbids it, and a
route that returned a `plan` field would be the place a price eventually appeared.
Pricing questions go to symonsayadmin@symoneural.com.
"""
from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from . import (AccountExists, AccountsError, AccountsUnavailable, InvalidEmail,
               Throttled, WeakPassword, change_password_async, create_account_async,
               enabled, init_db, issue_session, read_session, revoke_all_sessions,
               revoke_session, session_ttl_s, sessions_for, unit_state, verify_async)

log = logging.getLogger("symoneural.accounts")

from .module import SESSION_COOKIE

def _no_store(response: Response) -> None:
    """Authenticated/session responses must never be reused from a browser cache."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(tags=["accounts"], dependencies=[Depends(_no_store)])

# One spelling, defined in `module.py` and imported here. It was a literal in this file and
# a second literal would have appeared the moment a second surface needed it.
COOKIE = SESSION_COOKIE


# Every field has a default for the same reason the tuner's models do: a *missing*
# required field makes pydantic raise a ValidationError whose `input` is the whole
# request body, and FastAPI serialises that into the 422 -- which would echo the
# password back inside an error document. With defaults there is no validation path
# that can touch these values; the handlers check them by hand.
class SignupBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str = ""
    password: str = ""
    display_name: str = ""
    quote_id: str = ""


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    email: str = ""
    password: str = ""


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    old: str = ""
    new: str = ""


def _client_ip(request: Request) -> str:
    """The visitor's address, as far as it can honestly be known.

    Caddy fronts everything, so the socket address is always the loopback proxy and
    `X-Forwarded-For` is the only thing carrying the real client. Take the FIRST hop:
    later entries are appended by intermediaries and the first is the one Caddy wrote.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(503, "accounts are not switched on for this box")


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE, token,
        max_age=session_ttl_s(), httponly=True, samesite="lax",
        # Not hardcoded: see the module docstring. `url.scheme` is what the request
        # actually arrived on, which behind Caddy is https in production and http for
        # anybody hitting 127.0.0.1:8800 directly.
        secure=request.url.scheme == "https",
        path="/")


def _current(request: Request) -> dict:
    token = request.cookies.get(COOKIE, "")
    sess = read_session(token) if token else None
    if not sess:
        raise HTTPException(401, "not signed in")
    return sess


@router.get("/status", summary="Whether accounts are open on this box")
async def status_route() -> dict:
    """No counts and no addresses. How many customers exist is not a visitor's business,
    and a count is also a slow leak of how the business is doing."""
    on = enabled()
    return {
        "enabled": on,
        "signup_open": on,
        "session_ttl_s": session_ttl_s() if on else None,
        # Both of these are rendered verbatim as a sentence on /account.html, so they are
        # written as sentences. The lower-case, full-stop-less version shipped for a while
        # and read as a log line that had escaped onto the page.
        "note": ("Sign in, or create an account." if on else
                 "This box has not been given a session secret, so accounts are closed."),
    }


@router.post("/signup", status_code=201, summary="Create an account")
async def signup(body: SignupBody, request: Request, response: Response) -> dict:
    _require_enabled()
    try:
        init_db()
        acct = await create_account_async(
            body.email, body.password,
            display_name=(body.display_name or None),
            quote_id=(body.quote_id or None))
        token = issue_session(acct["id"])
    except (InvalidEmail, WeakPassword) as exc:
        # These messages are about what the visitor typed and are safe to repeat --
        # they carry no information about any other account.
        raise HTTPException(400, str(exc)) from None
    except AccountExists:
        raise HTTPException(409, "an account already exists for that address") from None
    except AccountsUnavailable as exc:
        log.error("accounts unavailable: %s", exc)
        raise HTTPException(503, "accounts are not configured on this box") from None
    except AccountsError:
        raise HTTPException(400, "could not create that account") from None
    _set_cookie(request, response, token)
    return acct


@router.post("/login", summary="Sign in")
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    _require_enabled()
    try:
        init_db()
        acct = await verify_async(body.email, body.password, ip=_client_ip(request))
    except Throttled as exc:
        # 429 with Retry-After, because a lockout nobody can see reads as a broken login.
        raise HTTPException(429, str(exc),
                            headers={"Retry-After": str(exc.retry_after)}) from None
    except AccountsUnavailable:
        raise HTTPException(503, "accounts are not configured on this box") from None
    if not acct:
        # One answer for a wrong password and for an address with no account. Saying
        # which would give away for free exactly what the dummy-hash timing cost buys.
        raise HTTPException(401, "that address and password do not match an account")
    token = issue_session(acct["id"])
    _set_cookie(request, response, token)
    return acct


@router.post("/logout", status_code=204, summary="Sign out")
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(COOKIE, "")
    if token:
        try:
            revoke_session(token)
        except AccountsUnavailable:
            pass
    # Clear the cookie whatever happened. A logout that leaves the cookie in place
    # because the row was already gone is a logout the visitor cannot trust.
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/me", summary="The signed-in account")
async def me(request: Request) -> dict:
    _require_enabled()
    return _current(request)["account"]


@router.get("/sessions", summary="Live sessions for the signed-in account")
async def my_sessions(request: Request) -> dict:
    _require_enabled()
    sess = _current(request)
    rows = sessions_for(sess["account_id"])
    # Mark which row is the browser asking. Without it the list is a set of opaque ids
    # and "sign out everywhere else" is a button nobody can aim.
    for r in rows:
        r["current"] = (r.get("sid") == sess["sid"])
    return {"count": len(rows), "sessions": rows}


@router.post("/password", status_code=204, summary="Change the password")
async def password(body: PasswordBody, request: Request, response: Response) -> Response:
    _require_enabled()
    sess = _current(request)
    try:
        # Returns False for a wrong current password -- it does not raise for that, and
        # treating a False as success would be a password change that silently did not
        # happen. Throttled DOES raise, and shares the login counter on purpose.
        if not await change_password_async(sess["account_id"], body.old, body.new):
            raise HTTPException(403, "the current password is not correct")
    except Throttled as exc:
        raise HTTPException(429, str(exc),
                            headers={"Retry-After": str(exc.retry_after)}) from None
    except WeakPassword as exc:
        raise HTTPException(400, str(exc)) from None
    except AccountsUnavailable:
        raise HTTPException(503, "accounts are not configured on this box") from None
    # change_password kills every session including this one. Issue a fresh cookie so the
    # visitor is not silently signed out by succeeding.
    _set_cookie(request, response, issue_session(sess["account_id"]))
    response.status_code = 204
    return response


@router.post("/signout-everywhere", status_code=204,
             summary="Revoke every session for this account")
async def signout_everywhere(request: Request, response: Response) -> Response:
    _require_enabled()
    sess = _current(request)
    revoke_all_sessions(sess["account_id"])
    response.delete_cookie(COOKIE, path="/")
    response.status_code = 204
    return response


class CreditBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    account_id: str = ""
    amount: int = 0
    note: str = ""


def build_router(accounts, *, secure_cookies: bool = False,
                 app_name: str = "") -> APIRouter:
    """An accounts router bound to one `AccountsModule`, for a surface with its own process.

        router = build_router(accounts, secure_cookies=..., app_name="DJ")
        app.include_router(router)          # /auth/*, /account/*, owner /admin/*

    The module-level `router` above is the API's own, against the process-wide database.
    This is the factory form, and it exists because `symoneural_dj` runs on its own port
    against its own database file and cannot use a router that resolved `db_path()` at
    import time.

    ## Why this router authenticates itself

    The DJ's one auth middleware lets `/auth/`, `/account/` and `/admin/` through
    untouched -- deliberately, because login cannot require being logged in. That makes
    every check below load-bearing rather than defence in depth: nothing upstream is
    checking these paths. The `/admin/` routes in particular are reachable by any
    stranger who can reach the port, and are guarded here or nowhere.

    ## `secure_cookies` is a parameter, not a scheme sniff

    The module-level `_set_cookie` reads `request.url.scheme`, which is right for the API:
    it is always behind Caddy, so the scheme is the real one. A standalone service may sit
    behind anything, so its operator states the answer (`DJ_SECURE_COOKIES`) rather than
    having it inferred from a header an attacker can set.
    """
    api = APIRouter(tags=[f"accounts:{app_name}" if app_name else "accounts"],
                   dependencies=[Depends(_no_store)])
    cookie_name = accounts.cookie_name()

    def _issue(response: Response, token: str) -> None:
        response.set_cookie(cookie_name, token, max_age=session_ttl_s(), httponly=True,
                            samesite="lax", secure=bool(secure_cookies), path="/")

    def _identify(request: Request):
        auth = request.headers.get("authorization", "")
        bearer = auth[7:] if auth.startswith("Bearer ") else ""
        return accounts.identify(cookie=request.cookies.get(cookie_name, ""), bearer=bearer)

    def _require(request: Request):
        ident = _identify(request)
        if ident is None:
            raise HTTPException(401, "login required")
        return ident

    def _require_owner(request: Request):
        ident = _require(request)
        if not ident.is_owner:
            # 404, not 403. A 403 confirms the route exists and is worth attacking; the
            # same reasoning the DJ already applies to job ids it will not show you.
            raise HTTPException(404, "not found")
        return ident

    @api.post("/auth/signup", status_code=201, summary="Create an account")
    async def _signup(body: SignupBody, request: Request, response: Response) -> dict:
        try:
            with accounts.bind():
                init_db()
                acct = await create_account_async(
                    body.email, body.password,
                    display_name=(body.display_name or None))
                token = issue_session(acct["id"])
        except (InvalidEmail, WeakPassword) as exc:
            raise HTTPException(400, str(exc)) from None
        except AccountExists:
            raise HTTPException(409, "an account already exists for that address") from None
        except AccountsUnavailable:
            raise HTTPException(503, "accounts are not configured on this box") from None
        except AccountsError:
            raise HTTPException(400, "could not create that account") from None
        _issue(response, token)
        return acct

    @api.post("/auth/login", summary="Sign in")
    async def _login(body: LoginBody, request: Request, response: Response) -> dict:
        try:
            with accounts.bind():
                init_db()
                acct = await verify_async(body.email, body.password,
                                          ip=_client_ip(request))
                if not acct:
                    # Same answer for a wrong password and an unknown address.
                    raise HTTPException(401,
                                        "that address and password do not match an account")
                token = issue_session(acct["id"])
        except Throttled as exc:
            raise HTTPException(429, str(exc),
                                headers={"Retry-After": str(exc.retry_after)}) from None
        except AccountsUnavailable:
            raise HTTPException(503, "accounts are not configured on this box") from None
        _issue(response, token)
        return acct

    @api.post("/auth/logout", status_code=204, summary="Sign out")
    async def _logout(request: Request, response: Response) -> Response:
        token = request.cookies.get(cookie_name, "")
        if token:
            with accounts.bind(), contextlib.suppress(AccountsUnavailable):
                revoke_session(token)
        response.delete_cookie(cookie_name, path="/")
        response.status_code = 204
        return response

    @api.get("/account/me", summary="The signed-in account and what it can spend")
    async def _me(request: Request) -> dict:
        ident = _require(request)
        return {
            "id": ident.user_id,
            "email": ident.user.email,
            "display_name": ident.user.display_name,
            "role": ident.user.role,
            "is_owner": ident.is_owner,
            "via": ident.via,
            # None, not 0. An owner has no balance rather than an empty one, and a client
            # that renders `0` would tell the owner they cannot afford their own product.
            "balance": accounts.balance(ident),
        }

    @api.get("/account/history", summary="This account's recent charges and credits")
    async def _history(request: Request) -> dict:
        ident = _require(request)
        if ident.is_owner:
            return {"entries": [], "note": "owner actions are free and are not metered"}
        return {"entries": accounts.meter.history(ident.user_id)}

    @api.get("/admin/users", summary="Every account (owner only)")
    async def _users(request: Request) -> dict:
        _require_owner(request)
        rows = accounts.accounts.listing()
        for row in rows:
            row["balance"] = accounts.meter.balance(str(row.get("id", "")))
        return {"count": len(rows), "accounts": rows}

    @api.post("/admin/credit", summary="Add SyMoN tokens to an account (owner only)")
    async def _credit(body: CreditBody, request: Request) -> dict:
        _require_owner(request)
        if not body.account_id:
            raise HTTPException(400, "account_id is required")
        if body.amount <= 0:
            raise HTTPException(400, "amount must be positive")
        if accounts.accounts.public(body.account_id) is None:
            raise HTTPException(404, "no such account")
        balance = accounts.meter.credit(body.account_id, body.amount, body.note or "admin")
        return {"account_id": body.account_id, "balance": balance}

    return api


def status() -> dict:
    """The rack unit, as a plain dict, shaped for `api.py`'s `Unit`.

    The state comes from `unit_state()` in the module beside this one rather than being
    recomputed here, so there is exactly one definition of what "the account surface is
    working" means. `offline` on a box with no session secret is a reading and not a
    decoration -- the surface genuinely cannot authenticate anybody, and the detail line
    names what is missing instead of leaving somebody to guess.
    """
    state, detail = unit_state()
    return {
        "id": "accounts", "label": "SyMoNeuRaL Account", "slot": "1U",
        "state": state, "bus": "cpu", "href": "/account.html",
        "spec": "scrypt N=2^17 \u00b7 server-side sessions",
        "detail": detail,
    }
