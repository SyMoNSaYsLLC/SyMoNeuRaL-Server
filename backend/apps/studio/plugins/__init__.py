"""The plugin contract: what a package under `backend/apps/studio/plugins/` must export.

Task #73 item 3 (#54). Three packages live here -- `discovery`, `exp`, `reinforce` -- and each
one's own docstring opens by declaring the contract, in three different and mutually
contradicting ways:

* `exp/__init__.py`       -- *"Two exports, and they are the whole contract with `api.py`"*
* `reinforce/__init__.py` -- *"Two exports, and they are the whole contract with `backend/api.py`"*
* `discovery/__init__.py` -- *"Three exports, and they are the whole contract with `api.py`"*

Two, two and three, naming four different sets between them. Nothing checked any of it, so the
contract existed only as prose in the packages it was supposed to constrain -- which is the same
shape as the rack count that read TWELVE in the commit that made it thirteen
(`apps/test_status_rack.py`). This file states it once, and
`apps/studio/test_plugin_contract.py` asserts it against the disk.

## This is a conformance contract, NOT a loader

The obvious next move is to have `api.py` iterate this package and mount whatever it finds.
Deliberately not done, for the same reason the streamer composition refactor was abandoned at
`#73` item 2: `api.py` mounts all thirteen surfaces in one table, each with its own `prefix=`
and `tags=`, and those tags are the OpenAPI groups the rebranded Swagger UI renders. A loop
either flattens them into one group -- changing a visitor-facing page to make an internal check
green -- or carries a per-plugin table of prefix and tags anyway, at which point it is `api.py`'s
table with an extra layer between it and the reader.

There is a second reason, written into `api.py` beside each import: every one of these packages
is bound to the *package* name rather than `from ... import router, status`, because their bare
`enabled`/`status`/`installed` would shadow `api.py`'s own functions of those names. A loader
returning modules keeps that property; a loader returning callables destroys it silently.

So: three hand-written imports and three explicit mounts stay. What this file adds is the
answer to *"what must a fourth package here provide"*, and a test that says whether the three
that exist actually provide it.

## What the three actually export -- read off the disk 2026-08-20, not asserted

                 enabled()  status()  router  token_ok()  LABEL
    exp              y         y        y         y         y
    reinforce        y         y        y         .         .
    discovery        y         y        .         y         .

`enabled()` and `status()` are the only two present on all three, so those two are the whole of
`REQUIRED`. It is tempting to require `router` and `LABEL` as well -- every plugin *should*
have a page and a name -- but `discovery` deliberately has no router (*"the `href` it would
carry has no page behind it, and `apps/voice/__init__.py` is the precedent for what that
costs"*) and `reinforce` deliberately has no `token_ok` at module level. A contract that two of
its three subjects fail on the day it is written is not a contract, it is a wish, and per
`.claude/CLAUDE.md` a check that cannot be true is worse than no check. The optional three are
*recognised* instead: named here so a reader knows they are the intended shape, and pinned by
`OPTIONAL_PRESENT` below so that gaining or losing one is a red test rather than a silent drift.

## The row keys are api.py's, and are deliberately NOT restated here

`status()` must return a mapping that `api.py`'s `Unit` model accepts, and that model's field
list -- including the four legal `state` values and the four legal `bus` values -- is not copied
into this file. A second copy is a second source of truth, and this file would be the stale one.
`test_plugin_contract.py` reads `class Unit` out of `api.py` **as source, via `ast`**, the same
discipline as `apps/test_status_rack.py` and `apps/test_studio_models.py`: importing the serving
module builds every rate limiter, resolves the GPU governor and mounts `site/`.

Why that assertion matters more than it looks: `state` is a `Literal`, so a plugin returning a
fifth value does not get a nicer label, it raises a pydantic error inside `build_status()` and
takes **the whole rack** off the front page. Both `exp` and `discovery` warn about this in their
own docstrings; nothing checked all three at once until now.

## One side effect of this file existing

`apps/studio/plugins/` was a PEP 420 namespace package -- the only gap in a chain that has
`apps/studio/__init__.py` above it and an `__init__.py` in each plugin below it. Adding this
file makes it a regular package, which changes the module name pytest derives for the suite
under `plugins/reinforce/tests/` (that suite is `--ignore`d and needs its own venv; see
`.claude/CLAUDE.md`). The whole-suite count was re-measured across this commit for exactly that
reason rather than assumed unchanged.

Nothing here imports a plugin. `api.py` imports this package's children during startup, and a
parent that eagerly imported all three siblings would drag `discovery` -- which `api.py` does not
mount and does not import -- into the serving process for free. `load()` is explicit and lazy.
"""
from __future__ import annotations

import importlib
from types import ModuleType

__all__ = ["PLUGINS", "REQUIRED", "RECOGNISED", "OPTIONAL_PRESENT",
           "load", "missing", "describe"]

#: The plugin packages, in import order. A new directory here must be added to this tuple --
#: `test_plugin_contract.py` compares it against the directories that actually carry an
#: `__init__.py`, so a fourth plugin cannot arrive unnoticed and unconformant. This is a
#: tripwire in the sense `apps/test_status_rack.py` uses the word: typing the new name is the
#: point, not an obstacle.
PLUGINS = ("discovery", "exp", "reinforce")

#: Present on all three, and therefore the contract. `enabled()` answers whether the surface is
#: switched on; `status()` returns the rack row.
REQUIRED = ("enabled", "status")

#: Recognised, not required -- see the table in the module docstring for who has what and why
#: the gaps are deliberate.
RECOGNISED = ("router", "token_ok", "LABEL")

#: Which plugins carry each recognised-optional export, as read off the disk on 2026-08-20.
#: Pinned rather than computed: if `discovery` gains a router, this goes red and whoever added
#: it updates the map in the same commit -- which is the moment to ask whether the export has
#: become universal enough to move into `REQUIRED`.
OPTIONAL_PRESENT = {
    "router": frozenset({"exp", "reinforce"}),
    "token_ok": frozenset({"discovery", "exp"}),
    "LABEL": frozenset({"exp"}),
}


def load(name: str) -> ModuleType:
    """Import one plugin package by name.

    Only for callers that genuinely do not know the name at write time -- the test below, and a
    future operator tool. `api.py` imports its three by hand on purpose; see the docstring.
    """
    if name not in PLUGINS:
        raise KeyError(f"{name!r} is not one of {PLUGINS} -- add it there first")
    return importlib.import_module(f"{__name__}.{name}")


def missing(mod: ModuleType) -> list[str]:
    """The `REQUIRED` names this module does not resolve, in declaration order.

    `hasattr` rather than a look at `__all__`: `exp` resolves `router` through a PEP 562
    module-level `__getattr__` so that importing the package does not import its routes, and a
    contract that read the list instead of the module would call that a miss.
    """
    return [name for name in REQUIRED if not hasattr(mod, name)]


def describe(name: str) -> dict[str, object]:
    """`{"name", "missing", "optional"}` for one plugin -- what conformance looks like, resolved."""
    mod = load(name)
    return {
        "name": name,
        "missing": missing(mod),
        "optional": sorted(n for n in RECOGNISED if hasattr(mod, n)),
    }
