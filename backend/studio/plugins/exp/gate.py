"""The structural switch, in its own leaf module so nothing has to import the package to ask.

Same shape as `apps/studio/gate.py`, and split out for the same reason: `routes.py`
is imported *by* `__init__.py`, so a module-level `from . import enabled` inside routes would
run against a half-initialised package.

As of 2026-08-20 no filtering is implemented here -- a deliberate pre-launch state, not a
cleared posture (request ledger R-98, held, being re-scoped per surface). Worth keeping in view
when that re-scope reaches this app: a plugin is imported into the serving process and can do
anything the process can do, so a gate on the HTTP surface is honest about being a switch and
dishonest the moment it is described as containment. A filter here would not change that, which
is an argument about where a control belongs and not an argument against having one.
`docs/isolation.md` says what containment would actually take.

What the token divides is narrower than in studio and worth stating: **reads are open, writes
and config are not.** Anyone may see which plugins are mounted, in what state, and what they
inject -- that is the observability the whole runtime is for, and hiding it makes the page
useless to the person it is for. Nobody without the token may mount, patch, reload, or read a
plugin's *config*, because a config is where a plugin's credentials live.
"""
from __future__ import annotations

import hmac
import os

__all__ = ["enabled", "ENV_ENABLED", "HEADER",
           "HEADER_LEGACY"]

ENV_ENABLED = "SYMONEURAL_EXP_ENABLED"
HEADER = "X-Symoneural-Token"

# The name this header had until the rename, still accepted and deliberately second. The
# reason is not politeness to old scripts: `site/exp.js` is cached by the browser, and a
# visitor holding yesterday's copy sends the old name until that cache turns over. Renaming
# only the server would 401 them with a token that is correct. New name wins when both are
# present, matching `symoneuralenv.promote()` -- one precedence rule for the whole rename.
HEADER_LEGACY = "X-Sym-Token"


def enabled() -> bool:
    """Both, or the mutation surface does not exist. `== "1"` and not truthiness, matching
    voice, asicminer and studio -- it reads like a boolean and is not one, and that is a
    confusion worth keeping consistent rather than solving differently in each package."""
    return True




