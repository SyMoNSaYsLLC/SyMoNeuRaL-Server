"""The manifest, and everything that turns text into running plugins.

`context.py`, `fiber.py` and `registry.py` know nothing about files. You can build a whole
graph by hand with `ctx.plugin(...)` and never come here. This module is the other half:
declarative configuration, plugins named as strings, hot-plug, and presets.

## The manifest

    plugins:
      - id: bus
        use: apps.studio.plugins.exp.plugins.bus
      - id: clock
        use: apps.studio.plugins.exp.plugins.clock
        config: {interval: 5}
      - id: session
        isolate: [llm, memory]        # a group -- see below
        plugins:
          - id: session.llm
            use: apps.studio.plugins.exp.plugins.echo_llm
      - id: broken
        use: apps.studio.plugins.exp.plugins.explode
        disabled: true

`use` is resolved three ways, tried in this order:

    apps.studio.plugins.exp.plugins.clock         an importable module with a module-level `apply`
    apps.studio.plugins.exp.plugins:clock         an attribute of an importable module
    ./plugins/clock.py                       a filesystem path, loaded by spec

The path form exists because dropping a `.py` file next to the manifest and reloading is the
shortest hot-plug story there is, and it does not require the file to be inside a package.

## Groups and `isolate`

An entry with `plugins:` instead of `use:` is a group. Its children mount on a context derived
from the group's, and if the group names `isolate`, each of those names resolves in a private
realm. That is the session fork: two `session` groups each providing `llm` do not see each
other's, and both still see the process-wide `bus` that neither isolated.

`intercept` on a group does the other half -- every child's calls into that service carry the
group's defaults.

## Applying a manifest is a diff, not a rebuild

`apply()` compares the incoming manifest against what is mounted and does the smallest thing
that reconciles them: mount what is new, dispose what is gone, patch what changed config, and
*leave alone* what did not. Rebuilding is three lines shorter and passes the same tests, and it
throws away the entire point of hot-plug -- editing one entry in a manifest must not restart
the eleven plugins you did not touch. A restart is cheap here only because these plugins are
small; the moment one of them holds a model or a socket it stops being cheap, and by then the
loader's behaviour is load-bearing.

## Hot-reload

`reload(id)` calls `importlib.reload` on the plugin's module, re-resolves it, `rebind`s the
fiber to the new callable, and restarts it. The rebind step is not optional and is the reason
`Fiber.rebind` exists: `restart()` alone re-runs the function object the fiber captured when it
was created, which is the *old* code, while the trace and the UI both report a successful
reload. See that method's docstring.

## Events

    internal/plugin        a fiber changed state (from `fiber.py`)
    loader/patch-context   an entry's config was replaced; carries (entry, old, new)
    loader/entry-add       an entry was mounted by a manifest apply
    loader/entry-remove    an entry was disposed by a manifest apply
    hmr/reload             a fiber is being reloaded; carries the reason

These are the observability hooks. A plugin subscribing to `internal/plugin` can maintain its
own view of the graph without polling, which is what `routes.py` does for the events feed and
what a UI plugin would do to draw one.

## What this is not

Not a sandbox. A plugin is imported into this process and can do everything the process can do.
`docs/isolation.md` says what would actually be required and why none of it is here.
"""
from __future__ import annotations

import importlib
import importlib.util
import pathlib
import sys
import typing

from . import registry
from .context import Context, ContextError, Runtime
from .fiber import DISPOSED, FAILED, Fiber

__all__ = ["Loader", "Entry", "load_manifest", "presets", "preset_path"]

#: Where `preset("dev")` looks. A directory rather than one file so a preset can be added by
#: dropping a file in, which is the same reason `plugins/` is a directory.
PRESET_DIR = pathlib.Path(__file__).resolve().parent / "presets"


def _yaml():
    """PyYAML, imported at the point of use.

    `api.py` imports this package at boot to mount its router. A module-scope `import yaml`
    would mean a missing PyYAML takes down the whole live API rather than one app -- and the
    same import is what would abort pytest *collection* rather than fail one test, which is the
    failure mode CLAUDE.md warns about by name.
    """
    import yaml                                   # noqa: PLC0415 -- deliberate, see above
    return yaml


