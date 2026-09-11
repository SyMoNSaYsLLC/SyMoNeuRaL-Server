"""A key-value store, and the clearest case for `isolate`.

Mounted once at the top level, every plugin shares one memory. Mounted inside a group that says
`isolate: [memory]`, each group gets its own and neither can see the other's -- same plugin,
same code, no configuration flag, no namespacing inside the plugin. The forking happens in the
container, which is the whole argument for a container.

    - id: session-a
      isolate: [memory]
      plugins:
        - {id: a.memory, use: studio.plugins.exp.plugins.memory}
    - id: session-b
      isolate: [memory]
      plugins:
        - {id: b.memory, use: studio.plugins.exp.plugins.memory}
"""
from __future__ import annotations

name = "memory"
schema = {"limit": (int, 1000)}


class Memory:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.data: dict = {}
        self.writes = 0

    def put(self, key, value):
        if len(self.data) >= self.limit and key not in self.data:
            raise KeyError(f"memory full at {self.limit} keys")
        self.data[key] = value
        self.writes += 1
        return value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def keys(self):
        return sorted(self.data)


def apply(ctx, config):
    ctx.provide("memory", Memory(config["limit"]))
