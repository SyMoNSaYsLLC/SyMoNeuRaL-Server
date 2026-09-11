"""A plugin that fails, on purpose, so failure has a worked example.

Three modes, because they fail at three different points and the runtime handles each
differently:

    mode: body       raises inside the body. The effects it registered first are disposed,
                     the fiber is FAILED, the traceback is on it, and nothing else stops.
    mode: undeclared reaches for a service it did not declare. `Context.__getattr__` raises
                     with the `inject = [...]` line it should have written.
    mode: config     is mounted with a config key its schema does not accept. That one fails
                     in `check_config`, before the body runs at all, and the message lists
                     every problem rather than the first.

The point of shipping this is that "my plugin does nothing" is the most common report a plugin
system gets, and the answer is almost always that it is FAILED with a traceback nobody looked
at. `GET /api/exp/plugins` shows it. So does the page.
"""
from __future__ import annotations

name = "explode"
schema = {"mode": (str, "body")}


def apply(ctx, config):
    mode = config["mode"]
    ctx.effect(lambda: None)                  # registered before the raise, disposed after it
    if mode == "undeclared":
        return ctx.bus                        # not in `inject`
    raise RuntimeError(f"explode({mode}) -- this plugin fails deliberately; see its docstring")
