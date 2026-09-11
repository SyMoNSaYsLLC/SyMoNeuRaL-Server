"""`agent.run()` -- the loop that decides whether a dangerous tool executes.

Until this file existed the loop had no test of its own. That was tolerable while it ran
every tool it was asked for, because there was no decision in it to get wrong. The
permission gate is a decision, so it needs one.

## What is asserted, and what deliberately is not

The frames, the ordering and the arithmetic -- not the model's wording. A test that demanded
a particular sentence back would go red the next time a temperature or an adapter changed,
which is the defect this repo has already fixed once elsewhere: an assertion that fails for
a reason unrelated to the thing it names teaches people to ignore it.

## The fakes

`inference` is replaced wholesale, because a real backend means the GPU and a 7B model
choosing what it likes. The **registry is real**: the gated set has to be the one the
product ships, or this file would be asserting that a fixture agrees with itself. Only
`registry.call` is intercepted, so an executed tool is recorded rather than run -- and
`test_the_registry_under_test_actually_has_gated_tools` fails first if the registry is
empty, since an empty one gates nothing and every assertion below would pass on air.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest import mock

from studio import registry
from studio import studio as routes
from studio.lib import agent

GATED = "run_command"
OPEN = "list_dir"


class FakeBackend:
    """One scripted reply per step. `chat` records the transcript it was handed, which is
    how the resume ordering is checked -- the messages the model sees are the assertion."""

    name = "fake"
    base = "http://fake.test"

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    async def chat(self, messages, tools=None, model=None, temperature=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if self.replies else answer("done")


def answer(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


def calls(*specs) -> dict:
    """An assistant message with native tool calls, in llama.cpp's OpenAI shape."""
    return {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function",
         "function": {"name": n, "arguments": json.dumps(a)}}
        for i, (n, a) in enumerate(specs)]}}]}


