"""symoneural-capture -- the shared distill store the data pump writes into.

    from capture import CaptureStore
    captures = CaptureStore(settings.capture_dir)
    captures.capture("dj", messages, verdict={"added": 27}, meta={"job_id": "j1"})

Every surface that produces a commercially-clean model turn banks it here, so that normal
use of the product accumulates training material without anyone running a scrape.
`symoneural_dj` was the first caller; the contract is deliberately small enough that the
next one does not need to read this file.

WHY THIS PACKAGE EXISTS AS A PACKAGE

It did not exist. `symoneural_dj/app.py` imported `symon_capture`, which was an editable
install whose finder mapped to `/home/google/AI_Local_NVIDIA` -- a directory that no longer
exists. So `import symon_capture` failed on every interpreter on this box, `symoneural_dj.app`
could not be imported at all, and `apps/remix/tests` was excluded from the pytest run
*because of that failure*. The exclusion read as a policy decision about per-project suites.
It was a missing dependency wearing a policy's clothes.

WHY IT IS `apps/capture` AND NOT `apps/symon_capture`

The convention: one version of an application, at `backend/<name>`, where `<name>` is
the display name minus the `symoneural-` prefix. It shows on the live stack as
`symoneural-capture`. The old import name `symon_capture` was a third spelling of a prefix
that already had two, which is how a directory ends up holding the same idea twice.

STDLIB ONLY, AND THAT IS A REQUIREMENT RATHER THAN A PREFERENCE

The serving path is the system interpreter (see `.claude/CLAUDE.md`, *Python environments*:
fastapi, uvicorn, pydantic and sympy are OS packages and nothing may be pip-installed there).
A capture store that needed a wheel would be a capture store that could not run in the place
it is called from. `apps/accounts` reached the same conclusion independently and says so at
length; this package simply needs less to do it.

WHAT IS WRITTEN, AND WHAT IS NOT

One JSON object per line, appended to `<root>/<app>/<UTC date>.jsonl`. The record carries the
messages, the verdict and the caller's metadata verbatim. It does NOT carry a source field:
`provenance.py` was deleted 2026-08-11, and recording an unverified provenance string is worse
than recording none -- it reads as a checked claim. What the turns actually are is a property
of the calling code, and belongs in that code's documentation rather than in a field nothing
validates.

The directory is created 0700 and files 0600. Captured turns are prompts and model output tied
to an account id; they are not world-readable by accident.
"""
from __future__ import annotations

from .store import CaptureError, CaptureStore

__all__ = ["CaptureStore", "CaptureError"]
__version__ = "0.1.0"
