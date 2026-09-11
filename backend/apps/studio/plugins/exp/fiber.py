"""One mounted plugin instance, and its whole life.

A `Fiber` is what `ctx.plugin(...)` gives back. It owns:

* the `Context` the plugin body was handed,
* the list of effects that body registered, in order,
* the epochs of the services it started against,
* its children -- fibers the plugin mounted itself,
* its state, and the exception if it has one.

## States

    PENDING    declared dependencies are not all provided yet. Not an error and not a
               failure: a plugin that injects `llm` before anything provides `llm` waits
               here, and starts by itself the moment one appears.
    LOADING    the body is running. Visible because an async plugin body can take real time
               and a UI showing nothing during it would be lying by omission.
    ACTIVE     the body returned. Its effects are live.
    FAILED     the body raised. The effects it managed to register before raising have been
               disposed -- a half-mounted plugin is the one state this runtime will not leave
               anything in.
    DISPOSING  effects are being run down.
    DISPOSED   nothing of it remains in the container.

A fiber moves PENDING -> LOADING -> ACTIVE and back to PENDING when a dependency goes away,
which is the whole reactive story: nothing here polls, `Runtime.settle()` is called after any
change and asks each fiber to reconcile itself.

## Why effects run in reverse

Registration order is dependency order -- a plugin provides a service and then subscribes a
listener that uses it. Disposing forward would revoke the service while the listener could
still fire. Reverse is not a style choice; it is the only order that cannot tear down
something still in use, and it is the same reason `contextlib.ExitStack` unwinds the way it
does.

## Failure is recorded, not raised

A plugin body that raises does not propagate the exception into whoever called `ctx.plugin()`.
The mounting code is usually the loader working through a manifest, and one bad entry must not
stop the other eleven. The exception is kept on the fiber, written to the trace, and reported
by `GET /api/exp/plugins`. This is deliberate and it is the one thing to remember when a
plugin "does nothing": look at its state, it is probably FAILED and the traceback is right
there.
"""
from __future__ import annotations

import inspect
import traceback
import typing

from .context import Context, ContextError

__all__ = ["Fiber", "PENDING", "LOADING", "ACTIVE", "FAILED", "DISPOSING", "DISPOSED"]

PENDING = "pending"
LOADING = "loading"
ACTIVE = "active"
FAILED = "failed"
DISPOSING = "disposing"
DISPOSED = "disposed"


