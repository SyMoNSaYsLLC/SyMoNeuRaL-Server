"""A background task, and the effect that stops it.

This is the plugin to copy when your plugin owns something that keeps running: a task, a
socket, a watcher, a subprocess. The pattern is three lines and the third one is the one people
forget:

    task = asyncio.create_task(loop())
    ctx.effect(task.cancel)          # <- without this, unmount leaks a running task

An unmount that leaves the task running is the failure that makes hot-reload useless: reload
five times and you have five tickers publishing to a bus that only one of them believes it
owns. `ctx.effect` is how you make unmount mean it.
"""
from __future__ import annotations

import asyncio
import contextlib

name = "clock"
inject = ["bus"]
schema = {"interval": (float, 1.0), "topic": (str, "tick")}


async def apply(ctx, config):
    interval, topic = config["interval"], config["topic"]
    state = {"ticks": 0}

    async def run():
        while True:
            await asyncio.sleep(interval)
            state["ticks"] += 1
            ctx.bus.publish(topic, {"n": state["ticks"], "interval": interval})

    task = asyncio.create_task(run())

    async def stop():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    ctx.effect(stop)
    ctx.provide("clock", state)
