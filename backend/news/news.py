"""The ticker's HTTP surface: one read-only endpoint that serves the cache.

    import news
    app.include_router(news.router, prefix="/api/news")   # before the static mount

## Three properties, all deliberate

**It never triggers a fetch.** It returns whatever the background refresher last measured.
`apps/gateway/routes.py` states the reason and it applies here with more force, since this
package reaches eight hosts rather than one: an endpoint that fetched on demand would be an
unauthenticated outbound-request trigger on a public-facing box, and anyone able to reach
`/api/news/ticker` could make this machine fetch thirty-two third-party feeds as fast as they
could type. The refresher owns the rate.

**It carries no token, and needs none.** Everything it returns is already public: headlines
and links that eight publishers hand to anyone who asks. There is no key material anywhere in
this package to leak.

**It answers 200 with an empty bar rather than 503 when the surface is off.** This is the one
place it departs from the gateway, and the reason is that the caller is not an operator, it is
`site/ui.js` on every page load. A 503 for the normal, expected, default state of the box
would put a red line in every visitor's console and in the access log, and would make a real
outage indistinguishable from "not switched on". `enabled: false` with no items says the same
thing in the response body, and the bar renders nothing either way.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/ticker", summary="The headlines the news refresher last collected")
def ticker() -> dict:
    """The bar's payload: items, how old they are, and which sources are failing.

    The imports are function-local for the same reason the gateway's are: `__init__.py`
    imports this module while it is still executing, so these names do not exist yet at
    import time. By the time a request arrives the package is fully initialised.
    """
    from . import CACHE, enabled

    got = CACHE.get()
    if not enabled():
        # Not an error, and not silence either. An operator reading this can tell the
        # difference between "off" and "on but every publisher is down"; a visitor's browser
        # sees an empty list and draws nothing.
        return {"enabled": False, "items": [], "count": 0, "stale": True,
                "age_s": None, "newest_age_s": None,
                "detail": "news surface is off — set SYMONEURAL_NEWS_ENABLED=1 and restart"}
    got["enabled"] = True
    return got
