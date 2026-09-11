"""The structural switch, in its own module so nothing has to import the package to ask.

`__init__.py` re-exports these and `routes.py` imports them directly. Splitting them out is
not decoration: `routes.py` is imported *by* `__init__.py`, so a module-level
`from . import enabled` inside routes would run against a half-initialised package. One tiny
leaf module removes the cycle instead of hiding it behind a function-local import.

As of 2026-08-20 no content filtering and no allow-list are implemented here. That is a
deliberate pre-launch state, not a cleared posture: the standing instruction this used to cite
is **held** (request ledger R-98, 2026-08-20) pending re-scope per surface, so read the
sentence above as a description of what the code does today and not as authority to remove a
control or to leave one out. This module is the same on/off switch `apps/voice` and
`apps/asicminer` already put on write-capable surfaces, and nothing more: with both variables
set, every tool runs unrestricted.
"""
from __future__ import annotations

import hmac
import os

__all__ = ["enabled", "switched_on", "token_ok", "present_token", "local_request",
           "local_bypass",
           "ENV_ENABLED", "ENV_LOCAL_BYPASS", "HEADER",
           "HEADER_LEGACY", "COOKIE", "COOKIE_LEGACY", "COOKIE_PATH",
           "LOCAL_PEERS", "PROXY_HEADERS"]

ENV_ENABLED = "SYMONEURAL_STUDIO_ENABLED"

# The local-only development bypass. Narrow on purpose: it is read by `local_bypass()` and by
# nothing else, it is spelled for one surface rather than for the box, and it is OFF unless it
# is exactly "1". It does NOT exist to weaken the public gate -- see `local_bypass`.
ENV_LOCAL_BYPASS = "SYMONEURAL_STUDIO_LOCAL_BYPASS"
HEADER = "X-Symoneural-Token"

# The name this header had until the rename, still accepted and deliberately second. Not
# politeness to old scripts: `site/studio.js` is cached by the browser, so a visitor holding
# yesterday's copy sends the old name until that cache turns over, and renaming only the
# server would 401 them while their token is correct. New name wins when both are present,
# matching `symoneuralenv.promote()` -- one precedence rule for the whole rename.
HEADER_LEGACY = "X-Sym-Token"

# Only the proxied editor uses this, and only under its own path. See `present_token`.
COOKIE = "symoneural_studio"

# And the legacy cookie has a sharper reason to be read than the legacy header does. This one
# is minted by `routes.editor` on a request the operator already made, so a tab that is open
# right now is holding `sym_studio` and will keep sending it: the editor's sub-resource
# requests are the ONLY thing that credential exists for, and they carry no header and no
# query string to fall back on (see `present_token`). Reading one name and minting the other
# would break the framed editor for every open session at the moment of deploy -- which is
# exactly the seven-aborted-requests failure `tests/studio.mjs` was written to catch. Read
# both, mint only `COOKIE`, so an open session heals on its next entry-document load.
COOKIE_LEGACY = "sym_studio"
COOKIE_PATH = "/studio/editor"


def switched_on() -> bool:
    """The structural switch ALONE -- is Studio meant to exist at all -- with no token involved.

    Split out 2026-08-22 so the #88 local bypass can say what it means. `enabled()` is two
    conditions wearing one name, and the bypass has to satisfy one of them and skip the other:
    it may drop the SECRET, it must never drop the SWITCH. Reading `enabled()` there would have
    left the friction in place (you would still need a token for it to be true), and reading
    the raw environment there would have hidden the invariant in a string comparison. This is
    the invariant, named.

    `== "1"` and not truthiness, matching voice and asicminer.
    """
    return os.environ.get(ENV_ENABLED) == "1"


def enabled() -> bool:
    """The switch alone. The token half is gone.

    This docstring used to say "the `and` is still here", and it is not. Studio's token was
    described as "the whole boundary in front of run_command" -- that boundary is now the
    fact that nothing off this box can reach the route, not a shared secret.
    """
    # NO API KEYS. Owner decision, 2026-09-11: "no api keys period -- everything is
    # straight post get fetch". Single-operator box, not reachable from the internet.
    # Removed rather than made optional: an optional gate is one somebody re-enables
    # by accident.
    return switched_on()


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

