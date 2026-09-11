"""Tests for the multi-coder session surface (R-184).

The interesting assertions are the ones about what the code REFUSES to do: merge answers,
drop a failed coder, call one answer a consensus, or let an unproven adapter be offered.
Those are the requirement; a passing fan-out is only the easy half.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import unittest
import unittest.mock
import os

from coders import (Answer, PRESETS, agreement, preset_rows, provider_map, providers,
               _normalise, CODER_IDS)


def A(cid, text="", state="completed", error=""):
    return Answer(cid, cid.title(), state, text=text, error=error)


class AgreementTests(unittest.TestCase):
    def test_identical_answers_agree(self):
        r = agreement([A("symon", "1,2,3"), A("claude", "1,2,3"), A("codex", "1,2,3")])
        self.assertTrue(r["agree"])
        self.assertEqual(r["distinct"], 1)

    def test_whitespace_is_not_disagreement(self):
        r = agreement([A("symon", "1, 2, 3"), A("claude", " 1,  2,\n3 ")])
        self.assertTrue(r["agree"])

    def test_separator_spacing_is_not_disagreement(self):
        # REGRESSION, found by the first real run on 2026-09-02: Symon answered
        # "1,2,3,4,5,6,7,8,9,10" and Claude answered "1, 2, 3, 4, 5, 6, 7, 8, 9, 10".
        # Those are the same answer. Reporting a disagreement would have sent the operator
        # to a decision he should never have been asked to make.
        r = agreement([A("symon", "1,2,3,4,5,6,7,8,9,10"),
                       A("claude", "1, 2, 3, 4, 5, 6, 7, 8, 9, 10")])
        self.assertTrue(r["agree"], "separator spacing must not read as disagreement")

    def test_spacing_fix_does_not_hide_a_real_disagreement(self):
        # The normaliser must not become so eager that it merges genuinely different
        # answers -- that would hide exactly what R-184 exists to surface.
        r = agreement([A("symon", "1,2,3"), A("claude", "1,2,4")])
        self.assertFalse(r["agree"])
        self.assertEqual(r["distinct"], 2)

    def test_different_answers_disagree_and_keep_both(self):
        r = agreement([A("symon", "count up"), A("claude", "count down")])
        self.assertFalse(r["agree"])
        self.assertEqual(r["distinct"], 2)
        self.assertEqual(len(r["proposals"]), 2)
        # Every proposal survives. Nothing is merged, nothing is ranked, and no winner is
        # marked -- that decision is the operator's under R-184.
        texts = {p["text"] for p in r["proposals"]}
        self.assertEqual(texts, {"count up", "count down"})
        for p in r["proposals"]:
            self.assertNotIn("winner", p)
            self.assertNotIn("score", p)

    def test_one_answer_is_not_a_consensus(self):
        # `agree` must be None, never True: one opinion is not agreement.
        self.assertIsNone(agreement([A("symon", "1,2,3")])["agree"])

    def test_failed_coder_does_not_count_as_assent(self):
        # A silent coder must not be read as agreeing. Two completed + one failed compares
        # only the two, and the failure never becomes a third vote.
        r = agreement([A("symon", "x"), A("claude", "x"),
                       A("codex", "", state="failed", error="boom")])
        self.assertTrue(r["agree"])
        self.assertEqual(r["distinct"], 1)

    def test_two_failures_leave_nothing_to_compare(self):
        r = agreement([A("symon", "", state="failed"),
                       A("claude", "", state="timed_out")])
        self.assertIsNone(r["agree"])


class PresetTests(unittest.TestCase):
    def test_all_seven_selections_exist(self):
        self.assertEqual(len(PRESETS), 7)
        kinds = [r["kind"] for r in preset_rows()]
        self.assertEqual(kinds.count("single"), 3)
        self.assertEqual(kinds.count("dual"), 3)
        self.assertEqual(kinds.count("tri"), 1)

    def test_every_preset_is_listed_even_when_unavailable(self):
        # Hiding an unavailable combination would lose the owner's requirement. Each row is
        # always present; only `available` changes.
        rows = preset_rows()
        self.assertEqual(len(rows), 7)
        for r in rows:
            self.assertIn("available", r)
            if not r["available"]:
                self.assertTrue(r["detail"], "an unavailable preset must say why")

    def test_owner_named_combinations_are_present(self):
        keys = {r["key"] for r in preset_rows()}
        for k in ("symon", "claude", "codex", "symon+claude", "codex+symon",
                  "codex+claude", "symon+claude+codex"):
            self.assertIn(k, keys)


class ProviderTests(unittest.TestCase):
    def test_three_coders(self):
        self.assertEqual(len(providers()), 3)
        self.assertEqual({p.coder_id for p in providers()}, set(CODER_IDS))

    def test_unavailable_provider_states_a_reason(self):
        for p in providers():
            if not p.available:
                self.assertTrue(p.detail.strip(), f"{p.coder_id} unavailable with no reason")

    def test_codex_is_not_offered_without_a_proven_boundary(self):
        # The incoming plan: an adapter that cannot enforce the answer-only boundary is
        # reported unavailable. This asserts we did not ship it as working because one
        # clean probe came back.
        c = provider_map()["codex"]
        if not c.answer_only_proven:
            self.assertFalse(c.available,
                             "codex offered as available without a proven answer-only boundary")


class UnavailableRowTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_coder_still_gets_a_row(self):
        from . import _ask_one
        pm = provider_map()
        target = next((c for c in CODER_IDS if not pm[c].available), None)
        if target is None:
            self.skipTest("all providers available on this box")
        a = await _ask_one(target, "hi", 5.0, "/tmp")
        self.assertEqual(a.state, "unavailable")
        self.assertTrue(a.error)
        # The row survives so a 3-coder run cannot silently become a 2-coder run.
        self.assertEqual(a.coder_id, target)


if __name__ == "__main__":
    unittest.main()


class DebateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from . import Session, Answer, _remember
        import time
        self.s = Session("debate-fixture", "Choose an implementation", ["symon", "claude"],
                         time.time(), answers=[Answer("symon", "Symon", "completed", "Option A"),
                                               Answer("claude", "Claude", "completed", "Option B")],
                         state="done", fixture=True)
        _remember(self.s)

    async def test_round_preserves_positions_and_requires_a_new_user_decision(self):
        from . import run_debate, record_decision, Answer
        from unittest.mock import patch, AsyncMock
        self.s.decision = "symon"
        calls = []
        async def answer(coder, prompt, deadline, scratch):
            calls.append((coder, prompt))
            return Answer(coder, coder.title(), "completed", "Revised " + coder)
        with patch(f"{__package__}._ask_one", side_effect=answer):
            await run_debate(self.s, "Explain tradeoffs", 0)
        self.assertEqual(calls[0][1], calls[1][1])
        for value in ("Option A", "Option B", "symon", "claude", "Explain tradeoffs"):
            self.assertIn(value, calls[0][1])
        self.assertEqual([a.text for a in self.s.answers], ["Option A", "Option B"])
        self.assertEqual(self.s.rounds[0].prompt, calls[0][1])
        self.assertEqual(self.s.decision, "")
        with self.assertRaises(ValueError):
            record_decision(self.s, "claude", 0)
        record_decision(self.s, "claude", 1)
        self.assertEqual(self.s.decisions[-1]["round_number"], 1)
        self.assertEqual(self.s.decision, "claude")

    async def test_duplicate_round_and_bounded_limit_do_not_dispatch(self):
        from . import run_debate, Answer, MAX_DEBATE_ROUNDS
        from unittest.mock import patch
        async def answer(coder, *args):
            return Answer(coder, coder.title(), "completed", "same")
        with patch(f"{__package__}._ask_one", side_effect=answer) as ask:
            for n in range(MAX_DEBATE_ROUNDS):
                await run_debate(self.s, "Discuss", n)
            count = ask.call_count
            for version in (0, MAX_DEBATE_ROUNDS):
                with self.assertRaises(ValueError):
                    await run_debate(self.s, "Discuss", version)
            self.assertEqual(ask.call_count, count)
            self.assertEqual(self.s.decision, "")

    async def test_inflight_round_refuses_second_round_and_decision(self):
        import asyncio
        from . import run_debate, record_decision, Answer
        from unittest.mock import patch
        entered, release = asyncio.Event(), asyncio.Event()
        async def answer(coder, *args):
            entered.set()
            await release.wait()
            return Answer(coder, coder.title(), "completed", coder)
        with patch(f"{__package__}._ask_one", side_effect=answer):
            task = asyncio.create_task(run_debate(self.s, "Discuss", 0))
            await entered.wait()
            with self.assertRaises(ValueError):
                await run_debate(self.s, "duplicate", 1)
            with self.assertRaises(ValueError):
                record_decision(self.s, "symon", 1)
            release.set()
            await task
        self.assertEqual(len(self.s.rounds), 1)

    async def test_failure_stays_attributed_and_cannot_be_selected(self):
        from . import run_debate, record_decision, Answer
        from unittest.mock import patch
        async def answer(coder, *args):
            if coder == "claude":
                return Answer(coder, "Claude", "timed_out", error="fixture deadline")
            return Answer(coder, "Symon", "completed", "Option A")
        with patch(f"{__package__}._ask_one", side_effect=answer):
            await run_debate(self.s, "Discuss", 0)
        self.assertEqual([a.coder_id for a in self.s.rounds[0].answers], self.s.coder_ids)
        self.assertEqual(self.s.rounds[0].answers[1].state, "timed_out")
        with self.assertRaises(ValueError):
            record_decision(self.s, "claude", 1)
        self.assertIsNone(self.s.to_dict()["rounds"][0]["agree"])

    async def test_cancellation_retains_round_and_every_participant(self):
        import asyncio
        from . import run_debate
        from unittest.mock import patch
        entered = asyncio.Event()
        async def answer(*args):
            entered.set()
            await asyncio.Event().wait()
        with patch(f"{__package__}._ask_one", side_effect=answer):
            task = asyncio.create_task(run_debate(self.s, "Discuss", 0))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(self.s.rounds[0].state, "canceled")
        self.assertEqual(len(self.s.rounds[0].answers), 2)
        self.assertTrue(all(a.state == "canceled" for a in self.s.rounds[0].answers))

    async def test_blank_or_oversized_context_is_rejected_without_dispatch(self):
        from . import run_debate, MAX_DEBATE_CONTEXT_CHARS
        from unittest.mock import patch
        with patch(f"{__package__}._ask_one") as ask:
            with self.assertRaises(ValueError):
                await run_debate(self.s, "  ", 0)
            self.s.answers[0].text = "x" * MAX_DEBATE_CONTEXT_CHARS
            with self.assertRaises(ValueError):
                await run_debate(self.s, "Discuss", 0)
            ask.assert_not_called()
        self.assertEqual(self.s.rounds, [])


class AdapterAndBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_jsonl_contract_uses_completed_item_and_turn(self):
        import json
        from unittest.mock import patch, AsyncMock
        from . import _ask_codex
        output = "\n".join(json.dumps(x) for x in [
            {"type":"item.completed","item":{"type":"agent_message","text":"Answer"}},
            {"type":"turn.completed","usage":{"output_tokens":2}}])
        with patch(f"{__package__}._run", new=AsyncMock(return_value=(0,output,""))) as run:
            answer = await _ask_codex("test", 1, "/tmp")
        self.assertEqual(answer.text, "Answer")
        self.assertEqual(answer.usage["output_tokens"], 2)
        self.assertEqual(run.call_args.args[0][1:4], ["-a", "never", "exec"])
        with patch(f"{__package__}._run", new=AsyncMock(return_value=(0,'{"type":"turn.completed"}',""))):
            answer = await _ask_codex("test", 1, "/tmp")
        self.assertEqual(answer.state, "failed")

    async def test_cancel_reaps_provider_process(self):
        """Tests process REAPING, not authorisation, so it holds a provider grant. Without
        one `_run` refuses before spawning anything and there is no child left to reap --
        the gate working, not a regression in the behaviour this pins."""
        import asyncio, sys, os, tempfile
        from pathlib import Path
        import authority
        from . import _run
        grant = authority.Task(task_id="t-reap", owner="test",
                               mutation_authority=("provider",))
        with authority.acting_as(grant), tempfile.TemporaryDirectory() as d:
            pidfile = Path(d)/"pid"
            script = "import os,time;open('pid','w').write(str(os.getpid()));time.sleep(30)"
            task = asyncio.create_task(_run([sys.executable,"-B","-c",script],"",d,60))
            for _ in range(100):
                if pidfile.exists(): break
                await asyncio.sleep(.01)
            self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            with self.assertRaises(ProcessLookupError): os.kill(pid,0)


class DebateRouteBoundaryTests(unittest.TestCase):
    def test_debate_inherits_local_router_guard(self):
        # Switched ON for the whole test, because the subject here is the LOCALITY gate and
        # the two are independent. With the surface off every line below would read 404 and
        # the test would pass while proving nothing about peers or proxy headers --
        # `SurfaceSwitchTests.test_the_switch_does_not_override_the_locality_gate` is the one
        # that checks they do not collapse into each other.
        self.enterContext(unittest.mock.patch.dict(
            os.environ, {"SYMONEURAL_CODERS_ENABLED": "1"}))
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from server import _require_local
        from .router import router
        app = FastAPI()
        app.include_router(router,prefix="/local/coders",dependencies=[Depends(_require_local)])
        body = {"clarification":"test", "expected_round":0}
        local = TestClient(app, client=("127.0.0.1",1234))
        for header in ("X-Forwarded-For","X-Forwarded-Host","X-Real-IP"):
            response = local.post("/local/coders/session/test/debate",json=body,headers={header:"198.51.100.1"})
            self.assertEqual(response.status_code,404)
        remote = TestClient(app,client=("198.51.100.1",1234))
        self.assertEqual(remote.get("/local/coders/providers").status_code,404)
        self.assertEqual(local.get("/local/coders/providers").status_code,200)


class ChildEnvironmentTests(unittest.TestCase):
    """A provider child is a THIRD-PARTY binary that makes outbound network calls.

    Whatever is in its environment has left this box's control, so the question is not
    "would Claude or Codex misuse a token" but "is this box still the only thing that holds
    it". Until 2026-09-03 the answer was no: `_run` passed `{**os.environ, ...}`, and the
    running API's environment carries the coder, studio and project tokens (still under their pre-rename `SYM_`
    spellings here) plus `SYMONEURAL_SESSION_SECRET`.
    """

    def test_no_project_secret_reaches_a_provider_child(self):
        """The regression guard. Named prefixes rather than named variables on purpose: a
        secret added next month will be `SYM_`-something and nobody will remember to add it
        here, which is the whole reason the filter is an allow-list."""
        from . import child_env
        # BOTH spellings of each token, because the rename in `apps/symoneuralenv.py` is
        # partway through this tree: the running service still carries the pre-rename `SYM_`
        # names while new code writes `SYMONEURAL_`. A filter that caught only one prefix
        # would look correct on whichever half the author happened to test.
        polluted = dict(
            os.environ,
            SYM_CODER_TOKEN="tok-coder", SYMONEURAL_CODER_TOKEN="tok-coder",
            SYM_STUDIO_TOKEN="tok-studio", SYMONEURAL_STUDIO_TOKEN="tok-studio",
            SYM_PROJECT_TOKEN="tok-project", SYMONEURAL_PROJECT_TOKEN="tok-project",
            SYMONEURAL_SESSION_SECRET="s3cr3t",
            SYMONEURAL_A_FUTURE_SECRET="not-yet-invented",
        )
        with unittest.mock.patch.dict(os.environ, polluted, clear=True):
            env = child_env()
        leaked = sorted(k for k in env if k.startswith(("SYM_", "SYMONEURAL_")))
        self.assertEqual(leaked, [], f"project variables reached the child: {leaked}")
        # And the values, in case a name is ever laundered through a different key.
        self.assertNotIn("s3cr3t", set(env.values()))
        self.assertNotIn("tok-studio", set(env.values()))

    def test_the_child_keeps_what_it_needs_to_work(self):
        """The other direction, because a filter that empties the environment would pass the
        test above and break every provider. HOME is the load-bearing one: the operator's
        provider credentials live under it, so an empty HOME means every provider reports
        itself unauthenticated and the surface looks broken rather than secured."""
        from . import child_env
        with unittest.mock.patch.dict(
                os.environ,
                {"HOME": "/home/google", "PATH": "/usr/bin", "LANG": "en_US.UTF-8",
                 "SYM_STUDIO_TOKEN": "tok"}, clear=True):
            env = child_env()
        self.assertEqual(env.get("HOME"), "/home/google")
        self.assertEqual(env.get("PATH"), "/usr/bin")
        self.assertEqual(env.get("LANG"), "en_US.UTF-8")

    def test_an_explicit_addition_still_wins(self):
        """`extra` is applied after the filter deliberately: naming a variable IS classifying
        it, and the allow-list exists to stop unclassified inheritance, not to veto a caller
        that has decided."""
        from . import child_env
        with unittest.mock.patch.dict(os.environ, {"HOME": "/h"}, clear=True):
            env = child_env({"SYMONEURAL_DELIBERATE": "yes"})
        self.assertEqual(env.get("SYMONEURAL_DELIBERATE"), "yes")

    def test_run_uses_the_filter_rather_than_os_environ(self):
        """Structural: the leak was one dict-splat, and the fix is one call. If `_run` ever
        goes back to splatting the process environment this fails, which the value-level
        tests above cannot catch without spawning a real provider."""
        import inspect
        from . import _run
        src = inspect.getsource(_run)
        self.assertIn("env=child_env(env)", src)
        self.assertNotIn("os.environ", src, "_run reads the process environment directly again")


class SurfaceSwitchTests(unittest.TestCase):
    """OFF is the default, and the switch is read per request rather than at import.

    This surface shipped without a switch at all, which left the rack's most effectful
    operator surface as the only one that was live the moment the API imported it -- while
    singular `coder`, which has strictly less authority, demanded both an ENABLED flag and a
    token. The asymmetry was backwards.
    """

    def _client(self, peer=("127.0.0.1", 1234)):
        from fastapi import FastAPI, Depends
        from fastapi.testclient import TestClient
        from server import _require_local
        from .router import router
        app = FastAPI()
        app.include_router(router, prefix="/local/coders",
                           dependencies=[Depends(_require_local)])
        return TestClient(app, client=peer)

    def test_absent_switch_means_off(self):
        """Absent, not merely non-'1'. The default has to be off for a variable nobody set."""
        env = {k: v for k, v in os.environ.items() if k != "SYMONEURAL_CODERS_ENABLED"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self._client().get("/local/coders/providers").status_code, 404)

    def test_switched_off_is_indistinguishable_from_never_built(self):
        """404 and not 403. A switched-off surface that announced itself would let a local
        process map what this box could do if it were turned on."""
        with unittest.mock.patch.dict(os.environ, {"SYMONEURAL_CODERS_ENABLED": "0"}):
            r = self._client().get("/local/coders/providers")
        self.assertEqual(r.status_code, 404)

    def test_switched_on_serves_a_loopback_caller(self):
        """The other direction, or the gate above would pass by breaking the surface."""
        with unittest.mock.patch.dict(os.environ, {"SYMONEURAL_CODERS_ENABLED": "1"}):
            r = self._client().get("/local/coders/providers")
        self.assertEqual(r.status_code, 200)
        self.assertIn("providers", r.json())

    def test_the_switch_does_not_override_the_locality_gate(self):
        """Two independent gates. Switching the surface ON must not make it reachable from
        off-box, and must not make an x-forwarded-* header acceptable."""
        with unittest.mock.patch.dict(os.environ, {"SYMONEURAL_CODERS_ENABLED": "1"}):
            remote = self._client(peer=("198.51.100.1", 1234))
            self.assertEqual(remote.get("/local/coders/providers").status_code, 404)
            local = self._client()
            for header in ("X-Forwarded-For", "X-Forwarded-Host", "X-Real-IP"):
                self.assertEqual(
                    local.get("/local/coders/providers",
                              headers={header: "198.51.100.1"}).status_code, 404)


class JournalTests(unittest.TestCase):
    """`_SESSIONS` is a dict owned by one worker, capped and gone on restart. That answers
    "what is on the page"; it cannot answer "what did this box ask a third-party provider,
    and what did the operator choose" a week later -- which a surface spawning provider CLIs
    under the operator's own accounts has to be able to answer."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.enterContext(unittest.mock.patch.dict(
            os.environ, {"SYMONEURAL_CODERS_STATE_DIR": self._tmp.name}))
        self.addCleanup(self._tmp.cleanup)

    def _lines(self):
        from . import journal_path
        p = journal_path()
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

    def test_a_record_is_appended_and_fsynced_with_owner_only_permissions(self):
        from . import journal, journal_path
        journal("session", "abc123", asked=["symon"])
        self.assertEqual(oct(journal_path().stat().st_mode)[-3:], "600",
                         "operator evidence must not be world-readable")
        rows = self._lines()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event"], "session")
        self.assertEqual(rows[0]["session_id"], "abc123")
        self.assertEqual(rows[0]["asked"], ["symon"])
        self.assertIn("ts", rows[0])

    def test_records_append_rather_than_replace(self):
        """The failure that makes a journal worthless is silently keeping only the last row."""
        from . import journal
        for i in range(3):
            journal("session", f"s{i}")
        self.assertEqual([r["session_id"] for r in self._lines()], ["s0", "s1", "s2"])

    def test_neither_prompt_nor_answer_text_is_written(self):
        """A control-plane record, not a second copy of model output. `prompt_sha256` still
        pins WHICH prompt a row refers to without storing it twice."""
        from . import journal
        secret = "a prompt that must not land on disk twice"
        journal("session", "s1",
                prompt_sha256=hashlib.sha256(secret.encode()).hexdigest(),
                prompt_chars=len(secret))
        blob = json.dumps(self._lines())
        self.assertNotIn(secret, blob)
        self.assertIn(hashlib.sha256(secret.encode()).hexdigest(), blob)

    def test_a_failed_write_cannot_lose_a_completed_answer(self):
        """Deliberately the opposite of `apps/coder._journal`, which raises so an untraced
        mutation is refused. Here the provider work is already done and paid for by the time
        there is anything to record, so a full disk must not turn into a lost answer."""
        from . import journal
        with unittest.mock.patch("os.open", side_effect=OSError("ENOSPC")):
            journal("session", "s1")          # must not raise
        self.assertEqual(self._lines(), [])

    def test_nothing_is_created_merely_by_importing(self):
        """Lazy, like apps/coder. Importing the module on a box where the surface is switched
        off must not create runtime state."""
        from . import journal_path
        self.assertFalse(journal_path().exists())


