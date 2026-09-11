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

__all__ = ["enabled", "token_ok", "present_token", "ENV_ENABLED", "HEADER",
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
    return os.environ.get(ENV_ENABLED) == "1"


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


def present_token(headers, query=None) -> str | None:
    """Header, `Authorization: Bearer`, then query string.

    No cookie form, unlike studio's. That one exists because the proxied ComfyUI editor issues
    its own sub-resource requests from inside an iframe and a cookie is the only credential a
    browser attaches to those. Nothing here is framed and nothing here loads sub-resources
    under its own path, so a cookie would be a credential minted for no request -- and one
    scoped, inevitably, more broadly than the single path that justified it.

    The query form has the shape of the same argument and does not survive it. Studio needs one
    because `<img src>` and `new WebSocket()` cannot set a header; nothing here is either, and
    `page.js` sends `X-Symoneural-Token` and only that (`page.js:56`). So this branch is a
    credential channel that is live -- `routes.py:67` and `:81` both hand it `request.query_params` -- and
    that no caller in this repo uses, which means the only way a token arrives here is in a URL,
    where it lands in the access log and in any referrer. Deleting the three lines would be the
    honest end of that reasoning; it is left in place because this pass is correcting claims
    rather than changing what the code accepts, and it is written down here so the next person
    reads it as an open item and not as a channel something depends on.
    """
    # Both spellings, new first. Both cases of each, because this is handed a plain dict by
    # the tests as often as a case-insensitive Starlette `Headers`.
    for key in (HEADER, HEADER.lower(), HEADER_LEGACY, HEADER_LEGACY.lower()):
        value = headers.get(key)
        if value:
            return value
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if query is not None:
        found = query.get("token")
        if found:
            return found
    return None
