"""A pub/sub service. The smallest complete plugin: provide one thing, clean it up.

    plugins:
      - id: bus
        use: apps.studio.plugins.exp.plugins.bus

`ctx.provide` returns a disposer and registers it as an effect, so unmounting this plugin
revokes `bus` and -- because `Fiber._unwind` unwinds dependents first -- every plugin that
started against it is already down by the time that happens.
"""
from __future__ import annotations

import collections
import typing

name = "bus"
schema = {"history": (int, 50)}


class Bus:
    """Topic -> subscribers, plus a bounded backlog so a late subscriber can catch up."""

    def __init__(self, history: int) -> None:
        self.subscribers: dict[str, list[typing.Callable]] = {}
        self.log: collections.deque = collections.deque(maxlen=history)
        self.published = 0

    def subscribe(self, topic: str, handler: typing.Callable) -> typing.Callable:
        self.subscribers.setdefault(topic, []).append(handler)

        def unsubscribe() -> None:
            if handler in self.subscribers.get(topic, ()):
                self.subscribers[topic].remove(handler)
        return unsubscribe

    def publish(self, topic: str, payload) -> int:
        self.published += 1
        self.log.append((topic, payload))
        delivered = 0
        for handler in list(self.subscribers.get(topic, ())):
            handler(payload)
            delivered += 1
        return delivered

    def recent(self, limit: int = 20) -> list:
        return list(self.log)[-limit:]

    def stats(self) -> dict:
        return {"published": self.published,
                "topics": sorted(self.subscribers),
                "backlog": len(self.log)}


def apply(ctx, config):
    bus = Bus(config["history"])
    ctx.provide("bus", bus)
