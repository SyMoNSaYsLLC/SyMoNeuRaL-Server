"""The service container, and the object every plugin is handed.

`Context` is the whole extension surface: a plugin is a callable that takes one and registers
things on it, and everything it registers is reversible. That is the idea Cordis calls
*spatiotemporal composability* and it is worth one paragraph in plain terms, because the name
is doing it no favours.

**Spatial** -- two plugins can be given the same service name and each see a different object,
because a context can `isolate()` a name into its own realm. That is how a session gets its own
`llm` without the process-wide one being touched.

**Temporal** -- a plugin can be unloaded at any moment and everything it did comes undone, in
reverse order, because every registration returned a disposer that its `Fiber` kept. That is
what makes hot-plugging safe rather than a leak with an optimistic name.

## What a plugin looks like

    def clock(ctx, config):
        ctx.provide("clock", Clock(config["interval"]))     # reverted on unload
        ctx.on("tick", lambda n: ...)                       # unsubscribed on unload
        ctx.effect(lambda: print("goodbye"))                # arbitrary cleanup

    clock.inject = ["bus"]                                  # declared dependency

Four forms are accepted, resolved in `registry.py`: a function, an object with `apply`, a class
with `__init__(self, ctx, config)`, and a module with a module-level `apply`. The last one is
what the loader uses, and is the reason the others exist -- a module *is* an object with an
attribute, so supporting modules for free meant supporting all four.

## Access is declared, not discovered

`ctx.llm` raises `ContextError` inside a plugin that did not declare `inject = ["llm"]`. This
is not a security boundary and cannot be one -- the plugin is ordinary Python in this process
and can `import` whatever it likes. It exists because the dependency graph is what the runtime
uses to decide *what to reload when a service changes*, and a dependency nobody declared is a
dependency the runtime cannot honour. An undeclared access that works by accident is a plugin
that silently keeps a stale service object after a reload. Better to say so at the point of
use.

The root context -- the one with no fiber -- has no restriction. It is not a plugin; it is the
thing that mounts them.

## Nothing here is a sandbox

`docs/isolation.md` explains at length why not, and what the options actually cost. The short
version: no filtering or sandboxing is implemented as of 2026-08-20 (a deliberate pre-launch
state, not a cleared posture -- request ledger R-98, held), and every plugin in this repository
was written in this repository. In-process isolation of Python from Python is not achievable
anyway -- `vm2`,
the JavaScript answer to this problem, was archived by its author after escapes that could not
be fixed. The seam for real isolation is out-of-process, and a plugin that spawns a subprocess
is just a plugin.
"""
from __future__ import annotations

import asyncio
import inspect
import typing

from . import trace as tracemod

__all__ = ["Context", "ContextError", "Runtime", "Service", "Disposer"]

Disposer = typing.Callable[[], typing.Any]


class ContextError(RuntimeError):
    """Raised for a misuse of the container: an undeclared service, a name already provided by
    a live fiber, a disposer that ran twice. Never raised for a plugin's own exception -- that
    is recorded on the fiber and left as it came."""


class Service:
    """One entry in the container.

    `epoch` is the mechanism behind reactive reload. It starts at 1 and increments when a name
    *already in the container* is provided again with a different object; each active fiber
    remembers the epoch it started against, and one whose remembered epoch no longer matches is
    *stale* and gets restarted by `settle`. So a plugin holding `ctx.llm` never has to wonder
    whether the object it captured is still the one the container would hand out.

    It counts re-provisions in place, not rebindings over the lifetime of a name. A provider
    that unwinds first takes the entry out with it -- `revoke` below deletes the key -- so its
    replacement is a new `Service` starting at 1 again, which is what makes a restarted fiber
    read `epoch=1` next to a brand-new object. That case is not a missed bump: `Fiber.stale`
    only asks about names still present, and a name that went away is `Fiber.missing`'s
    business. `test_exp.py::ServiceEpochTests` pins both halves.

    It is a version number, and calling it that would have been clearer than what upstream calls
    it, but the concept is borrowed and so is the word.
    """

    __slots__ = ("key", "name", "value", "owner", "epoch")

    def __init__(self, key: str, name: str, value: typing.Any, owner) -> None:
        self.key = key
        self.name = name
        self.value = value
        self.owner = owner          # the Fiber that provided it, or None for the root
        self.epoch = 1

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        return f"<Service {self.key} epoch={self.epoch} owner={getattr(self.owner, 'id', None)}>"


