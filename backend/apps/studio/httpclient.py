"""Facade over the upstream HTTP client (httpx).

This module is the ONLY file in the `studio` package allowed to `import httpx`.
Every other file imports from here. Task #74 item 5: no application module names a
third-party package directly, so the vendor name appears in exactly one file per
dependency and the swap is a one-file change later.

`backend/DEPENDENCIES.md` argues the verdict, and gives a second reason that matters
more than the naming one: outbound HTTP is where an SSRF policy has to live, and a
policy is only a policy if there is one door. `apps/streamer/safefetch.py` is that door
for visitor-supplied URLs today. This module is where a studio-side equivalent would go,
and it cannot be bypassed by a module quietly importing the client itself -- which is
the arrangement being bought here, not tidiness.

**Named `httpclient.py`, not `http.py`, on purpose.** DEPENDENCIES.md says `apps/*/http.py`
and that literal path is a trap: `apps/remix` is a pytest rootdir whose `pythonpath`
includes `"."`, so an `http.py` at a package root shadows the stdlib `http` package for
everything under it -- including httpx itself, which imports `http`. The failure is a
collection error with no obvious cause. `httpclient` collides with nothing under any
rootdir.

**Re-export, do not wrap.** `symbolic.py` wraps sympy's functions because RavenCalc calls
a dozen named functions with stable signatures. `AsyncClient` is a class used as an async
context manager with a wide method surface, and wrapping it would be a second HTTP client
to maintain. The names below are bound to the upstream objects, so an `AsyncClient` built
by a test and injected into a connector is the same object either way.

**Keep this surface complete.** An incomplete facade is not a smaller facade, it is an
import-time `NameError` in whatever imports the missing name -- which is live in this repo
right now: `symbolic.py` does not re-export `convert_xor`, and `apps/ravencalc` has
collected zero tests since `49185b8` as a result. Add the name here rather than reaching
past the module.
"""
from __future__ import annotations

import httpx

# The client. Used as `async with AsyncClient(timeout=...) as c:` throughout.
AsyncClient = httpx.AsyncClient

# Errors, narrowest first. `HTTPStatusError` is what `raise_for_status()` raises and is a
# subclass of `HTTPError`, so an `except HTTPError` after it catches both.
HTTPStatusError = httpx.HTTPStatusError
HTTPError = httpx.HTTPError

# Message types, used in annotations -- which is why a missing one fails at import.
Request = httpx.Request
Response = httpx.Response
QueryParams = httpx.QueryParams
Timeout = httpx.Timeout


def version() -> str:
    """The upstream version, for anything that reports what it is running on."""
    return httpx.__version__
