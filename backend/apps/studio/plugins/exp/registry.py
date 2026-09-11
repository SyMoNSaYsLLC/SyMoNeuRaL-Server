"""What counts as a plugin, and how one gets mounted.

`ctx.plugin(thing, config)` accepts four shapes. They are not four features -- they are one
rule (*something that can be called with `(ctx, config)`*) applied to the four ways Python
naturally expresses it:

    def hello(ctx, config): ...                     a function
    class Hello:                                     a class -- instantiated, and its
        def __init__(self, ctx, config): ...         instance kept alive by the fiber
    hello = SimpleNamespace(apply=lambda ctx, cfg: ...)   an object with `apply`
    import mypackage.hello                           a module with a module-level `apply`

The module form is the one the loader uses and the reason the others are here: a module *is*
an object with attributes, so once `apply` is looked up by name, module support falls out for
free and there was no reason to exclude the rest.

## Metadata

Read off the plugin itself, wherever it happens to live -- a function attribute, a class
attribute, or a module global:

    inject   = ["llm"]                       required; the fiber stays PENDING without them
             = {"required": [...], "optional": [...]}
    name     = "clock"                       what the UI calls it; defaults to the qualname
    schema   = {"interval": (int, 5)}        config validation, see `check_config`

`inject` as a bare list means required. The dict form exists because "I use it if it is there"
is a real and common relationship -- a plugin that logs to a trace service if one is mounted
should not refuse to start on a box that has no trace service.

## Config validation

`schema` maps a config key to `(type, default)`. This is deliberately not jsonschema, pydantic
or attrs: the serving interpreter carries pydantic already, but the runtime here has to be
importable from a bare interpreter with nothing installed (the same constraint that shaped
`apps/studio/registry.py`), and a plugin's config is a flat dict of scalars in every
case that exists. When that stops being true the honest fix is to say so, not to grow a
half-jsonschema here.

It is also not a safeguard, and the same sentence applies as in the studio registry: it
restricts nothing. It exists because a `KeyError` raised inside a plugin body arrives as a
FAILED fiber with a traceback, and "interval must be an int, got 'five'" arrives as a
sentence.
"""
from __future__ import annotations

import inspect
import typing

from .context import Context, ContextError
from .fiber import Fiber

__all__ = ["Runner", "resolve", "mount", "check_config", "describe"]


class Runner:
    """A plugin, normalised: how to call it, what it needs, what it is called."""

    __slots__ = ("call", "required", "optional", "label", "kind", "schema", "doc", "target")

    def __init__(self, call, required, optional, label, kind, schema, doc, target) -> None:
        self.call = call
        self.required = tuple(required)
        self.optional = tuple(optional)
        self.label = label
        self.kind = kind
        self.schema = schema
        self.doc = doc
        self.target = target

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        return f"<Runner {self.label} ({self.kind}) inject={list(self.required)}>"


def _meta(attr, *sources, default=None):
    """First of `sources` that carries `attr`.

    A module plugin whose `apply` is a class has two plausible homes for `inject` and `schema`:
    the module (where the manifest points and where they read best) and the class. The module
    wins, because that is what the entry names, and the class is checked so a class dropped into
    a module of several still declares its own.
    """
    for source in sources:
        if source is not None and getattr(source, attr, None) is not None:
            return getattr(source, attr)
    return default


def _inject_of(*sources) -> tuple[tuple[str, ...], tuple[str, ...]]:
    raw = _meta("inject", *sources, default=())
    if isinstance(raw, dict):
        return tuple(raw.get("required", ())), tuple(raw.get("optional", ()))
    if isinstance(raw, str):
        # A string is iterable, so `inject = "llm"` would otherwise silently declare eight
        # single-letter services and the fiber would sit in PENDING forever waiting for `l`.
        return (raw,), ()
    return tuple(raw), ()


