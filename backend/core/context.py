"""The runtime objects a router needs but must not import from `server`.

## The cycle this exists to break

`server.py` imports every component's `router`. A router that reached back for
`server.CHAT_MODEL` or `server.gpu` would close the loop, and Python would either fail the
import or hand back a half-initialised module depending on which file got there first --
the second being much worse, because it fails later and somewhere else.

So the shared state lands here. `server.py` calls `configure()` once during startup, and
routers read attributes off `ctx`. Nothing imports `server`.

## Why an attribute bag and not module-level constants

A router imported at module scope would capture whatever the value was at import time.
`CHAT_MODEL` is a path read from config, `gpu` is a queue built during startup, and
`build_status` is a closure over objects that do not exist yet when the routers are first
imported. Reading `ctx.gpu` at call time gets the object that actually exists when the
request arrives; `from core.context import gpu` would get `None` forever.

The cost is that a typo is an AttributeError at request time rather than an ImportError at
startup, so `require()` exists to convert the whole class of mistake back into a startup
failure: `server.py` declares what it promised to provide, and a missing name is loud
immediately instead of on the first request to one route.
"""
from __future__ import annotations

from typing import Any


class _Context:
    """Attribute bag. Reads resolve at call time, which is the whole point."""

    def __getattr__(self, name: str) -> Any:                     # only on a miss
        raise AttributeError(
            f"core.context has no {name!r}. server.py must pass it to configure() before "
            f"any router uses it -- see the module docstring on why this is not an import."
        )


ctx = _Context()


def configure(**values: Any) -> None:
    """Publish runtime objects for the routers. Called once, from `server.py`."""
    ctx.__dict__.update(values)


def require(*names: str) -> None:
    """Fail at STARTUP if something a router needs was never published.

    Without this the failure is an AttributeError on the first request to one route, which
    looks like a bug in that route rather than a missing wire-up in server.py.
    """
    missing = [n for n in names if n not in ctx.__dict__]
    if missing:
        raise RuntimeError(
            f"core.context is missing {missing}: server.py builds the routers before it "
            f"has built these. Move the configure() call above the include_router calls."
        )