class Fiber:
    """The lifecycle handle. Awaitable: `await ctx.plugin(p)` settles and returns it."""

    _counter = 0

    def __init__(self, parent: Context, runner, config, *, label: str) -> None:
        Fiber._counter += 1
        self.id = f"f{Fiber._counter}"
        self.label = label
        self.runner = runner                    # a registry.Runner -- see registry.py
        self.config = config
        self.parent = parent
        self.runtime = parent.runtime
        self.state = PENDING
        self.error: str | None = None
        self.effects: list[typing.Callable] = []
        self.children: list[Fiber] = []
        self.epochs: dict[str, int] = {}
        self.started_at: float | None = None
        self.reloads = 0
        self.ctx = parent.extend(fiber=self,
                                 inject=runner.required, optional=runner.optional)
        if parent.fiber is not None:
            parent.fiber.children.append(self)
        self.runtime.fibers.append(self)
        self.runtime.trace.add("fiber/create", fiber=self.id, plugin=self.label,
                               inject=sorted(runner.required))

    # -- readiness ---------------------------------------------------------
    def missing(self) -> list[str]:
        """Declared-and-required services that are not in the container. The UI shows this
        verbatim, because "waiting for llm" is a complete explanation and "pending" is not."""
        return sorted(n for n in self.runner.required if not self.ctx.has(n))

    def stale(self) -> bool:
        """True when a service this fiber started against has since been replaced.

        Compares against the epochs recorded at start. A service revoked entirely is handled by
        `missing()` instead, which sends the fiber back to PENDING rather than restarting it --
        restarting into a dependency that is gone would just fail.
        """
        for name, epoch in self.epochs.items():
            service = self.runtime.services.get(self.ctx._key(name))
            if service is not None and service.epoch != epoch:
                return True
        return False

    # -- transitions -------------------------------------------------------
    async def _reconcile(self) -> bool:
        """One settle pass, for this fiber. Returns whether anything changed."""
        if self.state in (DISPOSING, DISPOSED):
            return False
        if self.state == PENDING and not self.missing():
            await self._start()
            return True
        if self.state == ACTIVE and self.missing():
            await self._unwind(PENDING)
            return True
        if self.state == ACTIVE and self.stale():
            self.reloads += 1
            await self.runtime.emit("hmr/reload", self, "service-changed")
            await self._unwind(PENDING)
            await self._start()
            return True
        return False

    async def _start(self) -> None:
        import time
        self.state = LOADING
        self.error = None
        self.epochs = {}
        for name in list(self.runner.required) + list(self.runner.optional):
            service = self.runtime.services.get(self.ctx._key(name))
            if service is not None:
                self.epochs[name] = service.epoch
        self.runtime.trace.add("fiber/start", fiber=self.id, plugin=self.label)
        try:
            result = self.runner.call(self.ctx, self.config)
            if inspect.isawaitable(result):
                result = await result
            # A body may return its own disposer, the way a plugin that wires up something
            # outside this container naturally would. Accepted rather than ignored: ignoring
            # it silently is how a plugin author discovers, much later, that their cleanup was
            # never going to run.
            if callable(result):
                self.add_effect(result)
        except Exception as exc:                                  # noqa: BLE001
            self.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            detail = traceback.format_exc()
            # Everything it registered before raising comes back out -- children first, then
            # effects, the same order `_unwind` uses and for the same reason. A plugin that
            # called `ctx.plugin(child)` and then raised would otherwise end up FAILED with an
            # ACTIVE child nothing holds a handle to: unreachable, never disposed, and still
            # providing services into the container under a dead parent.
            for child in list(self.children):
                await child.dispose()
            self.children.clear()
            await self._dispose_effects()
            self.state = FAILED
            self.runtime.trace.add("fiber/fail", fiber=self.id, plugin=self.label,
                                   error=self.error, traceback=detail)
            await self.runtime.emit("internal/plugin", self, "failed")
            return
        self.state = ACTIVE
        self.started_at = time.time()
        self.runtime.trace.add("fiber/active", fiber=self.id, plugin=self.label,
                               effects=len(self.effects))
        await self.runtime.emit("internal/plugin", self, "active")

    def dependents(self) -> list["Fiber"]:
        """Active fibers that started against a service this one provides.

        Compared by realm-qualified key, not by plain name. Comparing names would make two
        isolated sessions each other's dependents -- disposing session A's `bus` provider would
        unwind session B's consumer, which shares nothing with it but a string. That is the bug
        that makes `isolate()` decorative, and it is invisible in any test with one session in
        it.

        Ownership is single -- `Context.provide` refuses a second live provider for a key -- so
        this walk cannot loop through two fibers that provide for each other, and the `seen` set
        in `_unwind` covers the diamond case where two dependents share a third.

        Known gap: a fiber still LOADING (an async body mid-await) has recorded its epochs but
        is not matched here, so it is not unwound ahead of its provider. Its own `_reconcile`
        catches it on the next pass.
        """
        mine = {s.key for s in self.runtime.services.values() if s.owner is self}
        if not mine:
            return []
        return [f for f in self.runtime.fibers
                if f is not self and f.state == ACTIVE
                and mine & {f.ctx._key(n) for n in f.epochs}]

    def rebind(self, runner) -> None:
        """Point the fiber at a freshly resolved plugin. Called by the loader between
        `importlib.reload` and `restart`.

        Without this, hot-reload is a lie -- and it is the specific lie a plugin runtime cannot
        afford. `restart()` calls `self.runner.call`, which is the function object captured when
        the fiber was created; reloading the module rebinds the name inside the module and
        leaves this fiber holding the previous object. The trace would say `hmr/reload`, the
        table would say reloaded, and the code that ran would be the old code.

        Three things move, not one, because a reloaded module may have changed any of them:
        the callable, the `schema` (so the config is re-checked), and `inject` (so the context's
        declared access is rebuilt). The fiber id does not move, which is the point -- a UI row
        or a route handler holding this fiber keeps pointing at the same thing.
        """
        from . import registry
        self.runner = runner
        try:
            self.config = registry.check_config(runner, self.config)
        except ContextError as exc:
            self.state = FAILED
            self.error = str(exc)
            self.runtime.trace.add("fiber/fail", fiber=self.id, plugin=self.label,
                                   error=str(exc), phase="rebind")
            return
        self.label = runner.label
        self.ctx = self.parent.extend(fiber=self, inject=runner.required,
                                      optional=runner.optional)
        self.runtime.trace.add("fiber/rebind", fiber=self.id, plugin=self.label,
                               inject=sorted(runner.required))

    async def _unwind(self, to: str, _seen: set | None = None) -> None:
        """Run the effects down and leave the fiber in `to` (PENDING for a reload, DISPOSED
        for a real unload).

        Three things go first, and the order is the whole point of this method:

        1. **Fibers that depend on this one.** Without this step there is a window in which a
           consumer is still ACTIVE while the service it started against has already been
           revoked -- the settle pass would notice and send it to PENDING, but only *after*.
           Reverse-order teardown is worthless if it only holds within one plugin: without
           this step the trace reads `bus gone` before `consumer gone`, which is the order a
           consumer's own cleanup cannot survive.
        2. **Children.** A fiber the plugin mounted itself registered its effects after its
           parent's and may depend on them.
        3. **This fiber's own effects**, in reverse registration order.
        """
        seen = _seen if _seen is not None else set()
        if self.id in seen:
            return
        seen.add(self.id)
        for dependent in self.dependents():
            await dependent._unwind(PENDING, seen)

        previous, self.state = self.state, DISPOSING
        for child in list(self.children):
            await child.dispose()
        self.children.clear()
        await self._dispose_effects()
        self.state = to
        self.epochs = {}
        self.started_at = None
        self.runtime.trace.add("fiber/unwind", fiber=self.id, plugin=self.label,
                               was=previous, now=to)
        await self.runtime.emit("internal/plugin", self, to)

    async def _dispose_effects(self) -> None:
        while self.effects:
            cleanup = self.effects.pop()          # reverse order -- see the module docstring
            try:
                got = cleanup()
                if inspect.isawaitable(got):
                    await got
            except Exception as exc:              # noqa: BLE001
                # A cleanup that raises must not strand the ones under it. This is the failure
                # mode that makes hot-reload untrustworthy in most plugin systems: one bad
                # disposer and the rest of the teardown never happens.
                self.runtime.trace.add("effect/error", fiber=self.id, plugin=self.label,
                                       error=f"{type(exc).__name__}: {exc}")

    # -- public ------------------------------------------------------------
    def add_effect(self, cleanup: typing.Callable) -> typing.Callable:
        if self.state in (DISPOSING, DISPOSED):
            raise ContextError(f"{self.label} registered an effect while unloading")
        self.effects.append(cleanup)

        def run_once():
            # The removal is the guard, so it has to gate the call as well. Removing and then
            # calling unconditionally means a plugin that disposes its own service early and is
            # then unloaded runs that cleanup twice -- and a cleanup written to be run once
            # (closing a socket, releasing a lease, decrementing a counter) is exactly the kind
            # that misbehaves the second time.
            if cleanup not in self.effects:
                return None
            self.effects.remove(cleanup)
            return cleanup()

        return run_once

    async def dispose(self) -> None:
        """Unload for good. Idempotent."""
        if self.state == DISPOSED:
            return
        await self._unwind(DISPOSED)
        if self in self.runtime.fibers:
            self.runtime.fibers.remove(self)
        await self.runtime.settle()     # something that injected this fiber's services is now
                                        # missing a dependency and needs to hear about it

    async def restart(self, config=None) -> "Fiber":
        """Unload and load again, optionally with new config. The fiber object survives, so a
        route handler or a UI row holding a reference keeps pointing at the same thing.

        Refused on a disposed fiber rather than quietly doing nothing. `dispose` takes the fiber
        out of `runtime.fibers`, so no settle pass will ever look at it again: a restart unwinds
        nothing, mounts nothing, leaves the state at DISPOSED, increments `reloads`, and hands
        back a fiber that answers every question as though it had worked. That is how
        `POST /reload` came to return 200 for a no-op. What outlives a dispose is the *entry*, so
        the fix is to mount that again -- which is what `Loader.reload` and `Loader.patch` now
        do when they find a disposed fiber, rather than calling this and getting the error.
        """
        if self.state in (DISPOSING, DISPOSED):
            raise ContextError(
                f"{self.label} is {self.state} and cannot be restarted -- a disposed fiber is "
                f"no longer in the runtime's list, so nothing would start it. Mount the entry "
                f"again instead.")
        if config is not None:
            self.config = config
        self.reloads += 1
        if self.state in (ACTIVE, FAILED):
            await self._unwind(PENDING)
        await self.runtime.emit("hmr/reload", self, "requested")
        await self.runtime.settle()
        return self

    def snapshot(self) -> dict:
        """What the API and the page show. Config is *not* in here -- see `routes.py`, which
        adds it only for a request that presented the token, because a plugin's config can
        carry a credential and the plugin list is a public read.

        `reloads` counts explicit restarts and service-changed reloads. It does *not* count the
        ACTIVE -> PENDING -> ACTIVE round trip a fiber makes when a dependency is briefly
        revoked and provided again, because from that fiber's side nothing was reloaded: it
        waited."""
        return {
            "id": self.id,
            "plugin": self.label,
            "state": self.state,
            "inject": sorted(self.runner.required),
            "optional": sorted(self.runner.optional),
            "missing": self.missing(),
            "provides": sorted(s.name for s in self.runtime.services.values()
                               if s.owner is self),
            "effects": len(self.effects),
            "children": [c.id for c in self.children],
            "reloads": self.reloads,
            "started_at": self.started_at,
            "error": self.error,
        }

    def __await__(self):
        async def wait():
            await self.runtime.settle()
            return self
        return wait().__await__()

    def __repr__(self) -> str:      # pragma: no cover -- debugging aid
        return f"<Fiber {self.id} {self.label} {self.state}>"