def present_token(headers, query, cookies=None) -> str | None:
    """Pull the token out of a request: header, then query string, then cookie.

    The query-string form exists because two real browser contexts cannot set a header:
    `<img src="/api/studio/image?...">` and `new WebSocket(...)`. Refusing to accept it there
    would not make the surface safer, it would make images and live progress impossible.

    The cookie form exists for exactly one thing, and an earlier version of this docstring
    said it was "worse" than the query string, which was written before the editor was framed
    and turned out to be a claim about a situation that does not arise. The proxied ComfyUI
    editor at `/studio/editor/` loads its own assets by *relative* URL -- `assets/index-*.js`,
    `materialdesignicons.min.css`, `api/userdata/user.css` -- from inside an iframe. Those
    requests carry no header (no JavaScript of ours issues them) and no query string (the
    token was on the iframe's URL, not on theirs), so every one of them 401'd and the editor
    never booted. That is not hypothetical either: it is what `tests/studio.mjs` reported,
    seven aborted requests and a timeout waiting for the canvas.

    A cookie is the only mechanism a browser applies to sub-resource requests it issues on its
    own. It is minted by `routes.editor` on the entry document, scoped to `COOKIE_PATH` so it
    is never sent to `/api/studio` or to any other part of the site, `SameSite=Strict`, and
    given no expiry so it dies with the tab -- the same lifetime as the `sessionStorage` copy
    the page holds.

    It is also `HttpOnly`, and that flag wants stating narrowly: it keeps *this copy* out of
    `document.cookie` and it protects nothing about the token itself. The same secret is on the
    iframe's own URL -- `page.js:373` sets `frame.src = '/studio/editor/?token=' + token()` --
    so it sits in `location.search` of the framed document, readable by any script ComfyUI
    loads there, its own frontend bundle and any custom node alike. `page.js:274` puts it on
    image URLs the same way, and the page holds a copy in `sessionStorage` besides. Anything
    that can run script in either document already has the operator token. `HttpOnly` is
    hygiene on one copy of several, not a boundary, and this docstring read as though it were.
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
    if cookies:
        for name in (COOKIE, COOKIE_LEGACY):
            found = cookies.get(name)
            if found:
                return found
    return None


# ---------------------------------------------------------------------------------------
# the local-only development bypass
# ---------------------------------------------------------------------------------------
# Added 2026-08-22 as the chosen resolution of #88 / SECURITY-AUDIT BLOCKER-1. The complaint
# it answers is real: Studio answers 503 unless both variables are set, so Garrett could not
# open his own surface without first exporting a secret. The naive fix -- drop the token --
# would have published ComfyUI's own editor to the internet, because `ops/Caddyfile` delegates
# `/studio` AND `/studio/*`, and `/studio/editor/*` proxies that editor with a catch-all over
# seven methods plus a WebSocket. So the friction comes off the LOCAL path only.
#
# Copied in shape, deliberately, from `api.py::_require_local`, which is the strictest local
# test in this repo. Not imported from there: `api.py` imports this package, so the dependency
# would be a cycle. The values are duplicated and that duplication is the point -- two
# hand-maintained copies of a security constant, each with a test, beats one copy that a
# refactor can widen for both at once.

# Loopback only. `localhost` is here because a `TestClient` peer is not always numeric.
LOCAL_PEERS = ("127.0.0.1", "::1", "localhost")

# The belt to the peer check's braces. Caddy sets these on everything it proxies, so their
# presence means the request crossed the reverse proxy even when the socket claims loopback --
# which is exactly what a future `handle /studio*` change would produce, and exactly the case
# the peer check alone would wave through.
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-real-ip")


def local_request(peer: str | None, headers) -> bool:
    """True only for a request that came from a process on this machine and did not cross a proxy.

    Two conditions and both must hold, for the reason `_require_local` gives: the peer address
    is the real check, and the forwarded headers catch the case where the socket says loopback
    because a reverse proxy is the one connecting.

    `headers` may be a plain dict or a Starlette `Headers`; both spellings of each name are
    tried, because a dict is case-sensitive and `Headers` is not.
    """
    if (peer or "") not in LOCAL_PEERS:
        return False
    for name in PROXY_HEADERS:
        if headers is None:
            break
        if name in headers or name.title() in headers:
            return False
    return True


def local_bypass(peer: str | None, headers) -> bool:
    """True when this request may skip the token -- local, explicitly switched on, off by default.

    THREE conditions, all required:

      1. `SYMONEURAL_STUDIO_LOCAL_BYPASS == "1"`  -- absent means no bypass, which is the default
      2. `switched_on()`                          -- **Studio is still deliberately switched on**
      3. `local_request(peer, headers)`           -- loopback, and not through a proxy

    **The invariant, stated once: this bypasses token friction and NEVER the disabled state.**
    A Studio that is switched off denies every caller, local or not, bypass flag or not --
    condition 2 is what guarantees it, and `test_disabled_studio_refuses_even_with_the_bypass`
    is what proves it. `local_bypass()` is not a master allow switch and must never become one.

    **What this does not do, and each omission is load-bearing:**

    It does not touch `enabled()`. A public request still meets the unchanged
    `enabled()` + `token_ok()` pair, so with no token configured the public answer is 503 and
    with one configured it is 401 -- both exactly as before. The bypass can only ever make the
    LOCAL path easier; there is no argument to it that makes the public path easier.

    It calls `switched_on()` rather than `enabled()`, and that is the whole point of the
    function. `enabled()` is the switch AND a non-empty token, so calling it here would leave
    the friction exactly where it was -- the operator would still have to invent a secret to
    get past it. Condition 2 keeps the deliberate on/off switch and drops only the secret.

    It is spelled for Studio alone. Miner, ASIC, Project, Coder, Exp, Reinforce and Discovery
    each keep their own gate untouched, and no token variable is removed or shared.
    """
    if os.environ.get(ENV_LOCAL_BYPASS) != "1":
        return False
    if not switched_on():                       # never bypass the disabled state
        return False
    return local_request(peer, headers)