class ProviderSpawnRequiresAuthority(unittest.TestCase):
    """Spawning `claude` or `codex` runs a third-party CLI under the operator's own logged-in
    session. This module's docstring names that plainly: "whoever can reach this surface can
    spend his account". Reaching the surface is admission; spending the account is authority.
    """

    def setUp(self):
        import tempfile
        self.enterContext(unittest.mock.patch.dict(
            os.environ, {"SYMONEURAL_AUTHORITY_DIR": tempfile.mkdtemp(),
                         "SYMONEURAL_CODERS_STATE_DIR": tempfile.mkdtemp()}))

    def test_a_spawn_with_no_task_is_refused_before_the_process_starts(self):
        import asyncio
        import authority
        from . import _run
        with self.assertRaises(authority.NoTask):
            asyncio.run(_run(["/bin/echo", "hi"], "p", "/tmp", 5.0))

    def test_a_grant_for_another_scope_does_not_buy_provider_spend(self):
        """`provider` is deliberately not `service`. A task granted a shell must not silently
        also get the right to spend the operator's third-party quota."""
        import asyncio
        import authority
        from . import _run
        for scope in ("workspace", "service", "environment"):
            with self.subTest(scope=scope):
                t = authority.Task(task_id=f"t-{scope}", owner="test",
                                   mutation_authority=(scope,))
                with authority.acting_as(t):
                    with self.assertRaises(authority.NotAuthorised):
                        asyncio.run(_run(["/bin/echo", "hi"], "p", "/tmp", 5.0))

    def test_the_provider_grant_permits_the_spawn(self):
        """The other direction, or the gate could pass every test above by refusing always."""
        import asyncio
        import authority
        from . import _run
        t = authority.Task(task_id="t-ok", owner="test", provider="claude",
                           mutation_authority=("provider",))
        with authority.acting_as(t):
            code, out, _ = asyncio.run(_run(["/bin/echo", "hi"], "p", "/tmp", 10.0))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "hi")

    def test_the_gate_authorises_without_taking_an_exclusive_lease(self):
        """Providers are deliberately concurrent -- run_session fans out with asyncio.gather
        and _LOCKS serialises each provider against itself. A scope-wide lease would serialise
        Claude against Codex and destroy that. So the spawn uses enforce(), not guard(), and
        no lease may be held afterwards."""
        import asyncio
        import authority
        from . import _run
        t = authority.Task(task_id="t-nolease", owner="test",
                           mutation_authority=("provider",))
        with authority.acting_as(t):
            asyncio.run(_run(["/bin/echo", "hi"], "p", "/tmp", 10.0))
        self.assertIsNone(authority.current_holder("provider"),
                          "the spawn took an exclusive lease and would serialise providers")