# ----------------------------------------------------------------------------- resolution
def resolve_ref(ref: str):
    """`use:` string to a plugin object, in one of three forms.

    Every failure is a `ContextError` naming what it tried, and the three branches say three
    different things on purpose. `package.module:attribute` already told us which module and
    which attribute, so its errors name those; a path already told us the file, so its error is
    the path. Only the bare dotted name is genuinely ambiguous -- it could have been any of the
    three and was probably a typo in one of them -- so that is the one branch that lists all
    three forms. An earlier revision of this line claimed every branch did, which is a promise
    two of them do not keep and do not need to.
    """
    ref = str(ref).strip()
    if ":" in ref and not ref[1:2] == ":":        # not a Windows drive letter; we are on Linux
        module_name, _, attr = ref.partition(":")
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:
            # Wrapped for the same reason as the bare-module branch below: `_mount` records a
            # `ContextError` on the entry and carries on, and an unwrapped `ModuleNotFoundError`
            # escaping `apply()` would abort the whole manifest over one typo.
            raise ContextError(f"cannot import {module_name!r} for {ref!r}: {exc}") from None
        try:
            return getattr(module, attr)
        except AttributeError:
            raise ContextError(
                f"{module_name!r} has no attribute {attr!r}") from None
    if ref.endswith(".py") or "/" in ref:
        return _from_path(ref)
    try:
        return importlib.import_module(ref)
    except ImportError as exc:
        raise ContextError(
            f"cannot resolve plugin {ref!r}: {exc}. Tried it as a module, and it is neither "
            f"'package.module:attribute' nor a path ending in .py") from None


