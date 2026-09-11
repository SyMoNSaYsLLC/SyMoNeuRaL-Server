"""A stand-in `llm` service -- and the reason `ctx.intercept` exists.

It does not call a model. It echoes, deterministically, so a test can assert on the result and
a preset can be exercised on a box with no GPU lease available. The real inference path in this
repo is `apps/studio/inference.py`, behind the governor; a plugin wanting that should
provide a service wrapping it rather than duplicating it.

What this file demonstrates is the call surface. `complete()` takes `temperature` and `model`
as keyword arguments with defaults, which is precisely the shape `intercept` shapes:

    child = ctx.intercept("llm", temperature=0.2)
    await child.llm.complete("hello")        # temperature=0.2, without asking the plugin

A group in a manifest does the same thing declaratively:

    - id: careful
      intercept: {llm: {temperature: 0.0}}
      plugins: [...]
"""
from __future__ import annotations

name = "echo_llm"
schema = {"model": (str, "echo"), "prefix": (str, "")}


class EchoLLM:
    def __init__(self, model: str, prefix: str) -> None:
        self.model = model
        self.prefix = prefix
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, temperature: float = 0.7,
                       model: str | None = None) -> dict:
        record = {"prompt": prompt, "temperature": temperature, "model": model or self.model}
        self.calls.append(record)
        return {**record, "text": f"{self.prefix}{prompt[::-1]}"}


def apply(ctx, config):
    ctx.provide("llm", EchoLLM(config["model"], config["prefix"]))
