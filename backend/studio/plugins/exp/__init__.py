"""SyMoNeuRaL Exp -- the plugin runtime this stack's next layer is built on.

Two exports, and they are the whole contract with `api.py`. The contract that binds all
three plugins here -- and what each one is and is not required to provide -- is stated once in
`apps/studio/plugins/__init__.py` and asserted by `apps/studio/test_plugin_contract.py`; this
package is the only one of the three that provides every recognised export:

    from studio.plugins import exp      # `from apps import symoneuralexp as exp` until
                                             # the restructure; that import no longer exists
    app.include_router(exp.router, prefix="/api/exp", tags=["exp"])     # before the static mount
    Unit(**exp.status())        # the rack row -- page first, same rule as voice and studio

## What this is

Every other app in `backend/` is a *capability*: chat, image, remix, reinforce, studio.
This one is the thing capabilities get mounted *into*. It is a service container with a
lifecycle -- declare what you need, get it when it exists, be taken down cleanly when it goes
away, be reloadable while the process keeps running.

| Module | Does |
|---|---|
| `context.py` | the container: services, events, `provide`/`inject`/`isolate`/`intercept` |
| `fiber.py`   | one mounted plugin instance -- states, effects, reverse teardown, rebind |
| `registry.py`| what counts as a plugin, and config validation |
| `loader.py`  | YAML manifests, presets, groups, hot-plug, hot-reload |
| `trace.py`   | the append-only record everything else is debugged from |
| `plugins/`   | one worked example per shape and per mechanism |
| `presets/`   | `dev`, `sessions`, `failures` -- manifests you can mount and read |

The design is Cordis's, ported rather than copied: `docs/architecture.md` says which ideas were
taken, which were left, and why. Nothing is vendored and there is no npm anywhere near it.

## Why it exists

Because it is the layer under the interesting work rather than the interesting work itself.
Everything above it -- an agent that gains a tool at runtime, a session that forks its own model
without disturbing the process-wide one, a UI that reloads its own plugin while a render is in
flight -- is easy once this exists and is a rewrite of the process every time it does not.
`docs/architecture.md` closes with the plateau argument in full.

## The gate

Reads are open; mounting, patching, reloading and reading a plugin's *config* need
`SYMONEURAL_EXP_ENABLED=1` and `SYMONEURAL_EXP_TOKEN=<secret>`. See `gate.py` for why that line, and
`docs/isolation.md` for why none of it is a sandbox.
"""
from __future__ import annotations

import os

from .gate import ENV_ENABLED, enabled, token_ok  # noqa: F401

__all__ = ["router", "enabled", "token_ok", "status", "runtime", "LABEL",
           "DEFAULT_PRESET", "default_preset"]

LABEL = "SyMoNeuRaL Exp"

ENV_PRESET = "SYMONEURAL_EXP_PRESET"

#: The value of `SYMONEURAL_EXP_PRESET` **at import**, kept because `__all__` exports it and the page
#: shows it. Read `default_preset()` instead of this if you care about the current environment:
#: `api.py` imports this package during startup, so a variable set after that -- by a test, by
#: `systemctl set-environment`, by anything in-process -- would never be seen here.
DEFAULT_PRESET = os.environ.get(ENV_PRESET, "dev")

_LOADER = None
_BOOTED = False
_BOOT_LOCK = None


def default_preset() -> str:
    """The preset `boot()` will mount, read now rather than at import.

    `""` means mount nothing at all, which is the setting for a process that wants the API
    surface and will supply its own manifest.
    """
    value = os.environ.get(ENV_PRESET)
    return DEFAULT_PRESET if value is None else value


def __getattr__(name: str):
    """`router` is imported on first access, not at package import (PEP 562).

    The same reason as studio's: `mod.py` imports FastAPI, and the runtime modules under it
    import nothing outside the standard library. That is not a stylistic constraint -- it is
    what lets `python3 -m studio.plugins.exp.cli` and the test file run under a bare interpreter,
    and what keeps a missing FastAPI or a missing PyYAML from turning into an aborted pytest
    *collection* rather than one failed test.

    `api.py` touches `exp.router` during startup, so a syntax error in `mod.py` still fails
    the boot loudly. Nothing is deferred that anybody was relying on to fail early.
    """
    if name == "router":
        import importlib
        mod = importlib.import_module(".router", __name__)
        return getattr(mod, 'router')
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def runtime():
    """The process-wide `Loader`, created on first call.

    One per process, deliberately. A second container would mean two `bus` services under one
    name with nothing to tell them apart, which is the confusion `isolate()` exists to make
    explicit -- fork a realm, do not fork the container.

    Creating it does not mount anything. `boot()` does that, and `mod.py` calls it on the
    first request rather than at import, so importing this package never starts a plugin.
    """
    global _LOADER
    if _LOADER is None:
        from .loader import Loader
        from .trace import Trace  # noqa: F401  -- imported so a broken trace fails here
        _LOADER = Loader(trace_path=_trace_path())
    return _LOADER


