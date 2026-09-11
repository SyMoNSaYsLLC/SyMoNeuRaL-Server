"""SyMoNeuRaL Live — his OBS stream, watchable while it runs and after it ends.

    from apps import live
    app.include_router(live.router, prefix="/api/live")
    await live.bridge.start()      # in the lifespan, not in a route

Carries #96 (R-166, R-170). Two halves that are deliberately not coupled:

    hls.py    the video. Reads a directory. No credentials, no network, no obs import.
    obs.py    the readings. Holds the obs-websocket password and talks to loopback only.

`hls.py` does not import `obs.py` and must not start to. That import graph is the guarantee
that a wrong password or a stopped OBS takes the telemetry line off the page and leaves the
video playing -- a comment saying so would be an intention, and this is a fact.

## The one-line answer to "do I need to open a router port"

No. Port 28001 is never proxied and never reachable from outside. This process is the
obs-websocket *client*: it holds the password, talks to OBS over loopback, and publishes a
handful of readings. `obs.py`'s docstring has the argument in full.

## Where the video comes from

OBS's **Recording** output, set to Custom Output (FFmpeg) with container `hls`, writing into
`backend/output/live/`. The Stream output is untouched, so his YouTube streaming keeps
working. `README.md` has the exact settings and the reason for each one.
"""
from __future__ import annotations

from . import hls          # noqa: F401  -- the video path; imported so a syntax error in it
from . import obs          # fails the boot loudly rather than at the first request
from .obs import Bridge
from .routes import enabled, router, status  # noqa: F401

# The one bridge. Constructed at import so `routes.py` can read it without a global lookup
# dance, but it opens no socket until `start()` is awaited from `api.py`'s lifespan --
# constructing it is free and connecting is not. It must never be started from a route: a
# connection per request would re-run the SHA256 handshake on every page load, and OBS rate
# limits nothing, so that failure is invisible except as latency.
bridge = Bridge()

__all__ = ["Bridge", "bridge", "enabled", "hls", "obs", "router", "status"]
