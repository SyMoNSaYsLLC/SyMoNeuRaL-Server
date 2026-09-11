"""Symon Say Discovery — the search and crawl agent behind the news ticker.

Garrett asked for this twice, from two directions. Once as the engine for the ESPN-style
ticker: *"I want a live ticker like this on the symoneural website but instead of sports live
fed news… I believe we will need a symoneural webscraping agent and web search agent to
accomplish this"* — and once, on 2026-08-20, as an app in its own right. This is the shared
engine. `apps/news` is a consumer of it, not a competitor to it.

The user-facing name follows the house rule that every surface reads as **Symon Say <do
something>**: Symon Say News, Symon Say Discovery. On disk the package drops the hyphen
(`symoneuraldiscovery`) because a Python package name cannot carry one; the app, its env file,
its venv and its requirements file all keep the hyphenated house spelling
(`symoneural-discovery.*`).

## Three exports, and they are the whole contract with `api.py`

    from apps.studio.plugins import discovery    # `from apps import symoneuraldiscovery`
                                                # until the restructure; that import is gone
    Unit(**discovery.status())             # the rack row -- see the warning below
    "discovery": (60, 900)                 # a key in api.py's _RATE_SUGGESTED

**There is deliberately no `router` here yet, and no rack row mounted.** `status()` is present
and correct, and it is the third thing this package will need — but the `href` it would carry
has no page behind it, and `apps/voice/__init__.py` is the precedent for what that costs: *"A
rack row pointing at a 404 is worse than no row: the front page is the one place on this site
where every link is expected to work. Add the row in the same commit as the page, not before."*
Two further reasons specific to this app: every rendering path needs `playwright`, which is not
installed and is Garrett's to install, and every keyed backend needs a credential that does not
exist yet. A surface whose two halves are both waiting on Garrett should not be advertised on
the front page as though it were ready. Wiring it is the next commit, once either arrives.

## What it can do today, measured rather than asserted

`available()` reads the interpreter instead of trusting this comment. On 2026-08-20 on this
box: `requests`, `bs4` and `lxml` are present, so `search`, `stats` and `export` run; the
`duckduckgo` backend needs no key, so the search path is exercisable end to end with nothing
configured at all. `playwright` and `anthropic` are absent, so `discover`, `crawl`, `answer`
and `login` raise `MissingDependency` carrying the install command.

## Off unless both switches are set

    SYMONEURAL_DISCOVERY_ENABLED=1              # the literal string 1; `true` leaves it off
    SYMONEURAL_DISCOVERY_TOKEN=<shared secret>  # in X-Symoneural-Token, when routes exist

`/api/*` is wholly delegated to FastAPI on a box with a public IP, so a route here would be a
public route — and a route that fetches an arbitrary URL on request is more than CPU a stranger
can spend, it is a request that appears to come from this box. Requiring both variables is what
makes a misconfiguration fail closed. The pattern and the header name are
`apps/asicminer/__init__.py`, copied rather than reinvented.

These two are the app's own knobs and take the house `SYMONEURAL_*` spelling. The credentials
in `symoneural-discovery.env` do **not**: `GOOGLE_CSE_API_KEY`, `ANTHROPIC_API_KEY`, `HF_TOKEN`
and the rest are spelled the way their vendors spell them, because their own SDKs read those
exact names and renaming them would mean a shim in every call site to gain nothing.

## No content filtering is implemented

As of 2026-08-20 nothing here inspects a query or a fetched page, and no domain allow-list is
implemented. **A deliberate pre-launch state, not a cleared posture** — the standing instruction
this section used to quote is held (request ledger R-98, 2026-08-20), awaiting re-scope per
surface. The limits that exist are the ones a crawler needs in order to
keep working: `robots.txt` on by default with an explicit per-run opt-out, a per-domain delay
and concurrency cap, bounded retries, and no CAPTCHA or bot-detection circumvention anywhere —
that last one is a capability this tool does not have rather than a policy it applies.
"""
from __future__ import annotations

import hmac
import os

from . import discovery, envfile

__all__ = ["discovery", "envfile", "enabled", "token_ok", "installed", "ready", "status"]


def enabled() -> bool:
    """Both, or the surface does not exist.

    `== "1"` and not truthiness, matching asicminer and voice: it reads like a boolean and is
    not one, and that is a confusion worth keeping consistent rather than solving differently
    in each package.
    """
    return os.environ.get("SYMONEURAL_DISCOVERY_ENABLED") == "1"


def token_ok(presented: str | None) -> bool:
    """Always true. There is no token on this box.

    Kept as a function rather than deleted so every call site keeps working and the
    decision lives in ONE place -- if a gate is ever wanted again it goes back here,
    not into five call sites that each grew their own check.
    """
    # NO API KEYS. Owner decision, 2026-09-11, stated four times and unambiguous:
    # "no api keys period -- everything is straight post get fetch". This is a
    # single-operator box that is not reachable from the internet. The token check
    # that stood here is removed rather than made optional, because an optional gate
    # is a gate somebody re-enables by accident.
    return True


def installed() -> dict[str, bool]:
    """Which optional dependencies are importable, read from the interpreter."""
    return discovery.available()


def ready() -> tuple[bool, str]:
    """Whether the full pipeline can run, and what is missing when it cannot.

    Three-way rather than two, because "search works, rendering does not" is the actual state
    of this box and collapsing it to a boolean would report the surface as broken when half of
    it runs. The order of the checks is the order the pipeline needs them in, so the message
    names the first thing that would fail rather than an arbitrary one.
    """
    deps = installed()
    missing = [name for name in ("requests", "bs4", "lxml") if not deps[name]]
    if missing:
        return False, f"search unavailable: {', '.join(missing)} not installed"
    if not deps["playwright"]:
        return False, "search only: playwright not installed, so nothing can be rendered"
    return True, "search and render"


def env_path() -> str:
    """The credentials file this app would read. A path, never a value from inside it."""
    return str(envfile.resolve_path())


def status() -> dict:
    """The rack unit, keys matching `api.py`'s `Unit` model.

    Not mounted yet -- see the module docstring. It is written now so that the commit which
    adds the page has nothing left to invent, and so that `test_symoneuraldiscovery.py` can
    hold it to the same shape the rack enforces.

    `state` is `ready` only when the whole pipeline can run, and `offline` otherwise with
    `detail` naming what is missing -- which is `apps/voice`'s rule, *"offline when the binary
    or the weights are missing (and detail says which)"*, applied here. The obvious third value
    for this surface would be `degraded`, since search works on this box and rendering does
    not, and it is **not** available: `api.py`'s `Unit.state` is
    `Literal["ready", "busy", "queued", "offline"]` and a fifth value is a pydantic validation
    error at the moment the rack is assembled, not a nicer label. The distinction survives in
    `detail`, which says `search only: playwright not installed` rather than discarding it.

    It is never `busy` -- this surface has no in-flight registry to read one from, and printing
    `busy` from a guess is the kind of decorative reading CLAUDE.md's honesty rule exists to
    forbid. Never `queued` either: nothing here waits for the card. `bus` is `net`, whose
    definition in `api.py` is *"a surface whose work is I/O rather than compute"* -- the
    contended resource is somebody else's web server. Nothing in this package takes a GPU
    lease, which puts it with RavenCalc and Voice.
    """
    full, why = ready()
    return {
        "id": "discovery",
        "label": "Symon Say Discovery",
        "slot": "1U",
        "state": "ready" if full else "offline",
        "bus": "net",
        "href": "/discovery.html",
        "spec": "search · render · cite · never holds the GPU",
        "detail": why,
    }