class Runtime:
    """Everything shared between contexts: services, listeners, fibers, and the trace.

    A `Context` is a cheap view onto one of these -- create as many as you like, they hold
    three fields and a reference here. The runtime is the thing with state.
    """

    #: How many settle passes before we call it an oscillation. A pass that changes nothing
    #: ends the loop, so this only trips when two fibers keep invalidating each other, which is
    #: a real bug in the plugins rather than a limit worth tuning.
    MAX_PASSES = 32

    def __init__(self, *, trace_path=None, trace_limit: int = 2000) -> None:
        self.services: dict[str, Service] = {}
        self.listeners: dict[str, list[tuple[int, typing.Callable]]] = {}
        self.fibers: list = []
        self.trace = tracemod.Trace(path=trace_path, limit=trace_limit)
        self._realm_counter = 0
        self._listener_counter = 0
        self._settling = False
        self._lock = asyncio.Lock()
        #: Set by `settle()` when it gives up, cleared when it converges. Published by
        #: `Loader.state()`, so the one failure this runtime cannot recover from is visible on
        #: the page rather than only on stderr.
        self.settle_error: str | None = None

    # -- realms ------------------------------------------------------------
    def new_realm(self, label: str = "") -> str:
        self._realm_counter += 1
        return f"{label or 'realm'}#{self._realm_counter}"

    # -- the settle loop ---------------------------------------------------
    async def settle(self) -> None:
        """Bring every fiber to the state its dependencies imply, and keep going until nothing
        changes.

        This is one loop rather than a graph walk on purpose. A graph walk has to decide an
        order, and the order depends on which services each plugin provides, which is not known
        until the plugin has run: a plugin that provides `a` and injects `b` and a plugin that
        provides `b` and injects `a` have no valid static order, and the walk would have to pick
        one and stall. Repeated passes over a flat list have no such problem -- each pass starts
        whatever is now ready, and the pass after it sees the services that produced.

        Re-entrant calls are a no-op. `ctx.plugin()` inside a plugin body appends a fiber and
        calls `settle()`; that call arrives while this one holds the lock, and returns
        immediately, because the loop it would have run is the loop already running and will
        pick the new fiber up on its next pass.
        """
        if self._settling:
            return
        async with self._lock:
            self._settling = True
            try:
                for _ in range(self.MAX_PASSES):
                    changed = False
                    for fiber in list(self.fibers):
                        changed = await fiber._reconcile() or changed
                    if not changed:
                        self.settle_error = None
                        return
                # Recorded before it is raised, and kept on the runtime, because of how this
                # gets called: `registry.mount` launches `settle()` as a task, so on that path
                # the exception has no caller to reach and would otherwise surface only as
                # asyncio's "Task exception was never retrieved" on stderr -- not on a fiber,
                # not in the trace, and not in any API reply. `loader.state()` publishes this
                # field, so the page shows it.
                self.settle_error = (
                    f"plugin states did not settle in {self.MAX_PASSES} passes -- two fibers "
                    f"are probably invalidating each other; the trace shows the sequence "
                    f"(GET /api/exp/events, or --trace N on the CLI)")
                self.trace.add("runtime/unsettled", passes=self.MAX_PASSES,
                               fibers=len(self.fibers), error=self.settle_error)
                raise ContextError(self.settle_error)
            finally:
                self._settling = False

    # -- events ------------------------------------------------------------
    async def emit(self, event: str, *args, **kwargs) -> list:
        """Call every listener for `event`. Sync and async handlers both work.

        A handler that raises is recorded in the trace and does not stop the others. An event
        bus where one bad subscriber can cancel delivery to the rest is a bus that silently
        drops half its traffic the first time a plugin has a bug in it.
        """
        results = []
        for _, handler in list(self.listeners.get(event, ())):
            try:
                got = handler(*args, **kwargs)
                if inspect.isawaitable(got):
                    got = await got
                results.append(got)
            except Exception as exc:                              # noqa: BLE001
                self.trace.add("listener/error", event=event,
                               error=f"{type(exc).__name__}: {exc}")
        return results


