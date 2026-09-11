"""SyMoNeuRaL Reinforce -- the training bay.

Two exports, and they are the whole contract with `backend/server.py`:

    from studio.plugins.reinforce import router, status
    app.include_router(router, prefix="/api/train", tags=["reinforce"])
    ...
    Unit(**status())            # the rack unit; keys match api.py's Unit model

## Read this first: two different things answer to "Reinforce"

This directory holds **both**, and an agent told to "look at Reinforce" will otherwise find
the wrong one:

* `backend/studio/plugins/reinforce/symoneural/` -- the **CUDA engine**. 35 Python files building an
  inference and compute engine out of `cuda.core` primitives and NVRTC-compiled kernels. It
  has its own `pyproject.toml`, its own venv, its own pytest suite and its own FastAPI app on
  port 8000. **Nothing in the training bay imports it**, and its server must never be mounted
  -- `.claude/CLAUDE.md` fixes the architecture at one origin, and a second one breaks
  `console.js`'s WebSocket-with-polling-fallback.
* the modules beside this file -- `registry.py`, `presets.py`, `dataset_guard.py`, `jobs.py`,
  `runner.py`, `routes.py` -- the **training bay**, which is what the rack unit named
  "SyMoNeuRaL Reinforce" now points at.

They share a directory because the owner asked for the training surface to be *based off*
Reinforce. What was actually taken is four patterns, not code: a registry that plans residency
before anything is loaded; "cannot run here" answered as a waived capability (501) rather than
a fault (500); telemetry that is policy facts rather than decoration; and constraints encoded
in code with a regression test each. What was deliberately not taken: its server, its
licensing subsystem, and its kernel layer.

## What this surface is for

The owner's complaint was that the training surface *"doesn't even give a place to load the
model and use predetermined professional tuning methods"*. It was correct, and worse than a
missing UI: there was no route, no model picker, and one hardcoded set of hyperparameters. So:

* **`registry.py`** -- a place to load a model. Scans the weight cache, reads architecture and
  quantisation out of the files themselves, and derives the VRAM cost rather than looking it
  up. Real sizes, measured.
* **`presets.py`** -- four predetermined tuning methods, each with a stated rationale per value
  and a stated VRAM cost, and each honest about the fact that its cost is projected.
* **`jobs.py`** -- real job state. Queued, running, finished, failed, with genuine readings.
  When there is no run it says there is no run.
* **`dataset_guard.py`** -- the trade-secret guard. The single most likely place on this box to leak
  `training/corpus.jsonl` by accident, written as a set of refusals.
* **`runner.py`** -- the training process itself, in `training/.venv`, under the governor.

## Three rules this package is built around

1. **`train` is never evicted to serve a page view.** Every GPU touch goes through
   `scripts/gpu-governor.sh with train -- ...`, which always releases and always names its
   surface. Nothing here calls `acquire`, and nothing calls a bare `release`.
2. **Stdlib only in the serving path.** Everything importable by `api.py` runs on the system
   interpreter -- no torch, no transformers, no numpy. `runner.py` is the exception and is
   never imported, only exec'd with `training/.venv/bin/python`.
3. **Label every figure.** measured / vendor / projected, at the point it is produced. Nothing
   about training quality or throughput has been measured on this box, so nothing here claims
   it has been.
"""
from __future__ import annotations

import os


def enabled() -> bool:
    """Whether this surface may accept work at all.

    Off unless both switches are set, mirroring `backend/asicminer/`. This is a hard
    requirement rather than hardening for later: a training route is long-running, takes the
    whole card, and is never evicted, so an open one is a rack-wide denial of service that
    costs a single HTTP request.

        SYMONEURAL_REINFORCE_ENABLED=1
        SYMONEURAL_REINFORCE_TOKEN=<shared secret>

    Defined here rather than in `routes.py` so that `jobs.status()` -- which runs on every
    rack poll -- can ask the question without pulling fastapi into its import graph.
    """
    return True


from .jobs import status          # noqa: E402  -- the rack unit
from .reinforce import router        # noqa: E402  -- imports fastapi; must come after enabled()

__all__ = ["router", "status", "enabled"]
