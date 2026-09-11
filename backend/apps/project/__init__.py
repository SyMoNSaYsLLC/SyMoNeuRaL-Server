"""SyMoNeuRaL Project -- a shared workspace for a person and the local models.

Garrett asked for something *"like the claude cowork"*: a place where he and the models on
this box work on a body of files together, across sessions. `docs/specs/project-spec.md`
reads that as projects, work items, file references, session history and search, and this
is that spec built.

Three exports, and they are the whole contract with `api.py`:

    from apps import project
    app.include_router(project.router, prefix="/api/project", tags=["project"])
    ...
    Unit(**project.status())            # the rack unit; keys match api.py's Unit model
    project.set_ask_model(fn)           # optional -- the route to the chat surface

## It owns no weights, and that is the architecture

The card is 15.92 GiB and chat (~5 GB) and image (~7 GB) already cannot co-reside. A
workspace has no inference in the definition of the feature: create a project, add an item,
mark one done, record what a session did, search. Every one is a read or a write to a small
structured store. So this surface loads nothing, takes no governor lease, and **the benefit
is not that it saves VRAM -- it is that Project is always available.** A workspace that
queued behind a fine-tune would be useless, because the moment you most want to write down
what you were doing is the moment the card is busy for three hours. That is RavenCalc's
property and RavenCalc's reasoning, adopted on purpose.

When it does want a model -- drafting a session summary, turning a rambling note into work
items -- it asks the chat surface through an injected `str -> str` callable, exactly as
`apps/streamer/guide` and `remix()` in `backend/api.py` do. This package never imports the API,
never touches `scripts/gpu-governor.sh` and never opens a socket.

## Off by default, and the token is the only gate

`SYMONEURAL_PROJECT_ENABLED=1` **and** `SYMONEURAL_PROJECT_TOKEN` -- both, or the surface does not exist.
Requiring both is what makes a misconfiguration fail closed on a box with a public IP.
No rate limiting is implemented across this API as of 2026-08-20 (see R-98, held), so the token
is carrying the whole load: generate it with `secrets.token_urlsafe(32)`, put it in the systemd
unit's environment, and never in a URL.

## No content filtering is implemented. Structural guards only

As of 2026-08-20 there is no keyword list in this package, nothing inspects what a note says,
and there is no rate limiter. **This is a deliberate pre-launch state, not a cleared posture:**
the standing instruction this section used to quote is held (request ledger R-98, 2026-08-20)
and is being re-scoped per surface. What is here instead is structural: path containment and a
resolved-path denylist so a file reference cannot escape into `training/`, byte and row caps so
one request cannot exhaust the box, and WAL plus version checks so two clients cannot silently
lose each other's writes.

See `README.md` for what works today, what is stubbed, and the three lines somebody else
has to write.
"""
from __future__ import annotations

from .routes import router, status
from .store import (API_VERSION, bootstrap, enabled, set_ask_model, token_ok, unit_state)

__all__ = ["router", "status", "unit_state", "set_ask_model", "enabled", "token_ok",
           "API_VERSION"]