class Context:
    """A view onto a `Runtime`, scoped to one fiber's declared dependencies and realms."""

    __slots__ = ("runtime", "fiber", "_inject", "_optional", "_realms", "_intercept")

    def __init__(self, runtime: Runtime, *, fiber=None, inject=(), optional=(),
                 realms=None, intercept=None) -> None:
        self.runtime = runtime
        self.fiber = fiber
        self._inject = frozenset(inject)
        self._optional = frozenset(optional)
        self._realms: dict[str, str] = dict(realms or {})
        self._intercept: dict[str, dict] = dict(intercept or {})

    # -- naming ------------------------------------------------------------
    def _key(self, name: str) -> str:
        """Realm-qualified service key. The default realm is the empty string, so a process
        with no isolation in it has keys that read exactly like the names."""
        return f"{self._realms.get(name, '')}:{name}"

    # -- reading -----------------------------------------------------------
    def get(self, name: str, default=None):
        service = self.runtime.services.get(self._key(name))
        return default if service is None else service.value

    def has(self, name: str) -> bool:
        return self._key(name) in self.runtime.services

    def __contains__(self, name: str) -> bool:
        return self.has(name)

    def __getitem__(self, name: str):
        return self.__getattr__(name)

    def __getattr__(self, name: str):
        """`ctx.llm`. Declared dependencies only, inside a plugin.

        `__getattr__` and not `__getattribute__`: this runs only when normal attribute lookup
        has already failed, so `ctx.runtime`, `ctx.plugin` and the rest cost nothing and a
        service may not be named after one of them. That collision is worth a clear error, and
        `provide` raises one.
        """
        if name.startswith("_"):
            raise AttributeError(name)
        if self.fiber is not None and name not in self._inject and name not in self._optional:
            raise ContextError(
                f"{self.fiber.label} reached for the service {name!r} without declaring it. "
                f"Add `inject = [{name!r}]` to the plugin. It declares "
                f"{sorted(self._inject) or 'nothing'}. "
                f"This is not access control -- it is how the runtime knows to reload this "
                f"plugin when {name!r} changes, and it cannot know from an undeclared use.")
        service = self.runtime.services.get(self._key(name))
        if service is None:
            if name in self._optional:
                return None
            raise ContextError(
                f"the service {name!r} is not provided. Fibers that inject it stay PENDING "
                f"until something provides it, so reaching this line means it was optional "
                f"or the container was read from the root.")
        value = service.value
        overrides = self._intercept.get(name)
        return _Intercepted(value, overrides) if overrides else value

    # -- writing -----------------------------------------------------------
    def provide(self, name: str, value: typing.Any) -> Disposer:
        """Put a service in the container and return the disposer that takes it back out.

        The disposer is also registered as an effect of the calling fiber, so a plugin does not
        have to hold on to it: unloading the plugin removes the service. Keeping the return
        value is for the case where you want to revoke it earlier than that.
        """
        if hasattr(Context, name):
            raise ContextError(
                f"{name!r} is already an attribute of Context, so `ctx.{name}` would never "
                f"reach the container. Pick another name.")
        key = self._key(name)
        existing = self.runtime.services.get(key)
        if existing is not None and existing.owner is not None and existing.owner is not self.fiber:
            raise ContextError(
                f"{name!r} is already provided by {existing.owner.label}. Two live providers "
                f"of one name is not a merge, it is a race -- isolate the name instead: "
                f"`ctx.isolate([{name!r}])`.")
        if existing is None:
            service = Service(key, name, value, self.fiber)
            self.runtime.services[key] = service
        else:
            service = existing
            if service.value is not value:
                service.value = value
                service.epoch += 1      # every dependent is now stale; `settle` restarts them
            service.owner = self.fiber
        self.runtime.trace.add("service/provide", service=name, key=key, epoch=service.epoch,
                               owner=getattr(self.fiber, "id", None))

        def revoke() -> None:
            current = self.runtime.services.get(key)
            if current is service:
                del self.runtime.services[key]
                self.runtime.trace.add("service/revoke", service=name, key=key)

        return self.effect(revoke)

    def effect(self, cleanup: Disposer) -> Disposer:
        """Register arbitrary cleanup with the calling fiber. Returns it, so it can be called
        early; calling it early also removes it from the fiber, so it never runs twice."""
        if self.fiber is None:
            return cleanup          # the root disposes when the process does
        return self.fiber.add_effect(cleanup)

    def on(self, event: str, handler: typing.Callable) -> Disposer:
        """Subscribe, and get the unsubscribe back. Registered as an effect, so a plugin's
        listeners go away with the plugin -- the single most common leak in every event-bus
        plugin system, and the reason `effect` exists at all."""
        self.runtime._listener_counter += 1
        entry = (self.runtime._listener_counter, handler)
        self.runtime.listeners.setdefault(event, []).append(entry)

        def off() -> None:
            bucket = self.runtime.listeners.get(event) or []
            if entry in bucket:
                bucket.remove(entry)

        return self.effect(off)

    async def emit(self, event: str, *args, **kwargs) -> list:
        return await self.runtime.emit(event, *args, **kwargs)

    # -- mounting ----------------------------------------------------------
    def plugin(self, plugin, config=None, *, name: str | None = None):
        """Mount a plugin and return its `Fiber`.

        The fiber comes back immediately and is awaitable: `await ctx.plugin(p)` settles the
        runtime and gives you a fiber whose state is final, while a bare `ctx.plugin(p)` inside
        another plugin's body just queues it -- the settle pass already running will pick it
        up. Both are correct; the first is what you want in a test or a route handler, the
        second is what you want when a plugin mounts its own children.

        A fiber mounted by a plugin is a child of that plugin's fiber and is disposed with it.
        """
        from . import registry
        return registry.mount(self, plugin, config, name=name)

    def inject(self, deps, callback, config=None):
        """`ctx.inject(["llm"], fn)` -- a plugin that is only a dependency declaration.

        Sugar, and used constantly: most of the time what you want is "run this once `llm`
        exists, and unrun it if `llm` goes away", which is a plugin with no body of its own.
        """
        callback.inject = list(deps)
        return self.plugin(callback, config)

    # -- deriving ----------------------------------------------------------
    def extend(self, **fields) -> "Context":
        """A sibling view with some fields replaced. Cheap -- three references and two frozen
        sets. Nothing about the container is copied."""
        base = {"fiber": self.fiber, "inject": self._inject, "optional": self._optional,
                "realms": self._realms, "intercept": self._intercept}
        base.update(fields)
        return Context(self.runtime, **base)

    def isolate(self, names) -> "Context":
        """A view where each of `names` resolves in a private realm.

        This is the session fork. `ctx.isolate(["llm", "memory"])` gives back a context whose
        `llm` is nobody else's `llm`: a plugin mounted on it that provides `llm` writes into
        the private realm, and the process-wide one is neither read nor disturbed. Names not
        listed still resolve to the shared container, which is the point -- a session forks
        what it needs to fork and shares the rest.
        """
        return self.with_realms({name: self.runtime.new_realm(name) for name in names})

    def with_realms(self, mapping: dict) -> "Context":
        """`isolate` with the realm ids supplied rather than minted.

        The loader needs this. `isolate()` mints a new realm on every call, so deriving a
        group's context a second time -- which happens on every manifest re-apply, and on every
        `reload` of a plugin inside a group -- would produce a namespace containing nothing, and
        the children already mounted would be invisible to it. The realm id belongs to the
        manifest entry, not to the call, so the entry keeps it and passes it here.
        """
        return self.extend(realms={**self._realms, **mapping})

    def intercept(self, name: str, **defaults) -> "Context":
        """A view where calls into one service carry default keyword arguments.

        Upstream uses this to give a plugin its own view of, say, an HTTP client with a base
        URL already set. Here it is what lets one preset hand every plugin below it the same
        model or the same temperature without each plugin growing a config field for it:

            child = ctx.intercept("llm", temperature=0.2)
            await child.llm.complete("...")        # temperature=0.2 unless overridden

        A keyword the caller passes explicitly always wins. Only keyword arguments are merged;
        positional ones are passed straight through, because merging by position guesses.
        """
        merged = dict(self._intercept)
        merged[name] = {**merged.get(name, {}), **defaults}
        return self.extend(intercept=merged)

    # -- introspection -----------------------------------------------------
    def services(self) -> dict[str, Service]:
        """Every service this context can see, by plain name. Shadowed realms win, which is
        what a reader of an isolated context expects to be told."""
        out: dict[str, Service] = {}
        for service in self.runtime.services.values():
            if service.key == self._key(service.name):
                out[service.name] = service
        return out

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        who = self.fiber.label if self.fiber else "root"
        return f"<Context {who} inject={sorted(self._inject)}>"


class _Intercepted:
    """The proxy `Context.intercept` hands out. Wraps every callable attribute so the defaults
    are merged in at call time rather than at lookup time -- looking up a method and calling it
    later is normal, and a proxy that only worked for `ctx.svc.method(...)` in one expression
    would be a trap."""

    __slots__ = ("_target", "_defaults")

    def __init__(self, target, defaults: dict) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_defaults", defaults)

    def __getattr__(self, name: str):
        attr = getattr(self._target, name)
        if not callable(attr):
            return attr
        defaults = self._defaults

        def call(*args, **kwargs):
            return attr(*args, **{**defaults, **kwargs})

        return call

    def __call__(self, *args, **kwargs):
        return self._target(*args, **{**self._defaults, **kwargs})

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        return f"<intercepted {self._target!r} {self._defaults}>"