def _trace_path():
    """`run/exp-events.jsonl`, beside the pidfiles and the GPU lock.

    `run/` is runtime state, which this is: a ring of what the container did, not a log anything
    should rotate. Returns `None` if the directory is not there, because a trace file is worth
    having and not worth failing a boot over.
    """
    import pathlib
    run = pathlib.Path(__file__).resolve().parents[2] / "run"
    return run / "exp-events.jsonl" if run.is_dir() else None


async def boot(preset: str | None = None):
    """Mount the default preset once. Idempotent -- a second call is a no-op, not a re-apply.

    Re-applying would be *almost* harmless, because `Loader.apply` diffs, but "almost" is doing
    real work there: two applies interleaved on one runtime means the second diffs against a
    half-built entry list.

    Two things make this actually idempotent rather than nearly so. The flag is its own
    module-level boolean and not `loader.source`, because `apply` sets `source` *after* the
    awaits this is meant to serialise -- so two concurrent first requests both saw `None` and
    both applied -- and because `source` is `None` for a dict manifest, which made this re-run
    after any `POST /apply`. The lock covers the await itself, since checking a flag before an
    await only narrows the window; it does not close it.

    An explicit `preset` argument always applies: that is a caller asking for a specific
    manifest, not asking whether one is mounted yet.
    """
    global _BOOTED, _BOOT_LOCK
    import asyncio

    loader = runtime()
    if preset is None and _BOOTED:
        return loader
    if _BOOT_LOCK is None:
        _BOOT_LOCK = asyncio.Lock()
    async with _BOOT_LOCK:
        if preset is None and _BOOTED:
            return loader
        name = default_preset() if preset is None else preset
        if not name:
            loader.source = "(none)"
            _BOOTED = True
            return loader
        from .loader import preset_path
        await loader.apply(preset_path(name), label=name)
        _BOOTED = True
        return loader


def status() -> dict:
    """The rack unit, keys matching `api.py`'s `Unit` model.

    Read at call time, and reporting only what has actually been mounted. Before the first
    request nothing is, and this says so rather than describing the preset it is *going* to
    mount -- a row that reports intent as state is the decorative-indicator failure CLAUDE.md
    forbids, in a place where it would be easy to miss.
    """
    loader = _LOADER
    if loader is None or loader.source is None:
        # `queued`, not `idle` or `degraded`. `api.py`'s `Unit.state` is a four-value Literal
        # (ready / busy / queued / offline) and a fifth value does not fail here -- it fails
        # pydantic validation inside `/api/status`, taking the whole rack down for every other
        # surface. `site/console.js` prints '--' for a bus it does not recognise but the state
        # is validated before it ever reaches the page.
        state, detail = "queued", (f"container up, nothing mounted; preset "
                                   f"{default_preset() or '(none)'} mounts on first request")
    else:
        snapshot = loader.state()
        counts = snapshot["states"]
        bad, waiting = counts.get("failed", 0), counts.get("pending", 0)
        state = "ready"
        # Failures lead. There is no `degraded` in the Literal, so the count is the only place
        # this can be told and burying it behind the healthy numbers would be the same omission
        # as not reporting it.
        parts = ([f"{bad} FAILED"] if bad else []) + [f"{counts.get('active', 0)} active"]
        if waiting:
            parts.append(f"{waiting} pending")
        parts.append(f"{len(snapshot['services'])} services")
        detail = f"preset {loader.source} · " + " · ".join(parts)
    if not enabled():
        detail += " · read-only (set SYMONEURAL_EXP_ENABLED=1 to mutate)"
    return {
        "id": "exp",
        "label": LABEL,
        "slot": "1U",
        "state": state,
        "bus": "cpu",
        "href": "/exp",
        "spec": "plugin runtime · hot-plug · lifecycle",
        "detail": detail,
    }