def _from_path(ref: str):
    """Load a `.py` file that is not in any package.

    Relative paths resolve against this package's directory, so a manifest can say
    `plugins/clock.py` and mean the obvious thing. The module is registered in `sys.modules`
    under a name derived from the path -- without that, `importlib.reload` has nothing to
    reload and hot-reload of a path-loaded plugin silently does nothing.
    """
    path = pathlib.Path(ref)
    if not path.is_absolute():
        path = (pathlib.Path(__file__).resolve().parent / path).resolve()
    if not path.exists():
        raise ContextError(f"no such plugin file: {path}")
    name = "expplug_" + str(path).replace("/", "_").replace(".", "_").strip("_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:       # pragma: no cover -- unreadable file
        raise ContextError(f"cannot load {path} as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module_of(target) -> object | None:
    """The module to re-execute for a plugin, or None when there is no way to name one.

    Three of the four shapes `registry.resolve` accepts answer this. A module is itself; a
    function and a class both carry `__module__` naming the file they were defined in; an
    *instance* inherits `__module__` from its type, which is also the right file whenever the
    class was defined in the plugin. What has no answer is a plugin assembled at runtime --
    `types.SimpleNamespace(apply=...)` has no `__module__` attribute at all (checked on 3.13.5:
    `hasattr` is False, not None) -- and a target whose `__module__` names a module that is not
    in `sys.modules`. Both return None, and `Loader.reload` has to say so instead of reporting
    a reload it did not perform.
    """
    if isinstance(target, type(sys)):
        return target
    name = getattr(target, "__module__", None)
    return sys.modules.get(name) if name else None


def reload_module(module):
    """Re-execute a module in place, including one loaded from a bare path.

    `importlib.reload` cannot do the second case and fails in a way that reads like success if
    you are not looking: it re-derives the spec by asking the meta path finders for the module's
    *name*, and a module created by `spec_from_file_location` has a synthetic name no finder has
    ever heard of, so it raises `ImportError: spec not found for the module`. Caught and
    reported, that becomes "reload failed" -- which is at least honest, but it means hot-reload
    of a dropped-in file, the headline use, never worked at all.

    The fix is to rebuild the spec from the file the module actually came from and execute it
    into the same module object. Same object means every reference already handed out keeps
    working; re-executed means they see the new code. A `SyntaxError` is raised at compile time,
    before a single statement runs, so a broken edit leaves the module's namespace exactly as it
    was and the plugin keeps serving the code it has.
    """
    origin = getattr(module, "__file__", None)
    if origin and getattr(module, "__package__", None) in (None, "", module.__name__):
        spec = importlib.util.spec_from_file_location(module.__name__, origin)
        if spec is not None and spec.loader is not None:
            spec.loader.exec_module(module)
            module.__spec__ = spec
            return module
    return importlib.reload(module)


# ----------------------------------------------------------------------------- entries
class Entry:
    """One line of the manifest, and the fiber it produced.

    Kept apart from the fiber deliberately. An entry survives its fiber -- a disabled entry has
    none, a failed reload may leave none -- and the API mutates by entry id, because that is
    what the manifest names and what a person editing YAML can see. Fiber ids are runtime
    identity; entry ids are configuration identity, and conflating them means an entry that
    fails to mount becomes unaddressable exactly when you want to fix it.
    """

    __slots__ = ("id", "use", "config", "disabled", "isolate", "intercept", "children",
                 "fiber", "error", "parent", "realms")

    def __init__(self, raw: dict, *, parent: "Entry | None" = None, index: int = 0) -> None:
        if not isinstance(raw, dict):
            raise ContextError(f"manifest entry must be a mapping, got {type(raw).__name__}")
        self.use = raw.get("use")
        self.config = dict(raw.get("config") or {})
        self.disabled = bool(raw.get("disabled", False))
        self.isolate = list(raw.get("isolate") or ())
        self.intercept = dict(raw.get("intercept") or {})
        self.parent = parent
        # `is not None`, not `or`: YAML 1.1 parses the bare words `on`, `off`, `yes` and `no`
        # as booleans, so `id: off` arrives here as `False`, and an `or` chain would fall
        # through to `use` -- giving the entry a module path for a name. But `str(False)` is not
        # a rescue either: it names the entry "False", which is not what its author typed and
        # not what `POST /remove {"id": "off"}` looks for, so the entry becomes unaddressable
        # by any spelling anyone would try. Raising here is the only outcome that reaches the
        # person who can fix it, so it raises and names the fix.
        given = raw.get("id")
        if isinstance(given, bool):
            raise ContextError(
                f"entry id {given!r} came from a bare YAML 1.1 boolean -- 'on', 'off', 'yes' "
                f"and 'no' are parsed as True/False before this code sees them. Quote it: "
                f'id: "{"on" if given else "off"}"')
        self.id = str(given) if given is not None else str(self.use or f"entry-{index}")
        self.children = [Entry(child, parent=self, index=i)
                         for i, child in enumerate(raw.get("plugins") or ())]
        self.fiber: Fiber | None = None
        self.error: str | None = None
        #: Realm ids for the names in `isolate`, minted once by `Loader._group_context` and
        #: carried across a re-apply. A realm minted per call would make every re-derived group
        #: context an empty namespace -- see `Context.with_realms`.
        self.realms: dict[str, str] = {}
        if self.use is None and not self.children:
            raise ContextError(f"entry {self.id!r} has neither 'use' nor 'plugins'")

    @property
    def is_group(self) -> bool:
        return self.use is None

    def walk(self) -> typing.Iterator["Entry"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def snapshot(self, *, with_config: bool) -> dict:
        out = {
            "id": self.id,
            "use": self.use,
            "disabled": self.disabled,
            "group": self.is_group,
            "isolate": list(self.isolate),
            "children": [c.id for c in self.children],
            "fiber": self.fiber.id if self.fiber else None,
            "state": self.fiber.state if self.fiber else (
                "disabled" if self.disabled else "failed" if self.error
                else "group" if self.is_group else "unmounted"),
            "error": self.error or (self.fiber.error if self.fiber else None),
        }
        if with_config:
            out["config"] = dict(self.config)
        return out

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        return f"<Entry {self.id} {'group' if self.is_group else self.use}>"


def load_manifest(source: str | pathlib.Path | dict) -> list[dict]:
    """A path, a YAML string, or an already-parsed dict, to a list of raw entry dicts.

    Accepts both `{"plugins": [...]}` and a bare list, because half the manifests anyone writes
    by hand are the bare list and rejecting it teaches nothing.
    """
    if isinstance(source, dict):
        data = source
    elif isinstance(source, pathlib.Path) or (
            isinstance(source, str) and "\n" not in source and source.endswith((".yaml", ".yml"))):
        path = pathlib.Path(source)
        if not path.exists():
            raise ContextError(f"no such manifest: {path}")
        data = _yaml().safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = _yaml().safe_load(str(source)) or {}
    if isinstance(data, list):
        return list(data)
    if not isinstance(data, dict):
        raise ContextError(f"manifest must be a mapping or a list, got {type(data).__name__}")
    plugins = data.get("plugins", [])
    if not isinstance(plugins, list):
        raise ContextError("manifest 'plugins' must be a list")
    return list(plugins)


def presets() -> list[str]:
    """Preset names available on this box, sorted."""
    if not PRESET_DIR.is_dir():
        return []
    return sorted(p.stem for p in PRESET_DIR.glob("*.y*ml"))


def preset_path(name: str) -> pathlib.Path:
    for suffix in (".yaml", ".yml"):
        candidate = PRESET_DIR / f"{name}{suffix}"
        if candidate.exists():
            return candidate
    raise ContextError(f"no preset {name!r}; have: {', '.join(presets()) or '(none)'}")


# ----------------------------------------------------------------------------- the loader
class Loader:
    """Owns a `Runtime`, a root `Context`, and the entry tree mounted on it."""

    def __init__(self, runtime: Runtime | None = None, *, trace_path=None) -> None:
        self.runtime = runtime or Runtime(trace_path=trace_path)
        self.root = Context(self.runtime)
        self.entries: list[Entry] = []
        self.source: str | None = None          # the preset or path last applied, for the UI

    # -- lookup ------------------------------------------------------------
    def all_entries(self) -> list[Entry]:
        return [e for top in self.entries for e in top.walk()]

    def find(self, entry_id: str) -> Entry:
        for entry in self.all_entries():
            if entry.id == entry_id:
                return entry
        raise ContextError(f"no entry {entry_id!r}; have: "
                           f"{', '.join(e.id for e in self.all_entries()) or '(none)'}")

    # -- mounting ----------------------------------------------------------
    async def apply(self, source, *, label: str | None = None) -> "Loader":
        """Reconcile the running graph with a manifest. The diff, not a rebuild.

        Matching is by entry id. An entry present in both is patched if its config or `use`
        changed and otherwise left running -- untouched, same fiber, same id, no restart. This
        is what makes editing one line of a manifest a local operation.
        """
        raw = load_manifest(source)
        incoming = [Entry(item, index=i) for i, item in enumerate(raw)]
        await self._reconcile(self.entries, incoming, self.root, None)
        self.entries = incoming
        self.source = label or (str(source) if isinstance(source, (str, pathlib.Path))
                                and len(str(source)) < 200 else None)
        await self.runtime.settle()
        return self

    async def _reconcile(self, current: list[Entry], incoming: list[Entry],
                         ctx: Context, parent: Entry | None) -> None:
        by_id = {e.id: e for e in current}
        seen: set[str] = set()
        for entry in incoming:
            seen.add(entry.id)
            existing = by_id.get(entry.id)
            if existing is None:
                await self._mount(entry, ctx)
                await self.runtime.emit("loader/entry-add", entry)
                continue
            # Carry the live fiber across, then decide whether it can stay.
            entry.fiber, entry.error = existing.fiber, existing.error
            entry.realms = existing.realms
            changed = (entry.use != existing.use
                       or entry.isolate != existing.isolate
                       or entry.intercept != existing.intercept
                       or entry.disabled != existing.disabled)
            if changed:
                await self._unmount(existing)
                entry.fiber, entry.error, entry.realms = None, None, {}
                await self._mount(entry, ctx)
            elif entry.is_group:
                child_ctx = self._group_context(ctx, entry)
                await self._reconcile(existing.children, entry.children, child_ctx, entry)
            elif entry.config != existing.config and entry.fiber is not None:
                await self._patch_fiber(entry, existing.config)
        for entry in current:
            if entry.id not in seen:
                await self._unmount(entry)
                await self.runtime.emit("loader/entry-remove", entry)

    def _group_context(self, ctx: Context, entry: Entry) -> Context:
        """The context a group's children mount on. Idempotent -- calling it twice for the same
        entry gives back a view onto the same realms, not a second private namespace."""
        if entry.isolate and not entry.realms:
            entry.realms = {name: self.runtime.new_realm(f"{entry.id}.{name}")
                            for name in entry.isolate}
        child = ctx.with_realms(entry.realms) if entry.realms else ctx
        for name, defaults in entry.intercept.items():
            child = child.intercept(name, **(defaults or {}))
        return child

    async def _mount(self, entry: Entry, ctx: Context) -> None:
        """Entry to fiber. `entry.init()` in the upstream loader; the same job.

        A resolution failure is recorded on the entry rather than raised, for the reason stated
        all through this package: a manifest with one bad `use:` in it must still mount the
        other eleven, and the person fixing it needs to see which one and why -- which is on the
        entry, in the trace, and in `GET /api/exp/plugins`.
        """
        entry.error = None
        if entry.disabled:
            self.runtime.trace.add("loader/skip", entry=entry.id, reason="disabled")
            return
        if entry.fiber is not None and entry.fiber.state != "disposed":
            # Mounting over a live fiber orphans it: nothing holds its handle any more, and its
            # effects will never run. Unmount first, always.
            await self._unmount(entry)
        if entry.is_group:
            child_ctx = self._group_context(ctx, entry)
            self.runtime.trace.add("loader/group", entry=entry.id,
                                   isolate=list(entry.isolate),
                                   intercept=sorted(entry.intercept))
            for child in entry.children:
                await self._mount(child, child_ctx)
            return
        try:
            plugin = resolve_ref(entry.use)
        except Exception as exc:                                  # noqa: BLE001
            # Not just `ContextError`. Resolving a `use:` *imports a module*, which runs
            # arbitrary module-level code, so anything at all can come back out of here -- a
            # `SyntaxError` in the plugin file, a `RuntimeError` raised at import, an
            # `OSError` from something it opens on the way up. Every one of those has to land
            # on the entry rather than escape `apply()`, or one bad line in one plugin file
            # unmounts the other eleven entries by never mounting them.
            entry.error = f"{type(exc).__name__}: {exc}"
            self.runtime.trace.add("loader/error", entry=entry.id, use=entry.use,
                                   error=entry.error)
            return
        entry.fiber = ctx.plugin(plugin, entry.config, name=entry.id)

    async def _unmount(self, entry: Entry) -> None:
        for child in entry.children:
            await self._unmount(child)
        if entry.fiber is not None:
            await entry.fiber.dispose()
            self.runtime.trace.add("loader/unmount", entry=entry.id, fiber=entry.fiber.id)
            entry.fiber = None

    async def _patch_fiber(self, entry: Entry, old: dict) -> None:
        """New config onto a running fiber. Validated here, because this is the one path that
        changes a config without going through `mount`, and an unchecked patch means a typo in
        the config editor arrives as a `KeyError` from inside the plugin body four states later
        instead of as a sentence naming the field."""
        self.runtime.trace.add("loader/patch", entry=entry.id,
                               keys=sorted(set(old) ^ set(entry.config)
                                           | {k for k in set(old) & set(entry.config)
                                              if old[k] != entry.config[k]}))
        try:
            entry.config = registry.check_config(entry.fiber.runner, entry.config)
        except ContextError as exc:
            entry.config, entry.error = old, str(exc)
            self.runtime.trace.add("loader/error", entry=entry.id, phase="patch",
                                   error=str(exc))
            return
        entry.error = None
        await self.runtime.emit("loader/patch-context", entry, old, entry.config)
        await entry.fiber.restart(entry.config)

    # -- mutation ----------------------------------------------------------
    async def patch(self, entry_id: str, config: dict) -> Entry:
        """Replace one entry's config and restart its fiber. The API's config editor."""
        entry = self.find(entry_id)
        old, entry.config = dict(entry.config), dict(config or {})
        if entry.fiber is None or entry.fiber.state == DISPOSED:
            entry.fiber = None                  # same condition as `reload` -- see `Fiber.restart`
            await self._mount(entry, self.root)
        else:
            await self._patch_fiber(entry, old)
        await self.runtime.settle()
        return entry

    async def enable(self, entry_id: str, on: bool = True) -> Entry:
        """Hot-plug, both directions. Disabling disposes; enabling mounts from scratch.

        The guard below compares against the state being asked for, so asking for the state an
        entry is already in does nothing. Inverting that comparison is the interesting failure:
        enabling an already-enabled entry would mount a *second* fiber over the first, the second
        one's `provide` would be refused (`Context.provide` will not take a second live owner),
        the entry would point at that failure, and the original fiber would go on running with
        nothing holding its handle. `_mount` refuses to run over a live fiber for the same
        reason -- two guards for one leak, because this one is invisible from the outside.
        `test_exp.py::LifecycleTests::test_hot_plug_runs_in_both_directions` covers the
        ordinary path.
        """
        entry = self.find(entry_id)
        if entry.disabled != (not on):
            entry.disabled = not on
            if on:
                await self._mount(entry, self._context_for(entry))
            else:
                await self._unmount(entry)
        await self.runtime.settle()
        return entry

    async def add(self, raw: dict) -> Entry:
        """Mount one new entry at the top level without touching anything else."""
        entry = Entry(raw, index=len(self.entries))
        if any(e.id == entry.id for e in self.all_entries()):
            raise ContextError(f"entry {entry.id!r} already exists")
        self.entries.append(entry)
        await self._mount(entry, self.root)
        await self.runtime.emit("loader/entry-add", entry)
        await self.runtime.settle()
        return entry

    async def remove(self, entry_id: str) -> None:
        entry = self.find(entry_id)
        await self._unmount(entry)
        if entry.parent is not None:
            entry.parent.children.remove(entry)
        elif entry in self.entries:
            self.entries.remove(entry)
        await self.runtime.emit("loader/entry-remove", entry)
        await self.runtime.settle()

    async def reload(self, entry_id: str) -> Entry:
        """Re-import the plugin's module and restart the fiber against the new code.

        The order is import, rebind, restart, and every step is load-bearing:

        * `importlib.reload` rebinds the names inside the module object. Anything holding a
          reference to the *old* function still has the old function -- which is exactly what
          the fiber is.
        * `rebind` moves the fiber onto the freshly resolved callable, re-checks the config
          against the possibly-new schema, and rebuilds the declared access from the possibly-
          new `inject`.
        * `restart` unwinds and runs it, disposing dependents first (see `Fiber._unwind`).

        Skipping the middle step is the classic hot-reload lie: everything reports success and
        the old code keeps running.
        """
        entry = self.find(entry_id)
        if entry.is_group:
            for child in entry.children:
                await self.reload(child.id)
            return entry
        if entry.fiber is None or entry.fiber.state == DISPOSED:
            # From this side a disposed fiber and no fiber are the same condition: neither is in
            # `runtime.fibers`, so neither can be restarted -- see `Fiber.restart`. Mount the
            # entry again. Dropping the reference first keeps `_mount`'s failure path from
            # leaving the entry pointing at the dead one.
            entry.fiber = None
            await self._mount(entry, self._context_for(entry))
            await self.runtime.settle()
            return entry
        module = _module_of(entry.fiber.runner.target)
        if module is not None:
            try:
                reload_module(module)
            except Exception as exc:                              # noqa: BLE001
                # A syntax error in the edited file. The fiber keeps running the code it has --
                # which is the right outcome, and the one a reload-by-remount cannot offer,
                # because that disposes first and then discovers the file does not parse.
                entry.error = f"reload failed, still running previous code: {exc}"
                self.runtime.trace.add("loader/error", entry=entry.id, phase="reload",
                                       error=str(exc))
                return entry
        # A path `use:` gets re-executed by `resolve_ref` below whichever way the block above
        # went, because `_from_path` calls `exec_module` every time it is asked. So a missing
        # module only means "nothing was re-imported" for the shapes that reach their runner
        # through an attribute lookup on an already-imported module.
        #
        # It also means a path `use:` has its body run *twice* per reload -- once by
        # `reload_module` above and once by `resolve_ref` below -- and the fiber is bound to the
        # second module object, so the first execution is wasted work with live side effects.
        # Measured, not inferred: a counter appended to on import reaches 2 after one `reload`.
        # Left in place here because removing it changes hot-reload semantics for every shape,
        # which is not a claims fix; it is an open item in `.claude/HANDOVER.md`.
        ref = str(entry.use or "")
        from_disk_anyway = ref.endswith(".py") or "/" in ref
        skipped = module is None and not from_disk_anyway
        # Assigned once, and this is the whole of B14: the previous form set a message inside
        # the `except` above and then cleared it here unconditionally, so the one case that had
        # something to report -- a target with no module to re-execute -- came back as a plain
        # 200 with `error: null`, indistinguishable from a reload that read the file. `state`
        # still comes from the fiber, which really is running; `error` is the only channel for
        # "the process is fine and your edit did not take", which is what the `/reload` route
        # docstring already says callers must read.
        entry.error = (
            "nothing was re-imported: this plugin object does not name a module that is in "
            "sys.modules, so there is no file to re-execute. Rebound and restarted against "
            "the code already loaded." if skipped else None)
        try:
            plugin = resolve_ref(entry.use)
        except Exception as exc:                                  # noqa: BLE001
            # Not just `ContextError`. Resolving a `use:` *imports a module*, which runs
            # arbitrary module-level code, so anything at all can come back out of here -- a
            # `SyntaxError` in the plugin file, a `RuntimeError` raised at import, an
            # `OSError` from something it opens on the way up. Every one of those has to land
            # on the entry rather than escape `apply()`, or one bad line in one plugin file
            # unmounts the other eleven entries by never mounting them.
            entry.error = f"{type(exc).__name__}: {exc}"
            return entry
        entry.fiber.rebind(registry.resolve(plugin, name=entry.id))
        if entry.fiber.state != FAILED:
            # The reason string is read back by the trace pane, so it has to distinguish the
            # two outcomes as well: `module-reloaded` on a skip is the same false claim as the
            # cleared `error` was, one field over.
            await self.runtime.emit("hmr/reload", entry.fiber,
                                    "rebound-only" if skipped else "module-reloaded")
            await entry.fiber.restart()
        await self.runtime.settle()
        return entry

    def _context_for(self, entry: Entry) -> Context:
        """The context an entry mounts on, walking the group chain down from the root."""
        chain: list[Entry] = []
        node = entry.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        ctx = self.root
        for group in reversed(chain):
            ctx = self._group_context(ctx, group)
        return ctx

    # -- teardown ----------------------------------------------------------
    async def dispose(self) -> None:
        for entry in list(self.entries):
            await self._unmount(entry)
        self.entries = []

    # -- introspection -----------------------------------------------------
    def state(self, *, with_config: bool = False) -> dict:
        fibers = [f.snapshot() for f in self.runtime.fibers]
        counts: dict[str, int] = {}
        for fiber in fibers:
            counts[fiber["state"]] = counts.get(fiber["state"], 0) + 1
        return {
            "source": self.source,
            "presets": presets(),
            "entries": [e.snapshot(with_config=with_config) for e in self.all_entries()],
            "fibers": fibers,
            # Every service in the container, realm-qualified -- not `self.root.services()`,
            # which sees the root realm only. The rack row counts this list, and with an
            # isolated service mounted the root view is empty: the row said "0 services /
            # nothing provided" while the Services table on the same page listed the row it
            # could not see. Two panels disagreeing about one reading is the failure the
            # honesty rule exists to prevent.
            "services": sorted(s.key for s in self.runtime.services.values()),
            "states": counts,
            "events": len(self.runtime.trace),
            "seq": self.runtime.trace.seq,
            #: Non-null only when `Runtime.settle` gave up. See `context.settle` for why this
            #: has to travel in the payload rather than as a raised exception.
            "settle_error": self.runtime.settle_error,
        }
