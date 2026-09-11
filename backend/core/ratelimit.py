"""Per-address rate limiting, and the one content refusal.

Every surface depends on `throttled_for(<name>)`; budgets come from core.config.LIMITS.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from core.config import LIMITS, _MINOR, _SEXUAL
from runtime.lib.ratelimits import allowed, client_key_from_headers, limiters_for

log = logging.getLogger("symoneural.api")


def denied(prompt: str) -> bool:
    """True only for the intersection of a child term and a sexual term."""
    return bool(_MINOR.search(prompt) and _SEXUAL.search(prompt))


# A surface with no configured budget gets NO limiter object at all, rather than one
# built with capacity 0. A zero-capacity bucket never refills to 1.0, so it would deny
# every single request forever -- the exact inversion of "no limit", and indistinguishable
# from a broken endpoint. Absent from this dict means unmetered; see check_rate.
_limiters = limiters_for(LIMITS)


def client_key(request: Request) -> str:
    """Caddy sits in front, so the real client is in the forwarded header."""
    return client_key_from_headers(request.headers,
                                    request.client.host if request.client else None)


async def check_rate(surface: str, key: str) -> bool:
    """Both buckets must allow, and the minute bucket is charged first.

    Ordering matters slightly: if the hourly bucket is the one that denies, the minute token
    is still spent. That is deliberate -- refunding it would mean tracking partial charges,
    and the drift is a token an hour.
    """
    return await allowed(_limiters, surface, key)


def throttled_for(surface: str):
    """A dependency that rate-limits against this endpoint's own budget."""
    async def dep(request: Request) -> None:
        key = client_key(request)
        if not await check_rate(surface, key):
            per_min, per_hour = LIMITS[surface]
            log.warning("rate limited %s on %s", key, surface)
            raise HTTPException(
                429,
                f"Easy — {surface} is capped at {per_min}/min and {per_hour}/hour per "
                f"address. RavenCalc runs on the CPU and is far less restricted.")
    return dep


Throttled = Annotated[None, Depends(throttled_for("chat"))]


def _try(sem: asyncio.Semaphore) -> bool:
    try:
        sem.acquire_nowait()  # type: ignore[attr-defined]
        return True
    except AttributeError:
        # asyncio.Semaphore has no acquire_nowait; emulate it.
        if sem._value <= 0:  # noqa: SLF001
            return False
        sem._value -= 1      # noqa: SLF001
        return True
    except Exception:
        return False
