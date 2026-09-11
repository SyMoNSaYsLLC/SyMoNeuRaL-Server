"""The class form, and an optional dependency.

A class plugin is instantiated with `(ctx, config)` and the instance is held alive by the fiber
until it unmounts -- which is what a class plugin is for: state whose lifetime is exactly the
mount. `stop()` (or `dispose()`) is picked up as an effect automatically, so this file has no
explicit `ctx.effect` call in it.

`inject` uses the dict form. `bus` is required, so the fiber sits PENDING until something
provides one. `memory` is optional: if a memory service is mounted this plugin persists into
it, and if it is not, it keeps its own list and works fine. That distinction is the reason the
dict form exists -- "I use it if it is there" is a real relationship, and forcing it to be
required would mean this plugin refuses to start on a box with no memory plugin for no reason.
"""
from __future__ import annotations

name = "recorder"
inject = {"required": ["bus"], "optional": ["memory"]}
schema = {"topic": (str, "tick"), "keep": (int, 100)}


class Recorder:
    def __init__(self, ctx, config) -> None:
        self.ctx = ctx
        self.keep = config["keep"]
        self.topic = config["topic"]
        self.seen: list = []
        self.unsubscribe = ctx.bus.subscribe(self.topic, self.record)

    @property
    def memory(self):
        # `get` rather than attribute access: an optional dependency is allowed to be absent,
        # and `ctx.memory` would raise on the box where it is.
        return self.ctx.get("memory")

    def record(self, payload) -> None:
        self.seen.append(payload)
        del self.seen[:-self.keep]
        memory = self.memory
        if memory is not None:
            # One key, overwritten -- not one key per event. An unbounded writer against a
            # bounded store fails eventually and by surprise: `Memory` raises at its limit, the
            # raise travels back through `bus.publish` into the clock's task, and the task dies
            # roughly half an hour after anyone stopped watching. `seen` is the bounded history;
            # memory holds the latest.
            memory.put(f"{self.topic}:latest", payload)

    def stop(self) -> None:
        self.unsubscribe()


#: What the loader mounts for `use: studio.plugins.exp.plugins.recorder`. The class *is* the
#: plugin; `registry.resolve` sees a class behind `apply` and takes the class path, so `stop()`
#: below is registered as an effect without this file asking for it.
apply = Recorder
