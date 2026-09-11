"""Symon Say News -- the collector behind the live ticker on symoneural.com.

Garrett asked for an ESPN-style bar along the bottom of the site, carrying not sports but the
news this site is about: "new technology, models, releases, robotics, hardware, betas,
integrations etc etc", and said it would need "a symoneural webscraping agent and web search
agent". This package is those two agents. What they actually are, stated plainly because this
repo does not describe a capability as more than it is:

  * the collector arm reads publisher-authored RSS and Atom feeds -- documents published for
    exactly this purpose. It is not scraping HTML and it does not run a browser.
  * the search arm sends a query to public search feeds that need no API key (Google News RSS
    search, Bing News with `format=RSS`, hnrss' search) and parses the results with the same
    parser. Query -> feed -> parse. That is the whole of it.

## Shape, and why it is this shape

Copied from `apps/gateway`, which solved the same problem: an outbound fetch that must not
happen on the request path.

  * `enabled()` gates the whole surface on one env var, so the default state of a public box
    is "makes no outbound requests at all".
  * `refresher()` is an asyncio task started from `api.py`'s `lifespan`, which is how every
    other background job in this repo runs. **There is no systemd timer and none is needed**
    -- which matters because installing one requires root and root is Garrett's.
  * the read endpoint serves the cache and never triggers a fetch. `apps/gateway/routes.py`
    states the reason and it applies here with more force, since this package talks to eight
    hosts rather than one: an endpoint that fetched on demand would be an unauthenticated
    outbound-request trigger on a public-facing box. The refresher owns the rate.

## What the bar shows when everything fails

The honest answer, decided before the code was written. The last good items are kept and
served with `age_s` and `stale`, and every item carries its own publication timestamp. A
ticker that showed yesterday's headlines as though they were live would be the exact
dishonesty CLAUDE.md's status-indicator rule exists to prevent, so the payload always says how
old it is and the bar renders that. If there has never been a good pass, `items` is empty and
the bar does not render at all -- there is no placeholder headline.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from . import collect, feeds, rank
from . import router  # noqa: F401  -- imported for the side effect of existing: `api.py`
# reaches it as `news.router.router`, and without this line that attribute lookup fails at
# import time rather than at request time, which is a startup crash instead of a 500.

log = logging.getLogger("symoneural.news")

ENV_ENABLED = "SYMONEURAL_NEWS_ENABLED"
ENV_INTERVAL = "SYMONEURAL_NEWS_INTERVAL_S"

# 15 minutes. A news ticker does not need to be a second-by-second feed, and the interval is
# also the politeness budget: a default pass is 28 fetches -- 10 sources plus 6 queries across 3
# search engines -- so ~112 requests an hour spread over eight hosts, which is well inside what
# a public feed expects from one reader. The ceiling is 34 a pass, since `collect.MAX_QUERIES`
# caps an env-supplied query list at 8. Both numbers are asserted against the tuples in
# test_news.py; the version of this comment that said `32 ... 7 hosts` was true of an
# earlier source list and went stale the moment two more publishers landed.
DEFAULT_INTERVAL_S = 900.0
MIN_INTERVAL_S = 300.0     # floor, so a mistyped env var cannot turn this into a hammer
MAX_INTERVAL_S = 21600.0   # ceiling, so a mistyped env var cannot turn it into a monument


def enabled() -> bool:
    return os.environ.get(ENV_ENABLED) == "1"


def interval_s() -> float:
    raw = os.environ.get(ENV_INTERVAL)
    if not raw:
        return DEFAULT_INTERVAL_S
    try:
        want = float(raw)
    except ValueError:
        log.warning("%s=%r is not a number; using %.0fs", ENV_INTERVAL, raw,
                    DEFAULT_INTERVAL_S)
        return DEFAULT_INTERVAL_S
    return min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, want))


class NewsCache:
    """The last good pass, plus what the last pass thought of itself.

    Deliberately not a plain dict: `put` and `fail` are different events -- a pass that
    reached nothing must not erase news that is merely old -- and making them two methods is
    what keeps that distinction from being re-litigated at every call site.
    """

    def __init__(self) -> None:
        self._items: list[dict] = []
        self._at = 0.0            # when the items were measured
        self._notes: list[dict] = []
        self._tried = 0.0         # when a pass last completed, good or bad
        self._error = ""

    def put(self, items: list[dict], notes: list[dict], now: float) -> None:
        self._items, self._notes, self._at, self._tried, self._error = \
            items, notes, now, now, ""

    def fail(self, notes: list[dict], detail: str, now: float) -> None:
        """Record a pass that produced nothing. The previous items survive."""
        self._notes, self._tried, self._error = notes, now, detail

    def get(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        interval = interval_s()
        age = (now - self._at) if self._at else None
        # 1.5 intervals: one refresh may be late without the bar calling itself stale, but a
        # refresh that was missed entirely shows. A flat `age > interval` would flicker stale
        # every cycle, since the refresher sleeps exactly one interval between passes.
        stale = age is not None and age > interval * 1.5
        newest = max((it["at"] for it in self._items if it["at"]), default=0.0)
        return {
            "items": self._items,
            "count": len(self._items),
            "at": round(self._at, 3),
            "age_s": None if age is None else round(age, 1),
            "stale": bool(stale) or not self._items,
            # The oldest thing a visitor can see is the tail of the bar; the newest is what
            # makes "live" true or false. Both are served so the bar can label itself rather
            # than the server deciding for it.
            "newest_at": round(newest, 3),
            "newest_age_s": None if not newest else round(now - newest, 1),
            "interval_s": interval,
            "sources": self._notes,
            "error": self._error,
        }


CACHE = NewsCache()


async def refresh_once() -> None:
    """One pass, off the request path. Never raises.

    The blocking `urllib` work goes through `asyncio.to_thread` for the same reason
    `gateway.refresh_once` does: 28 sequential fetches at up to 12 s each would otherwise
    stall every other request on this process for minutes.
    """
    now = time.time()
    try:
        items, notes = await asyncio.to_thread(collect.collect_all, now)
    except Exception as exc:                        # noqa: BLE001
        CACHE.fail([], f"{type(exc).__name__}: {exc}"[:200], now)
        log.warning("news pass failed before it started: %s", exc)
        return
    ranked = rank.rank(items, now)
    if not ranked:
        # Reached everything and still found nothing worth showing is a real outcome -- every
        # source erroring, or a genuinely empty sweep -- and it must not overwrite good items
        # with an empty bar. The notes say which of the two it was.
        errs = [n["source"] for n in notes if n.get("state") == "error"]
        CACHE.fail(notes, f"no items; {len(errs)} source(s) failing" if errs else "no items",
                   now)
        log.info("news pass produced 0 items from %d raw (%d source errors)",
                 len(items), len(errs))
        return
    CACHE.put(ranked, notes, now)
    log.info("news: %d items from %d raw, %d/%d sources ok", len(ranked), len(items),
             sum(1 for n in notes if n.get("state") == "ok"), len(notes))


async def refresher() -> None:
    """Refresh forever at `interval_s()`. Started from api.py's lifespan when enabled().

    The exception discipline is the gateway's, and it is not decoration: `CancelledError` has
    to propagate or shutdown hangs, while anything else has to be swallowed or one bad night
    on one publisher's CDN silently ends the ticker for as long as the process lives.
    """
    announced = False
    while True:
        try:
            if not announced:
                log.info("news refresher started; interval %.0fs", interval_s())
                announced = True
            await refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception:                           # noqa: BLE001
            log.exception("news refresher iteration failed; continuing")
        await asyncio.sleep(interval_s())
