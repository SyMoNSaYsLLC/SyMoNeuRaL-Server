"""The mutation-authority plane, tested by attacking it.

Almost every test here is a REFUSAL. That is the shape the thing has to have: a permission
system is only worth its code if the interesting cases are the ones it says no to, and a
suite full of happy paths would prove nothing about whether Studio can still delete a file
without a task.

Nothing here touches real state -- `SYMONEURAL_AUTHORITY_DIR` is redirected to a temp
directory for every test, so a run never competes with the live plane for a real lease.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from . import (AuthorityError, LeaseConflict, NoTask, NotAuthorised, SCOPES, Task,
               acquire, current_holder, guard, journal_path, release, require, tasks_path,
               record_task, state_dir)


def a_task(**kw) -> Task:
    base = dict(task_id="t-1", owner="release-owner", operator="garrett",
                provider="claude", role="production", mutation_authority=("workspace",),
                resource_scope="workspace", stop_condition="one operation")
    base.update(kw)
    return Task(**base)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.enterContext(unittest.mock.patch.dict(
            os.environ, {"SYMONEURAL_AUTHORITY_DIR": self._tmp.name}))
        self.addCleanup(self._tmp.cleanup)

    def events(self, kind=None):
        p = journal_path()
        if not p.exists():
            return []
        rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
        return [r for r in rows if kind is None or r["event"] == kind]


class NoTaskNoMutation(Base):
    def test_require_refuses_when_there_is_no_task_at_all(self):
        with self.assertRaises(NoTask):
            require(None, "workspace", "delete")

    def test_the_refusal_is_journalled(self):
        """A refusal nobody can see is indistinguishable from a call that never happened,
        and the pattern worth detecting is repeated refusals."""
        with self.assertRaises(NoTask):
            require(None, "workspace", "delete")
        self.assertEqual(len(self.events("effect.refused")), 1)

    def test_an_empty_task_id_is_not_a_task(self):
        with self.assertRaises(NoTask):
            acquire(a_task(task_id=""), "workspace")


class AuthorityIsNotProviderIdentity(Base):
    """The module's central claim. Provider is who is speaking; authority is what the task
    was granted. One is never derived from the other."""

    def test_provider_identity_does_not_grant_authority(self):
        for provider in ("claude", "codex", "symon", "browser", "root", ""):
            with self.subTest(provider=provider):
                t = a_task(task_id=f"t-{provider}", provider=provider,
                           mutation_authority=())          # granted nothing
                with self.assertRaises(NotAuthorised):
                    acquire(t, "workspace")

    def test_a_studio_token_holder_still_needs_a_grant(self):
        """Admission is not authority. Passing Studio's gate makes you a caller, not an
        owner -- the 28 tools behind that gate include a shell and an env mutator."""
        t = a_task(task_id="t-studio", provider="browser", role="studio-session",
                   mutation_authority=())
        with self.assertRaises(NotAuthorised):
            require(t, "environment", "env_set")

    def test_authority_is_checked_before_the_lock_is_consulted(self):
        """Otherwise the answer to 'may I?' would depend on who else happens to be busy."""
        holder = a_task(task_id="t-holder")
        lease = acquire(holder, "workspace")
        self.addCleanup(release, lease)
        ungranted = a_task(task_id="t-nope", mutation_authority=())
        with self.assertRaises(NotAuthorised):      # NOT LeaseConflict
            acquire(ungranted, "workspace")

    def test_a_grant_for_one_scope_is_not_a_grant_for_another(self):
        t = a_task(mutation_authority=("workspace",))
        with self.assertRaises(NotAuthorised):
            acquire(t, "repository")
        with self.assertRaises(NotAuthorised):
            acquire(t, "service")


class ConflictIsRefusedNeverStolen(Base):
    def test_a_second_owner_is_refused(self):
        first = acquire(a_task(task_id="t-a", owner="alice"), "workspace")
        self.addCleanup(release, first)
        with self.assertRaises(LeaseConflict):
            acquire(a_task(task_id="t-b", owner="bob"), "workspace")

    def test_the_holder_is_unchanged_after_a_refused_attempt(self):
        """A refusal that damaged the lock would be worse than no lock."""
        first = acquire(a_task(task_id="t-a", owner="alice"), "workspace")
        self.addCleanup(release, first)
        with self.assertRaises(LeaseConflict):
            acquire(a_task(task_id="t-b", owner="bob"), "workspace")
        self.assertEqual(current_holder("workspace")["lease_id"], first.lease_id)

    def test_the_same_task_and_owner_may_re_enter(self):
        """Nested controlled operations under one authority are legitimate; refusing them
        would push callers toward taking the lease once and holding it far too long."""
        t = a_task(task_id="t-same", owner="alice")
        outer = acquire(t, "workspace")
        inner = acquire(t, "workspace")
        self.assertEqual(inner.lease_id, outer.lease_id)
        release(outer)

    def test_a_different_owner_with_the_same_task_id_is_still_a_conflict(self):
        first = acquire(a_task(task_id="t-x", owner="alice"), "workspace")
        self.addCleanup(release, first)
        with self.assertRaises(LeaseConflict):
            acquire(a_task(task_id="t-x", owner="mallory"), "workspace")

    def test_a_foreign_lease_cannot_release_a_scope(self):
        """Releasing by scope alone would be lease stealing with extra steps."""
        held = acquire(a_task(task_id="t-a", owner="alice"), "workspace")
        self.addCleanup(release, held)
        forged = type(held)(**{**held.__dict__, "lease_id": "l-forged"})
        with self.assertRaises(LeaseConflict):
            release(forged)
        self.assertEqual(current_holder("workspace")["lease_id"], held.lease_id)


class StaleOwnersAreReconciledExplicitly(Base):
    def test_a_lease_held_by_a_dead_pid_is_broken_and_logged(self):
        """The governor's rule. A holder that died without releasing must not wedge the
        resource forever -- but the break is announced, because an inherited lock that looks
        like a fresh one is how a second writer gets in."""
        lease = acquire(a_task(task_id="t-dead"), "workspace")
        # Rewrite the holder with a pid that cannot exist.
        hf = state_dir() / "leases" / "workspace.lease.d" / "holder"
        rec = json.loads(hf.read_text()); rec["pid"] = 2 ** 22
        hf.write_text(json.dumps(rec))
        self.assertIsNone(current_holder("workspace"), "a dead holder still held the scope")
        self.assertEqual(len(self.events("lease.stale-reconciled")), 1)
        del lease

    def test_after_reconciliation_another_owner_may_acquire(self):
        acquire(a_task(task_id="t-dead", owner="alice"), "workspace")
        hf = state_dir() / "leases" / "workspace.lease.d" / "holder"
        rec = json.loads(hf.read_text()); rec["pid"] = 2 ** 22
        hf.write_text(json.dumps(rec))
        got = acquire(a_task(task_id="t-new", owner="bob"), "workspace")
        self.assertEqual(got.owner, "bob")

    def test_a_live_holder_is_never_treated_as_stale(self):
        """os.getpid() is alive by definition; if this ever passes as stale the staleness
        rule has inverted and every lock on the box is breakable."""
        lease = acquire(a_task(task_id="t-live"), "workspace")
        self.addCleanup(release, lease)
        self.assertIsNotNone(current_holder("workspace"))
        self.assertEqual(self.events("lease.stale-reconciled"), [])


class JournalIsWrittenBeforeTheEffect(Base):
    def test_intent_is_recorded_before_the_body_runs(self):
        seen = {}
        t = a_task()
        with guard(t, "workspace", "delete", path="/tmp/x"):
            seen["intent_at_body_time"] = len(self.events("effect.intent"))
        self.assertEqual(seen["intent_at_body_time"], 1,
                         "the intent record was not durable before the mutation ran")

    def test_a_failed_effect_still_leaves_its_intent_and_a_failure_record(self):
        """The case an after-the-fact log cannot serve: recovery needs to know what was
        ATTEMPTED, not only what succeeded."""
        with self.assertRaises(RuntimeError):
            with guard(a_task(), "workspace", "delete", path="/tmp/x"):
                raise RuntimeError("boom")
        self.assertEqual(len(self.events("effect.intent")), 1)
        self.assertEqual(len(self.events("effect.failed")), 1)
        self.assertIn("boom", self.events("effect.failed")[0]["error"])

    def test_the_lease_is_released_even_when_the_effect_raises(self):
        with self.assertRaises(RuntimeError):
            with guard(a_task(), "workspace", "delete"):
                raise RuntimeError("boom")
        self.assertIsNone(current_holder("workspace"), "a failed effect leaked its lease")

    def test_start_state_identity_is_carried_into_the_record(self):
        """Rollback needs to know what the state WAS. Recording it after the mutation would
        record the wrong thing."""
        with guard(a_task(), "workspace", "write", start_state_identity="sha256:abc"):
            pass
        self.assertEqual(self.events("effect.intent")[0]["start_state_identity"], "sha256:abc")

    def test_the_journal_is_owner_only(self):
        journal_ok = a_task()
        with guard(journal_ok, "workspace", "noop"):
            pass
        self.assertEqual(oct(journal_path().stat().st_mode)[-3:], "600")

    def test_provider_and_owner_both_reach_the_record(self):
        """Provider does not grant authority, but it must be attributable afterwards --
        'which provider asked for this' is the first question of any incident."""
        with guard(a_task(provider="codex", owner="release-owner"), "workspace", "noop"):
            pass
        rec = self.events("effect.intent")[0]
        self.assertEqual(rec["provider"], "codex")
        self.assertEqual(rec["owner"], "release-owner")


class ScopesAndTasks(Base):
    def test_an_unknown_scope_is_refused(self):
        with self.assertRaises(NotAuthorised):
            acquire(a_task(mutation_authority=("not-a-scope",)), "not-a-scope")

    def test_the_declared_scopes_are_the_ones_the_surfaces_need(self):
        for needed in ("workspace", "repository", "service", "environment", "deployment"):
            self.assertIn(needed, SCOPES)

    def test_a_task_record_is_durable(self):
        t = a_task(task_id="t-durable")
        record_task(t)
        rows = [json.loads(l) for l in tasks_path().read_text().splitlines() if l.strip()]
        self.assertEqual(rows[0]["task_id"], "t-durable")
        self.assertEqual(oct(tasks_path().stat().st_mode)[-3:], "600")

    def test_every_refusal_is_an_AuthorityError(self):
        """A caller must be able to catch one class and know no mutation happened."""
        for exc in (NoTask, NotAuthorised, LeaseConflict):
            self.assertTrue(issubclass(exc, AuthorityError))


class LeaseSurvivesAcrossProcesses(Base):
    """The reason this is a mkdir lock and not flock: the API acquires in one request handler
    and releases in another, and `flock` on a file descriptor dies with the process."""

    def test_a_lease_taken_in_another_process_is_visible_here(self):
        code = (
            "import os,sys;sys.path.insert(0,%r);"
            "from apps.authority import Task, acquire;"
            "t=Task(task_id='t-child',owner='alice',mutation_authority=('workspace',));"
            "l=acquire(t,'workspace');print(l.lease_id)" % str(Path(__file__).resolve().parents[2])
        )
        env = dict(os.environ, SYMONEURAL_AUTHORITY_DIR=self._tmp.name,
                   PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           timeout=60, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        child_lease = r.stdout.strip()
        held = current_holder("workspace")
        # The child exited, so its pid is gone and the lease is correctly reconciled as
        # stale -- which is itself the behaviour worth pinning. What must NOT happen is the
        # lock vanishing with the process before anyone noticed it existed.
        self.assertTrue(child_lease.startswith("l-"))
        self.assertIsNone(held)
        self.assertEqual(len(self.events("lease.stale-reconciled")), 1)


class StudioCannotBypassTheAuthorityPlane(Base):
    """Studio's four `dangerous=True` tools, attacked the way a confused agent would.

    Studio admits a caller once, at the surface, with `enabled() + token_ok()`. Behind that
    gate sit 28 tools including a shell and an environment mutator. These tests assert the
    thing that gate does NOT give you: the right to change the host.
    """

    TOOLS = (("run_command", "service"), ("env_set", "environment"),
             ("write_file", "workspace"), ("delete_path", "workspace"))

    # The tools import `from apps import authority`. This test must catch the exceptions
    # from THAT module object, not from a second copy imported under a different name --
    # `assertRaises` compares identity, and a duplicate import makes every refusal look
    # like an escape. Caught on first run, when a genuine refusal read as a failure.
    @staticmethod
    def _authority():
        from apps import authority as a
        return a

    def _tool(self, name):
        from apps.studio.tools_impl import fs, host
        return getattr(host, name, None) or getattr(fs, name)

    def _call(self, name):
        import tempfile as tf
        probe = Path(tf.gettempdir()) / "symoneural-authz-probe.txt"
        return {"run_command": lambda: self._tool(name)("echo hi"),
                "env_set":     lambda: self._tool(name)("SYMONEURAL_AUTHZ_PROBE", "1"),
                "write_file":  lambda: self._tool(name)(str(probe), "x"),
                "delete_path": lambda: self._tool(name)(str(probe))}[name]

    def test_every_dangerous_tool_refuses_with_no_task(self):
        """The production default. Nothing establishes a task yet, so every one of these is
        disabled by construction rather than by somebody remembering to disable it."""
        for name, _ in self.TOOLS:
            with self.subTest(tool=name):
                with self.assertRaises(self._authority().NoTask):
                    self._call(name)()

    def test_the_refused_effect_did_not_happen(self):
        """A refusal that raised AFTER the mutation would pass the test above and still have
        changed the host. The gate is placed before the effect and this is what proves it."""
        import tempfile as tf
        probe = Path(tf.gettempdir()) / "symoneural-authz-probe.txt"
        if probe.exists():
            probe.unlink()
        with self.assertRaises(self._authority().NoTask):
            self._call("write_file")()
        self.assertFalse(probe.exists(), "the file was written despite the refusal")
        with self.assertRaises(self._authority().NoTask):
            self._call("env_set")()
        self.assertNotIn("SYMONEURAL_AUTHZ_PROBE", os.environ,
                         "the environment was mutated despite the refusal")

    def test_a_task_granted_one_scope_cannot_use_another(self):
        """The lateral move: hold a legitimate workspace task, reach for a shell."""
        A = self._authority()
        t = A.Task(task_id="t-lateral", owner="release-owner", provider="browser",
                   mutation_authority=("workspace",))
        with A.acting_as(t):
            with self.assertRaises(A.NotAuthorised):
                self._call("run_command")()
            with self.assertRaises(A.NotAuthorised):
                self._call("env_set")()

    def test_binding_does_not_leak_out_of_its_context(self):
        """A nested authorised call must not leave the caller holding authority it was never
        granted -- that would turn one authorised operation into a standing permission."""
        A = self._authority()
        t = A.Task(task_id="t-inner", owner="release-owner", mutation_authority=("workspace",))
        self.assertIsNone(A.current_task())
        with A.acting_as(t):
            self.assertIsNotNone(A.current_task())
        self.assertIsNone(A.current_task(), "authority leaked past its context")
        with self.assertRaises(A.NoTask):
            self._call("write_file")()

    def test_the_gate_is_present_in_the_source_of_every_dangerous_tool(self):
        """Structural backstop. A future tool marked dangerous=True with no gate would pass
        every behavioural test above simply by not being called by them."""
        import re as _re
        for mod in ("host", "fs"):
            src = (Path(__file__).resolve().parents[1] / "studio" / "tools_impl"
                   / f"{mod}.py").read_text()
            for m in _re.finditer(r"@tool\([^)]*dangerous=True[^)]*\)\s*\ndef (\w+)", src):
                fn = m.group(1)
                body = src[m.end():]
                nxt = body.find("\n@tool")
                body = body[:nxt if nxt != -1 else len(body)]
                with self.subTest(tool=fn):
                    self.assertIn("authority.enforce(", body,
                                  f"{mod}.{fn} is dangerous=True but has no authority gate")
