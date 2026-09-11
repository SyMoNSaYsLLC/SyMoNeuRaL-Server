# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""The per-surface rate budgets. One dict, published from and enforced from.

Created 2026-09-08 because there were three answers to "what is chat's hourly limit" and
no two agreed:

    appdocs.py prose          120 requests/min, 3,000/hour     <- what visitors were told
    api.py _RATE_SUGGESTED    120, 2000                        <- what the code suggested
    the running process       no bucket at all                 <- what was enforced

Three of the four published hourly figures were wrong against the table beside them, and
none of the four was applied: `_rate_for` returned `(0, 0)` unless an env var was set, and
`check_rate` treats a missing limiter as "allow". A burst of 150 posts to `ravencalc` in
1.64 seconds drew no 429.

So the numbers live here, `api.py` defaults to them instead of to no limit, `appdocs.py`
renders its prose from them, and `test_rate_limits_are_real.py` asserts the three agree.
`SYMONEURAL_RATE_<SURFACE>=N/N` still overrides, which is what an operator needs.
"""
from __future__ import annotations

#: (per_minute, per_hour) per surface. Reasoning per line is in api.py where these were
#: first written down; the values are unchanged from that table.
BUDGETS: dict[str, tuple[int, int]] = {
    "ravencalc": (240, 6000),
    "chat":      (120, 2000),
    "remix":     (40,   600),
    "image":     (20,   300),
    "sigil":     (20,   300),
    "voice":     (60,   900),
    "studio":    (60,   900),
    "exp":       (60,   900),
}


def prose(surface: str) -> str:
    """The published sentence for a surface, built from the enforced numbers."""
    per_min, per_hour = BUDGETS[surface]
    return f"{per_min:,} requests/min per address, {per_hour:,}/hour."


# ---------------------------------------------------------------------------------------
# The enforcement, moved here 2026-09-10 for the RavenCalc pilot.
#
# The budgets lived here and the limiter lived in `api.py`, which was fine while one process
# served every surface. It stops being fine the moment a surface runs on its own port: that
# process must enforce the SAME published cap, and the only two ways to get there are to
# import the limiter or to write a second one. A second implementation of a published cap is
# precisely the drift this module was created to end -- three answers to "what is chat's
# hourly limit" and no two agreeing -- so it is imported.
#
# `api.py` now imports these instead of defining them. Its own docstrings for the reasoning
# are preserved below, because the reasoning is the valuable part and it was written against
# real failures.

import asyncio
import time


class RateLimiter:
    """Token bucket per client key.

    The bucket logic is the RavenCalc service's, already in this repo and already correct;
    the only change is that the window is a parameter. The original hardcoded 60 seconds,
    and two buckets are needed here -- a burst limit and an hourly one. Reusing it with the
    minute window for both would make the hourly cap refill sixty times too fast, which is a
    limiter that looks present and enforces nothing.

    Resets on restart, deliberately.

    Per-process, and that is a real consequence of the split worth stating: N processes means
    N buckets, so a client's effective cap is per surface rather than global. That is already
    the intent -- BUDGETS is keyed by surface -- but a client hitting two surfaces now gets
    both budgets in full, where one process would still have given them both budgets in full.
    Nothing changes. What WOULD change is splitting one surface across two processes, which
    is not in the nine-process plan.
    """

    def __init__(self, rate: int, window_s: float = 60.0):
        self.rate = max(1, int(rate))
        self.capacity = float(self.rate)
        self.refill_per_sec = float(self.rate) / float(window_s)
        self.state: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.time()
        async with self._lock:
            tokens, last = self.state.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill_per_sec)
            if tokens >= 1.0:
                self.state[key] = (tokens - 1.0, now)
                return True
            self.state[key] = (tokens, now)
            return False


def limiters_for(limits: dict[str, tuple[int, int]]) -> dict[str, tuple[RateLimiter, RateLimiter]]:
    """Build the minute/hour bucket pair per surface, skipping unmetered ones.

    A surface with no configured budget gets NO limiter object at all, rather than one built
    with capacity 0. A zero-capacity bucket never refills to 1.0, so it would deny every
    single request forever -- the exact inversion of "no limit", and indistinguishable from a
    broken endpoint. Absent from this dict means unmetered.
    """
    return {
        name: (RateLimiter(per_min, 60.0), RateLimiter(per_hour, 3600.0))
        for name, (per_min, per_hour) in limits.items()
        if per_min > 0 and per_hour > 0
    }


async def allowed(limiters: dict[str, tuple[RateLimiter, RateLimiter]],
                  surface: str, key: str) -> bool:
    """Both buckets must allow, and the minute bucket is charged first.

    Ordering matters slightly: if the hourly bucket is the one that denies, the minute token
    is still spent. That is deliberate -- refunding it would mean tracking partial charges,
    and the drift is a token an hour.
    """
    pair = limiters.get(surface)
    if pair is None:            # unmetered by configuration
        return True
    minute, hour = pair
    return await minute.allow(key) and await hour.allow(key)


def client_key_from_headers(headers, peer: str | None) -> str:
    """Caddy sits in front, so the real client is in the forwarded header.

    Takes headers and peer rather than a `Request`, so this module does not import a web
    framework -- a surface process, a WebSocket handler and a test all have those two things
    and do not all have a `Request`.
    """
    fwd = ""
    try:
        fwd = headers.get("x-forwarded-for", "") or ""
    except AttributeError:
        pass
    return fwd.split(",")[0].strip() or (peer or "unknown")
