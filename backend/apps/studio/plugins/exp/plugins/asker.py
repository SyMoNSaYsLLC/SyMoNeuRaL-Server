"""A plugin that consumes a service instead of providing one, so `intercept` has something to act
on.

Every other example in this directory provides something. This one *injects* `llm` and calls it,
which is the shape `ctx.intercept` exists to bend: mounted under a group that declares
`intercept: {llm: {temperature: 0.0}}`, that keyword arrives in the call this file makes without
this file naming it, asking for it, or being able to see that it happened. Mounted anywhere else,
the identical code gets `EchoLLM.complete`'s own default of 0.7.

`test_exp.py::InterceptTests` demonstrated that with its own local fixtures before this file
existed, and still does. What was missing was a consumer in `plugins/`, which meant the mechanism
was only ever visible from inside the test file: `presets/sessions.yaml` declared an interception
with nothing under it to intercept, and the header of that file said so -- "declared here and
inert here".

One call is made at mount time, deliberately. A plugin that only *stores* the injected service
demonstrates nothing until somebody drives it from the API, and `presets/sessions.yaml` is read
far more often than it is run. `answers[0]["temperature"]` is therefore the reading, and it is
0.7 under `session-a` and 0.0 under `session-b` of that one manifest -- measured, and asserted by
`test_exp.py::InterceptTests::test_the_sessions_preset_shows_both_sides_of_one_declaration`.
"""
from __future__ import annotations

name = "asker"
inject = ["llm"]
schema = {"prompt": (str, "hello")}


class Asker:
    def __init__(self, llm, prompt: str) -> None:
        self.llm = llm
        self.prompt = prompt
        self.answers: list[dict] = []

    async def ask(self, prompt: str | None = None) -> dict:
        # No `temperature=` here, on purpose, and this is the point of the file. Whatever the
        # group intercepted is what the `llm` service receives; `EchoLLM.complete` puts what it
        # was given into its reply, so `POST /api/exp/call` on this service shows the
        # interception rather than only asserting it. Checked: with `sessions` mounted, that
        # route answers `"temperature": 0.7` for the `session-a` asker and `0.0` for the
        # `session-b` one. Both readings are quoted in the preset's header.
        answer = await self.llm.complete(prompt or self.prompt)
        self.answers.append(answer)
        return answer


async def apply(ctx, config):
    asker = Asker(ctx.llm, config["prompt"])
    await asker.ask()
    ctx.provide("asker", asker)
