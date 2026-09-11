"""One pass: fetch every enabled source and every query, parse, and report what failed.

This is the blocking half of the package. `__init__.refresh_once` calls `collect_all` inside
`asyncio.to_thread`, exactly as `apps/gateway` calls `chain.probe`, so nothing here needs to
know about the event loop and nothing here may block it.

The failure model is per source, and it is the reason this function returns notes alongside
items. A pass that reached eight of eleven feeds is a good pass -- publishers rate-limit, DNS
blips, GitHub 503s -- and collapsing that into a single boolean would either throw away a
whole bar's worth of real news or claim a full sweep that did not happen. `routes.py` serves
the notes, so the operator can see which source is failing without reading a log.
"""
from __future__ import annotations

import os
import time
from urllib.parse import quote

from . import feeds, fetch
from .parse import Item, parse_feed

# The operator's levers. Queries are settable; URLs are not -- see feeds.py for why.
ENV_OFF = "SYMONEURAL_NEWS_OFF"          # comma-separated source names to skip
ENV_QUERIES = "SYMONEURAL_NEWS_QUERIES"  # comma-separated query strings

MAX_QUERIES = 8       # bounds a pass: 10 sources + 8 queries x 3 engines = 34 fetches.
                      # The 8 is the ceiling on an env-supplied query list, not the default
                      # count -- DEFAULT_QUERIES is 6, so a default pass is 28. Both figures
                      # are recomputed from the tuples by test_news.py rather than trusted
                      # here; this comment said 32 over 8 sources after the list grew to 10.
MAX_QUERY_LEN = 120   # a search phrase, not a payload


def disabled() -> frozenset[str]:
    raw = os.environ.get(ENV_OFF, "")
    return frozenset(name.strip().lower() for name in raw.split(",") if name.strip())


def queries() -> tuple[str, ...]:
    """The search phrases for this pass, sanitised.

    A query is a string, not a URL, and `fetch.check_host` re-validates the formatted result
    anyway -- but a query still gets trimmed and capped here, because an unbounded operator
    string interpolated into a URL is how a query becomes a request for something other than
    news. Characters are not filtered: `quote` encodes them, which is the correct handling and
    does not silently change what was asked for.
    """
    raw = os.environ.get(ENV_QUERIES)
    if raw is None:
        return feeds.DEFAULT_QUERIES
    out = []
    for part in raw.split(","):
        part = " ".join(part.split())[:MAX_QUERY_LEN]
        if part:
            out.append(part)
    return tuple(out[:MAX_QUERIES]) or feeds.DEFAULT_QUERIES


def search_url(template: str, query: str) -> str:
    """Format one search URL and prove its host before returning it.

    `quote(safe="")` encodes `/ : ? & #` as well as spaces, so a query cannot terminate the
    parameter and append its own. The `check_host` call is belt and braces on top of that: it
    is what makes the property testable in one line rather than argued about.
    """
    url = template.format(q=quote(query, safe=""))
    fetch.check_host(url)
    return url


def collect_all(now: float | None = None) -> tuple[list[Item], list[dict]]:
    """Fetch everything enabled. Returns (items, notes). Never raises.

    Never raises is a promise this function keeps for `refresh_once`, which is a task on the
    serving event loop: an exception escaping a `create_task` is logged and swallowed by
    asyncio, so the refresher would look alive while doing nothing.
    """
    now = time.time() if now is None else now
    off = disabled()
    items: list[Item] = []
    notes: list[dict] = []

    for src in feeds.SOURCES:
        if src.name.lower() in off:
            notes.append({"source": src.name, "state": "off"})
            continue
        started = time.monotonic()
        try:
            body = fetch.get(src.url)
            got = parse_feed(body, src.name, src.topic, src.weight)
        except Exception as exc:                    # noqa: BLE001 -- see docstring
            notes.append({"source": src.name, "state": "error",
                          "detail": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        items.extend(got)
        notes.append({"source": src.name, "state": "ok", "items": len(got),
                      "took_s": round(time.monotonic() - started, 3)})

    for eng in feeds.SEARCHES:
        if eng.name.lower() in off:
            notes.append({"source": f"{eng.name} search", "state": "off"})
            continue
        found = 0
        failed = []
        started = time.monotonic()
        for query in queries():
            try:
                body = fetch.get(search_url(eng.template, query))
                got = parse_feed(body, eng.name, eng.topic, eng.weight,
                                 credit_from_title=True)
            except Exception as exc:                # noqa: BLE001
                failed.append(f"{query}: {type(exc).__name__}")
                continue
            items.extend(got)
            found += len(got)
        note = {"source": f"{eng.name} search", "state": "ok" if found else "error",
                "items": found, "took_s": round(time.monotonic() - started, 3)}
        if failed:
            note["detail"] = "; ".join(failed)[:200]
        notes.append(note)

    return items, notes