class AgentGateTests(unittest.TestCase):
    def setUp(self):
        self.executed: list[tuple[str, dict]] = []

        async def fake_call(name, args):
            self.executed.append((name, dict(args)))
            return {"ok": True, "tool": name}

        patch = mock.patch.object(registry, "call", fake_call)
        patch.start()
        self.addCleanup(patch.stop)

    def drive(self, replies, **kw) -> list[dict]:
        """Run one turn to completion and return its frames."""
        backend = FakeBackend(replies)
        self.backend = backend

        async def go():
            with mock.patch.object(agent, "inference", mock.MagicMock()) as inf:
                async def pick():
                    return backend
                inf.pick = pick
                inf.InferenceError = RuntimeError
                return [f async for f in agent.run("do it", **kw)]
        return asyncio.run(go())

    def test_the_registry_under_test_actually_has_gated_tools(self):
        """The vacuity guard, and it earned its place: `registry.names()` is empty until a
        tool module is imported, `registry.get` returns None for an unknown name, and
        `gated` is False when it does. So an import that stopped populating the registry
        would turn every assertion in this file green while gating nothing at all."""
        gated = sorted(n for n in registry.names() if registry.get(n).dangerous)
        self.assertIn(GATED, gated)
        self.assertNotIn(OPEN, gated)
        self.assertGreaterEqual(len(gated), 4, f"only {gated} are flagged dangerous")

    def test_ask_stops_the_turn_and_runs_nothing(self):
        frames = self.drive([calls((GATED, {"cmd": "rm -rf /"})), answer("unreachable")],
                            permissions="ask")
        kinds = [f["event"] for f in frames]
        self.assertEqual(kinds, ["backend", "permission_required", "done"])
        self.assertEqual(self.executed, [], "a gated tool ran while asking about it")
        self.assertNotIn("tool_call", kinds,
                         "a tool_call frame for something that never ran would put it in "
                         "the transcript a reader believes")
        self.assertTrue(frames[-1]["awaiting_permission"])
        self.assertEqual(frames[-1]["tools_used"], 0)

    def test_the_gate_frame_carries_what_a_caller_needs_to_resume(self):
        """`arguments` so the prompt can display the real call, `call_id` so the result can
        be tied back to it, and `pending` so the resumed transcript contains the assistant
        message that made the call. Without `pending` the model is handed a result for a
        call it cannot see."""
        frames = self.drive([calls((GATED, {"cmd": "ls"}))], permissions="ask")
        ask = frames[1]
        self.assertEqual(ask["name"], GATED)
        self.assertEqual(ask["arguments"], {"cmd": "ls"})
        self.assertEqual(ask["call_id"], "c0")
        self.assertIn("dangerous", ask["reason"])
        self.assertEqual([m["role"] for m in ask["pending"]], ["assistant"])
        self.assertTrue(ask["pending"][0].get("tool_calls"))

    def test_the_calls_after_a_gated_one_are_named_and_not_run(self):
        """The model chose them as a set. Running the tail of a set whose head was never
        approved is a decision nobody made -- but dropping them silently would lose a tool
        the model asked for with nothing on screen to say so."""
        frames = self.drive([calls((GATED, {"cmd": "ls"}), (OPEN, {"path": "."}),
                                   ("read_file", {"path": "x"}))], permissions="ask")
        self.assertEqual(frames[1]["dropped"], [OPEN, "read_file"])
        self.assertEqual(self.executed, [])

    def test_an_open_tool_before_a_gated_one_still_runs_and_its_result_is_handed_back(self):
        """The gate stops the turn at the gated call, not before it. Work already done has
        to travel in `pending`, or resuming discards a completed tool call and the model
        repeats it."""
        frames = self.drive([calls((OPEN, {"path": "."}), (GATED, {"cmd": "ls"}))],
                            permissions="ask")
        self.assertEqual([n for n, _ in self.executed], [OPEN])
        pending = frames[-2]["pending"]
        self.assertEqual([m["role"] for m in pending], ["assistant", "tool"])
        self.assertEqual(pending[1]["name"], OPEN)
        self.assertEqual(frames[-1]["tools_used"], 1, "the open tool did run and counts")

    def test_deny_completes_the_turn_and_tells_the_model_it_was_refused(self):
        """With nobody to ask, the turn must finish rather than hang: the tool is refused,
        the refusal goes back as the tool's result, and the model answers around it."""
        frames = self.drive([calls((GATED, {"cmd": "ls"})), answer("I could not run that.")],
                            permissions="deny")
        kinds = [f["event"] for f in frames]
        self.assertEqual(kinds, ["backend", "tool_call", "tool_result", "answer", "done"])
        self.assertEqual(self.executed, [])
        self.assertTrue(frames[1]["gated"], "the tool_call frame must say it was gated")
        self.assertEqual(frames[2]["result"]["error"], "not_permitted")
        self.assertIn("Do not retry", frames[2]["result"]["detail"])

    def test_a_refused_tool_is_not_counted_as_a_used_one(self):
        """`tools_used` reads as "the card and the filesystem were touched this many times".
        Counting a denial in it inflates the one figure somebody would check against."""
        frames = self.drive([calls((GATED, {"cmd": "ls"})), answer("no")],
                            permissions="deny")
        self.assertEqual(frames[-1]["tools_used"], 0)

    def test_allow_is_the_documented_default_and_runs_the_tool(self):
        """Stated as a test because it is a security-relevant default: a caller that says
        nothing gets the pre-gate behaviour. That is deliberate -- the browser surface was
        working before the gate existed and a silent default of `deny` would have broken it
        -- but it must be a decision this file records, not an accident nobody re-reads."""
        for kw in ({}, {"permissions": "allow"}):
            with self.subTest(kw=kw):
                self.executed.clear()
                self.drive([calls((GATED, {"cmd": "ls"})), answer("ok")], **kw)
                self.assertEqual(self.executed, [(GATED, {"cmd": "ls"})])

    def test_an_exempted_tool_is_not_gated_and_the_exemption_is_that_tool_only(self):
        frames = self.drive([calls((GATED, {"cmd": "ls"})), answer("ok")],
                            permissions="ask", allow=[GATED])
        self.assertEqual(self.executed, [(GATED, {"cmd": "ls"})])
        self.assertNotIn("permission_required", [f["event"] for f in frames])

        self.executed.clear()
        frames = self.drive([calls(("write_file", {"path": "x", "content": "y"}))],
                            permissions="ask", allow=[GATED])
        self.assertEqual(self.executed, [])
        self.assertEqual(frames[1]["event"], "permission_required")
        self.assertEqual(frames[1]["name"], "write_file")

    def test_resume_goes_after_the_user_query_and_history_goes_before_it(self):
        """The two cannot be one list. History is what was said before the question; a
        resumed tool call is what happened after it. Merging them puts the tool result
        ahead of the query it was needed for, and the model answers the wrong question."""
        self.drive([answer("fine")],
                   history=[{"role": "user", "content": "earlier"},
                            {"role": "assistant", "content": "sure"}],
                   resume=[{"role": "assistant", "content": "", "tool_calls": [{"id": "c0"}]},
                           {"role": "tool", "name": GATED, "tool_call_id": "c0",
                            "content": "{}"}])
        seen = self.backend.seen[0]
        roles = [m["role"] for m in seen]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant", "tool"])
        self.assertEqual(seen[1]["content"], "earlier")
        self.assertEqual(seen[3]["content"], "do it", "the query must sit between them")

    def test_a_resumed_segment_counts_its_own_steps_from_zero(self):
        """It is a new call, so `steps` is this segment's. A caller that wants the whole
        turn adds them up; a loop that pretended to continue a count it never saw would be
        reporting a number it made up."""
        frames = self.drive([answer("carried on")],
                            resume=[{"role": "tool", "name": GATED, "content": "{}"}])
        self.assertEqual(frames[-1]["steps"], 1)