def resolve(plugin, *, name: str | None = None) -> Runner:
    """Normalise any of the four shapes into a `Runner`. Raises `ContextError` for anything
    that is none of them, naming what was passed -- "expected a plugin" with no more detail is
    the least useful error a loader can produce."""
    entry = getattr(plugin, "apply", None) if not inspect.isclass(plugin) else plugin
    # `target` is where metadata is read from and what the loader reloads; `entry` is what gets
    # called. For a module they differ, which is the whole reason the two names exist -- the
    # manifest points at `plugins.recorder`, the code to run is `plugins.recorder.apply`, and
    # `inject`/`schema` are module globals sitting between them. `target` is unconditional: the
    # four shapes differ in what `entry` becomes, never in this.
    target = plugin
    if entry is None:
        entry = plugin if callable(plugin) else None
    if entry is None:
        raise ContextError(
            f"{plugin!r} is not a plugin. Pass a function `(ctx, config)`, a class taking "
            f"`(ctx, config)`, an object with `.apply(ctx, config)`, or a module with a "
            f"module-level `apply`. Got {type(plugin).__name__}.")

    if inspect.isclass(entry):
        # The instance is not thrown away: it is attached to the fiber by the closure below, so
        # a class plugin can keep state in `self` for as long as it is mounted, and lose it on
        # unload, which is what a class plugin is for.
        def call(ctx, config, _cls=entry):
            instance = _cls(ctx, config)
            stop = getattr(instance, "stop", None) or getattr(instance, "dispose", None)
            ctx.effect(stop if callable(stop) else (lambda: None))
            # Held so `self` stays reachable for the fiber's lifetime and no longer.
            ctx.effect(lambda _keep=instance: None)
            return None
        kind = "class"
    elif callable(entry):
        call, kind = entry, ("module" if inspect.ismodule(plugin)
                             else "object" if entry is not plugin else "function")
    else:
        raise ContextError(
            f"{plugin!r} has an `apply` that is not callable ({type(entry).__name__})")

    required, optional = _inject_of(target, entry)
    label = (name or _meta("name", target, entry)
             or getattr(target, "__name__", None) or repr(target))
    return Runner(call=call, required=required, optional=optional, label=str(label), kind=kind,
                  schema=_meta("schema", target, entry, default={}) or {},
                  doc=inspect.getdoc(target) or inspect.getdoc(entry) or "", target=target)


def check_config(runner: Runner, config: dict | None) -> dict:
    """Fill defaults, coerce the obvious, and complain about the rest. Returns the config to
    use; raises `ContextError` with every problem at once rather than the first one, because a
    manifest entry with three wrong fields should take one edit to fix, not three."""
    config = dict(config or {})
    if not runner.schema:
        return config
    problems: list[str] = []
    for key, spec in runner.schema.items():
        want, default = spec if isinstance(spec, tuple) else (spec, None)
        if key not in config:
            if default is None and not _optional(spec):
                problems.append(f"{key!r} is required ({_typename(want)})")
            else:
                config[key] = default
            continue
        value = config[key]
        if want is typing.Any or isinstance(value, want):
            # `bool` is a subclass of `int`, so `interval: true` satisfies `isinstance(value,
            # int)` and would arrive as an interval of 1. Rejected here. The float and str fields
            # need the same answer and cannot get it here -- `isinstance(True, float)` is False,
            # so a bool bound for a float field never reaches this branch at all; `_coerce` turns
            # it away instead, and the reason is written there.
            if want is int and isinstance(value, bool):
                problems.append(f"{key!r} wants int, got bool")
            continue
        coerced = _coerce(value, want)
        if coerced is _NO:
            # The key and both types, and *not* the value. This message ends up on the fiber,
            # in the trace, and in `GET /api/exp/events`, which is an open read -- so a manifest
            # carrying `config: {interval: "sk-live-..."}` would publish the credential to any
            # visitor the moment it failed validation. The type is what tells you how to fix it;
            # the value is what you already have in front of you in the manifest.
            problems.append(f"{key!r} wants {_typename(want)}, got {type(value).__name__}")
        else:
            config[key] = coerced
    unknown = sorted(set(config) - set(runner.schema))
    if unknown:
        problems.append(f"unknown: {', '.join(unknown)}; accepts "
                        f"{', '.join(sorted(runner.schema))}")
    if problems:
        raise ContextError(f"config for {runner.label}: " + "; ".join(problems))
    return config


_NO = object()


def _optional(spec) -> bool:
    return isinstance(spec, tuple) and len(spec) > 1


def _typename(want) -> str:
    return getattr(want, "__name__", str(want))


