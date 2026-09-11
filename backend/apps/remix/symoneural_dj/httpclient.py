"""Facade over the upstream HTTP client (httpx).

This module is the ONLY file in the `symoneural_dj` package allowed to `import httpx`.
Every other file imports from here. Task #74 item 5, and `backend/DEPENDENCIES.md` has
the argument: one door out, so an SSRF policy cannot be bypassed by importing the client
directly, and the vendor name in one file per package so a swap is a one-file change.

**Why remix carries its own rather than importing studio's.** `apps/remix` is a separate
application with its own `pyproject.toml` and its own pytest rootdir; `apps.studio` is a
sibling, not a library it depends on. Reaching across would couple two applications
through their vendor plumbing, which is the coupling this module exists to remove. The
two files are near-identical and that is the correct amount of duplication: each package
swaps independently.

**Named `httpclient.py`, not `http.py`, on purpose.** `pyproject.toml` sets
`pythonpath = [".", "../.."]`, so `apps/remix` is a `sys.path` root -- an `http.py` there
would shadow the stdlib `http` package for everything under this rootdir, httpx included.
This file sits a level down inside the package, where that is already not true, but the
name is chosen so moving it up cannot reintroduce it.

**Re-export, do not wrap.** The tests inject their own client
(`tests/conftest.py` builds `AsyncClient(transport=MockTransport(...))` and hands it to
`SpotifyClient`), and these names are bound to the upstream objects, so an injected client
is the same object on both sides. Test code keeps importing httpx directly and
DEPENDENCIES.md marks that **Keep**: a test is not a shipped module, and the point of the
facade is the swap, not the spelling.

**Keep this surface complete.** An incomplete facade is an import-time `NameError` in the
consumer, not a smaller facade -- `symbolic.py`'s missing `convert_xor` re-export has had
`apps/ravencalc` collecting zero tests since `49185b8`. Add the name here rather than
reaching past the module.
"""
from __future__ import annotations

import httpx

# The client. Connectors accept one so tests can inject a MockTransport-backed instance.
AsyncClient = httpx.AsyncClient

# Errors, narrowest first: `HTTPStatusError` is a subclass of `HTTPError`.
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
