"""Route authorization classes for this application, as an explicit dependency seam.

Every route carries exactly one class, declared at its definition. That is the whole point:
before this module the only way to know a route's authorization was to read its body, and the
plan that preceded it assumed a middleware interception point this router does not have.

    PUBLIC_BOOTSTRAP           no checks. Reachable with the surface switched off.
    SHARED_AUTH                no checks. Identity may legitimately be absent.
    AUTHENTICATED_APPLICATION  session required. No entitlement.
    ENTITLEMENT_REQUIRED       session + customer entitlement.
    OPERATOR_ONLY              session + operator role. NO customer entitlement.

## Why prefix middleware was rejected

`/logout` must succeed with an absent, expired or already-invalidated session -- a user
holding a dead cookie has to be able to clear it. A prefix rule cannot express that without a
pattern hole, and a pattern hole is how an entitlement-required route silently becomes exempt.
Here the exemption is the class on the route, so it is greppable and testable.

## Precedence, and why operator is not an entitlement

    authentication -> class -> (entitlement | operator role) -> ownership

An operator is never denied an operator-only route for lacking a *customer* entitlement.
Operator authority and customer entitlement are separate axes; conflating them would lock the
operator out of the surface they administer.

## Fail closed, including when the check cannot run

If shared accounts is unavailable -- switched off, database missing, unreadable -- an
entitlement-required route returns 403. An authorization check that could not run has NOT
passed. Treating "cannot check" as "no restriction" is the fail-open reading and is the bug
this file is most concerned with.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from ..lib import store

log = logging.getLogger("symoneural.dispatchos.authz")

PUBLIC_BOOTSTRAP = "PUBLIC_BOOTSTRAP"
SHARED_AUTH = "SHARED_AUTH"
AUTHENTICATED_APPLICATION = "AUTHENTICATED_APPLICATION"
ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
OPERATOR_ONLY = "OPERATOR_ONLY"

CLASSES = (PUBLIC_BOOTSTRAP, SHARED_AUTH, AUTHENTICATED_APPLICATION,
           ENTITLEMENT_REQUIRED, OPERATOR_ONLY)

#: This application's slug in the shared entitlement table.
APPLICATION_SLUG = "dispatchos"


def _entitlement_or_403(user: dict) -> None:
    """Deny unless an active shared-accounts grant exists for this application.

    Four denials, deliberately distinguished in the log and identical to the caller:
    no correspondence, no grant, unavailable subsystem, malformed row.
    """
    account_id = store.shared_account_id(user["id"])
    if not account_id:
        # NULL reference. Not an error: this user simply has no shared identity.
        log.info("entitlement denied: user %s has no shared identity", user["id"])
        raise HTTPException(403, "this account is not entitled to this application")

    try:
        import accounts as shared
    except Exception:                                    # pragma: no cover - import guard
        log.error("entitlement denied: shared accounts module unavailable")
        raise HTTPException(403, "entitlement cannot be verified") from None

    try:
        ok = shared.is_entitled(account_id, APPLICATION_SLUG)
    except getattr(shared, "MalformedEntitlement", Exception) as exc:
        # Malformed is louder than absent: absent is a normal answer, malformed is a database
        # telling us something unreadable, and an operator should see it.
        log.error("entitlement denied: malformed record for %s/%s: %s",
                  account_id, APPLICATION_SLUG, exc)
        raise HTTPException(403, "entitlement cannot be verified") from None
    except Exception as exc:
        # Unavailable store, missing file, unreadable database. Cannot check -> has not passed.
        log.error("entitlement denied: shared accounts unavailable (%s): %s",
                  exc.__class__.__name__, exc)
        raise HTTPException(403, "entitlement cannot be verified") from None

    if not ok:
        log.info("entitlement denied: no active grant for %s/%s",
                 account_id, APPLICATION_SLUG)
        raise HTTPException(403, "this account is not entitled to this application")


def authorize(request: Request, route_class: str) -> dict | None:
    """Apply one class. Returns the user when a session was required, else None.

    Reuses the router's existing guards rather than reimplementing them, so authentication
    and role behaviour are unchanged by construction.
    """
    # `..dispatchos`, not `.apps`. This module moved into `apps/` in the
    # restructure and its relative import moved with it, so `.apps` now resolves
    # to `dispatchos.apps.apps`, which does not exist. Anonymous callers are
    # refused by the guard above before reaching this line, so the failure is
    # invisible until somebody signs in -- and then every guarded route 500s.
    # Still a local import, for the cycle reason it always was.
    from ..dispatchos import _operator, _signed_in

    if route_class not in CLASSES:
        raise ValueError(f"unknown route class: {route_class!r}")

    if route_class in (PUBLIC_BOOTSTRAP, SHARED_AUTH):
        return None
    if route_class == AUTHENTICATED_APPLICATION:
        return _signed_in(request)
    if route_class == OPERATOR_ONLY:
        return _operator(request)            # 401 then 403; no entitlement consulted
    user = _signed_in(request)               # ENTITLEMENT_REQUIRED
    _entitlement_or_403(user)
    return user


def require(route_class: str):
    """A FastAPI dependency for one class. Attach at the route definition."""
    if route_class not in CLASSES:
        raise ValueError(f"unknown route class: {route_class!r}")

    async def _dep(request: Request) -> dict | None:
        return authorize(request, route_class)

    _dep.__name__ = f"require_{route_class.lower()}"
    _dep.route_class = route_class          # type: ignore[attr-defined]
    return _dep