def _coerce(value, want):
    """YAML gives strings for anything quoted, and a manifest written by hand quotes things it
    did not need to. `"5"` for an int field is a typo, not a type error, and refusing it just
    makes the manifest harder to write.

    A bool is not one of those typos, and this is where the `bool`-is-an-`int` trap gets closed
    for the two fields `check_config`'s fast path cannot reach. `isinstance(True, float)` is
    False and `isinstance(True, str)` is False, so `flag: true` written against a float or str
    field falls through to here -- and the two tests below accept `int` and `(int, str)`, which
    a bool passes. Without the guard `interval: true` became `1.0` on a float field and
    `"True"` on a str one: the same silent repair the fast path rejects for `int`, one line
    later and two types over. Measured before the guard: `{"x": True}` against `(float, 0.0)`
    returned `{"x": 1.0}`, and `{"s": True}` against `(str, "")` returned `{"s": "True"}`. Both
    now say `wants float, got bool` / `wants str, got bool`, which is what `int` already said.
    """
    if isinstance(value, bool) and want is not bool:
        return _NO
    try:
        if want is int and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        if want is float and isinstance(value, (int, str)):
            return float(value)
        if want is str and isinstance(value, (int, float)):
            return str(value)
        if want is bool and isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
    except (TypeError, ValueError):
        return _NO
    return _NO


#: Strong references to the settle tasks launched below. asyncio keeps only a weak reference to
#: a running task, so a task nobody holds can be collected before it finishes.
_SETTLES: set = set()


def mount(ctx: Context, plugin, config=None, *, name: str | None = None) -> Fiber:
    """Create the fiber and schedule a settle. Called by `Context.plugin`.

    The fiber comes back before it has started -- deliberately. `await` it to settle, or mount
    it from inside another plugin body and let the settle pass already running find it. A
    config error is turned into a FAILED fiber rather than a raised exception for the same
    reason a plugin body's exception is: the caller is usually a loader working through a
    manifest, and entry three being wrong is not a reason for entries four through twelve to
    never mount.
    """
    runner = resolve(plugin, name=name)
    try:
        checked = check_config(runner, config)
    except ContextError as exc:
        fiber = Fiber(ctx, runner, config, label=runner.label)
        fiber.state = "failed"
        fiber.error = str(exc)
        ctx.runtime.trace.add("fiber/fail", fiber=fiber.id, plugin=fiber.label, error=str(exc))
        return fiber
    fiber = Fiber(ctx, runner, checked, label=runner.label)
    try:
        import asyncio
        task = asyncio.get_running_loop().create_task(ctx.runtime.settle())
        # Two reasons for the set and the callback. A task with no strong reference can be
        # garbage-collected mid-await, which would leave the fiber PENDING forever with nothing
        # scheduled to start it. And `settle()` raises when it cannot converge; on this path
        # there is no caller to catch it, so without the callback the only trace of a wedged
        # manifest is asyncio's "Task exception was never retrieved" on the API's stderr.
        # `settle()` records the failure on the runtime itself; this is the backstop for
        # anything else that comes out of a plugin body during a settle pass.
        _SETTLES.add(task)

        def _done(finished, _runtime=ctx.runtime):
            _SETTLES.discard(finished)
            if finished.cancelled():
                return
            exc = finished.exception()
            if exc is not None:
                _runtime.trace.add("runtime/settle-error", error=f"{type(exc).__name__}: {exc}")
                if _runtime.settle_error is None:
                    _runtime.settle_error = f"{type(exc).__name__}: {exc}"

        task.add_done_callback(_done)
    except RuntimeError:
        # No loop: a synchronous caller built the graph and will drive it itself. The fiber is
        # registered and PENDING, and the first `await runtime.settle()` starts it.
        pass
    return fiber


def describe(plugin) -> dict:
    """Static description without mounting anything -- what the page's plugin catalogue is
    built from, and what `GET /api/exp/catalogue` returns."""
    runner = resolve(plugin)
    return {
        "name": runner.label,
        "kind": runner.kind,
        "inject": list(runner.required),
        "optional": list(runner.optional),
        "schema": {k: {"type": _typename(v[0] if isinstance(v, tuple) else v),
                       "default": v[1] if isinstance(v, tuple) else None}
                   for k, v in (runner.schema or {}).items()},
        "doc": runner.doc.split("\n\n")[0] if runner.doc else "",
    }
