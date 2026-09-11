"""SyMoNeuRaL Streamer -- the IPTV surface, and the Guide that filters it.

Two units were merged here on Garrett's instruction: *"symon guide and symon tuner should be
migrated together"*, then *"you need to migrate tuner and guide to be 1"*. They had the same
`href` (`/tuner.html`), so the rack was rendering one page twice and the two rows disagreed
with each other. One package, one row, one namespace.

The seam is kept, not dissolved. `routes.py` and the modules beside it are the streaming
half: HLS sessions, playlist parsing, SSRF-pinned fetches. `guide/` is the library half --
matching, clustering, prompt-building -- plus its own thin router. Guide never opens a socket
and owns no weights (see `guide/__init__.py` for why that is the architecture and not a
shortcut), so folding it in costs the streaming half nothing.

Three exports, and they are the whole contract with `api.py`:

    from apps import streamer
    app.include_router(streamer.router,       prefix="/api/streamer")
    app.include_router(streamer.guide_router, prefix="/api/streamer/guide")
    Unit(**streamer.status())                 # the rack unit; keys match api.py's Unit model

There used to be a fourth: `tuner_router` and `tuner_status` were exported alongside `router`
and `status` so that a reader of `api.py` could tell which of the two merged surfaces a line
was wiring. That was the right call while the two were being pulled together and it is the
wrong one now -- the merge is finished, there is one surface, and a `tuner_*` name on it is a
reader promising themselves the old shape is still there. `status()` is the streamer's because
the merged pair is ONE rack row and always was.

Guide is nested at `/api/streamer/guide`, not given a sibling prefix, and not flattened into
the same one: **both routers declare `/state`**, so a shared flat prefix would have had the
second registration shadowed by the first and the guide's capability probe would have started
answering with the streamer's session count. Nesting is what makes the merge safe to mount.

The visitor's playlist and credentials live in their browser and are sent per request; nothing
is written to disk and nothing credential-bearing is logged. A visitor-supplied URL is
validated by `safefetch.validate_url`, which judges the *resolved address* and pins it, and the
pinned address is the only thing ever connected to -- ffmpeg never sees a URL, only `pipe:0`,
which is what keeps the SSRF control real and keeps the credentials out of `argv`.
"""
from __future__ import annotations

from . import guide                                              # noqa: F401
from .guide.routes import router as guide_router
from .routes import router, status

__all__ = ["guide", "guide_router", "router", "status"]