class ModeValidationTests(unittest.TestCase):
    """Both layers refuse an unrecognised mode, and they have to, because the gate is written
    as `permissions in ("ask", "deny")` -- so a string neither layer recognises would fall
    through it and run exactly like `allow`. Failing open on a typo is the one outcome a
    permission system may not have, so it is checked at the loop AND at the endpoint rather
    than at whichever one happens to be in front."""

    def test_the_loop_refuses_an_unknown_mode_instead_of_reading_it_as_allow(self):
        """`run()` used to take the string on trust, which left the endpoint's 400 as the only
        thing between a typo and an ungated run. It is a backstop now, not the whole check:
        `routes` is the only production caller today, and this is what keeps the next one
        honest. Note what is asserted -- not merely that the gated tool did not run, but that
        nothing ran and no backend was even picked, because a refusal that still burns a turn
        has not refused it."""
        executed: list[str] = []

        async def fake_call(name, args):
            executed.append(name)
            return {"ok": True}

        backend = FakeBackend([calls((GATED, {"cmd": "ls"})), answer("ok")])

        async def go():
            with mock.patch.object(registry, "call", fake_call), \
                 mock.patch.object(agent, "inference", mock.MagicMock()) as inf:
                async def pick():
                    return backend
                inf.pick = pick
                inf.InferenceError = RuntimeError
                return [f async for f in agent.run("do it", permissions="asK")]

        frames = asyncio.run(go())
        self.assertEqual(executed, [], "an unrecognised mode ran a dangerous tool")
        self.assertEqual([f["event"] for f in frames], ["error"],
                         "the turn should stop on the mode, before a backend is picked")
        self.assertEqual(frames[0]["code"], "bad_permissions")
        self.assertEqual(frames[0]["got"], "asK",
                         "the rejected spelling has to come back, or a caller cannot tell "
                         "which of its arguments was wrong")
        self.assertEqual(backend.seen, [], "the model was asked despite the bad mode")

    def test_every_mode_the_loop_accepts_is_a_mode_the_endpoint_accepts(self):
        """The two layers read one tuple. This is the assertion that makes that true rather
        than merely intended: add a fourth mode to `PERMISSION_MODES` and the case list in
        the test below stops covering it, which fails here instead of shipping a mode nobody
        exercised."""
        self.assertEqual(set(agent.PERMISSION_MODES), {"allow", "deny", "ask"},
                         "PERMISSION_MODES changed -- add the new spelling to the case list "
                         "in test_the_endpoint_refuses_an_unrecognised_mode_with_a_400")
        # Comments stripped first. The sentence in `routes.py` explaining that it reads this
        # tuple names the tuple, so a plain substring search over the raw text is satisfied by
        # the prose alone: this assertion passed with the literal tuple reinstated until the
        # strip went in. Second rule in this repo to be satisfied by its own explanation.
        src = (Path(__file__).parent / "routes.py").read_text()
        code = "\n".join(line.split("#")[0] for line in src.splitlines())
        self.assertIn("agent.PERMISSION_MODES", code,
                      "routes.py must validate against the loop's tuple, not a second copy "
                      "of it that can drift out of agreement with the gate")

    def test_the_endpoint_refuses_an_unrecognised_mode_with_a_400(self):
        """The other half, driven rather than grepped: `run_agent` must reject the typo
        before the loop ever sees it. Every accepted spelling is checked too -- a validator
        that refuses everything would satisfy the assertion above and break the product."""
        for mode, status in (("asK", 400), ("yes", 400), ("", 200), ("allow", 200),
                             ("deny", 200), ("ask", 200)):
            with self.subTest(mode=mode):
                response = asyncio.run(_post({"query": "hi", "permissions": mode}))
                self.assertEqual(response.status_code, status)
                if status == 400:
                    body = json.loads(bytes(response.body))
                    self.assertEqual(body["error"], "bad_permissions")
                    self.assertEqual(body["got"], mode)


class FakeRequest:
    """Enough of a Starlette request for `_guard` and the body read. Constructed rather than
    mocked so that a signature change in the handler shows up here as a failure instead of a
    silently permissive MagicMock."""

    def __init__(self, payload: dict, token: str):
        self._payload = payload
        self.headers = {routes.HEADER: token}
        self.query_params: dict = {}
        self.cookies: dict = {}
        self.client = type("C", (), {"host": "127.0.0.1"})()

    async def json(self):
        return self._payload

    async def body(self):
        return json.dumps(self._payload).encode()

    async def is_disconnected(self):
        return False


async def _post(payload: dict):
    import os
    env = {"SYMONEURAL_STUDIO_ENABLED": "1", "SYMONEURAL_STUDIO_TOKEN": "test-token"}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return await routes.run_agent(FakeRequest(payload, "test-token"))
    finally:
        for k, v in saved.items():
            os.environ[k] = v if v is not None else ""
            if v is None:
                os.environ.pop(k, None)


if __name__ == "__main__":
    unittest.main()
