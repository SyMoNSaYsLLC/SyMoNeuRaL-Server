"""`bin/symoneural-cli upgrade` -- the no-apt path to a deploy.

The 981-line CLI had no test of any kind when this file was written; this covers the
subcommand the packaged postinst advertises (`scripts/build-deb.sh:162`), because a `.deb`
that tells an operator to run a command which does not exist is the failure this repo keeps
finding in its own prose.

Two kinds of test here, deliberately:

  * two subprocess runs of the real script, which is the only thing that proves the
    subcommand is *registered* -- argparse rejects an unknown choice before any code runs
  * the root path exercised in-process with `geteuid`, `subprocess.run` and `STATE`
    redirected, because the real path publishes a webroot and restarts a service, and a test
    that needed root would simply never run

Nothing here needs the GPU, the API, or root.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "symoneural-code" / "bin" / "symoneural-cli"   # the real file; bin/ holds a symlink
#: `sudo_argv` builds its re-exec line from the CLI's own `__file__`, which resolves
#: through the bin/ symlink to the real path under symoneural-code/. Asserting the
#: symlink path here would test the shim rather than the command that actually runs.


def load_cli() -> types.ModuleType:
    """Import the CLI as a module, compiling the source on every call.

    It has no `.py` suffix, so the loader has to be explicit -- but a `SourceFileLoader`
    also *caches*, and that cache is the reason this reads and compiles the text instead.
    Importing an extensionless script writes `bin/__pycache__/symoneural-clicpython-313.pyc`
    beside the shipped file, and CPython validates that cache against the source mtime
    **truncated to whole seconds**. Edit the CLI and re-run inside the same second -- which a
    scripted mutate-run-restore loop does trivially -- and the loader hands back the previous
    bytecode with no error and no warning. That happened here: a deliberate mutation was
    reverted, the suite went red anyway, and the code under test was not the code on disk.
    A test suite whose whole job is to assert what the file says cannot be reading a copy of
    what it said a moment ago, so this path has no cache to be stale.
    """
    module = types.ModuleType("symoneural_cli")
    module.__file__ = str(CLI)
    exec(compile(CLI.read_text(), str(CLI), "exec"), module.__dict__)  # noqa: S102
    return module


class UpgradeSubcommandTests(unittest.TestCase):
    def test_upgrade_check_runs_and_names_the_script_it_calls(self):
        """`--check` is the whole reason this can be tested: it needs no root and publishes
        nothing, so this asserts the subcommand exists and that it delegates rather than
        reimplementing. If the parser entry is deleted, argparse exits 2 here."""
        with tempfile.TemporaryDirectory(dir=ROOT / "run") as tmp:
            env = {**os.environ, "SYMONEURAL_STATE_DIR": tmp}
            out = subprocess.run([sys.executable, str(CLI), "upgrade", "--check"],
                                 capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("scripts/deploy.sh --prune", out.stdout)
            self.assertIn("nothing was run", out.stdout)
            self.assertFalse(Path(tmp, "last-deploy").exists(),
                             "--check wrote a deploy verdict, so it did more than check")

    def test_status_prints_the_recorded_verdict_and_invents_none(self):
        """`scripts/build-deb.sh:146` claims `symoneural-cli status` reads
        /var/lib/symoneural/last-deploy back. Both halves are asserted: the line appears when
        the postinst has written a verdict, and no line appears when it has not."""
        with tempfile.TemporaryDirectory(dir=ROOT / "run") as tmp:
            env = {**os.environ, "SYMONEURAL_STATE_DIR": tmp}
            bare = subprocess.run([sys.executable, str(CLI), "status"],
                                  capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(bare.returncode, 0, bare.stderr)
            self.assertNotIn("last deploy", bare.stdout,
                             "a 'last deploy' row appeared with no file to read it from")

            Path(tmp, "last-deploy").write_text("ok: 2026-08-19T16:22:04-0400\n")
            after = subprocess.run([sys.executable, str(CLI), "status"],
                                   capture_output=True, text=True, timeout=60, env=env)
            self.assertIn("ok: 2026-08-19T16:22:04-0400", after.stdout)


class UpgradeRootPathTests(unittest.TestCase):
    """The path that only ever runs as root, run without it."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / "run")
        self.addCleanup(self.tmp.cleanup)
        self.cli.STATE = Path(self.tmp.name)
        self.calls: list[list[str]] = []

        def fake_run(argv, *_a, **_kw):
            self.calls.append([str(x) for x in argv])
            return subprocess.CompletedProcess(argv, 0)

        # Rebind the module's *names*, never the modules behind them. The first version of
        # this file did `self.cli.subprocess.run = fake_run`, which reaches through to the one
        # `subprocess` module every test in the process shares: 27 tests in apps/voice and
        # apps/streamer then failed, because they shell out to ffmpeg and were handed this stub.
        # A shim object bound to `symoneural_cli.subprocess` is visible to the code under
        # test and to nothing else.
        self.shim_subprocess(fake_run)
        self.cli.os = types.SimpleNamespace(geteuid=lambda: 0, execvp=self.cli.os.execvp)

    def shim_subprocess(self, run):
        self.cli.subprocess = types.SimpleNamespace(
            run=run, CompletedProcess=subprocess.CompletedProcess,
            SubprocessError=subprocess.SubprocessError)

    def args(self, **kw):
        return types.SimpleNamespace(**{"check": False, "no_restart": False, **kw})

    def test_the_deploy_is_called_through_and_the_verdict_is_recorded(self):
        rc = self.cli.cmd_upgrade(self.args())
        self.assertEqual(rc, 0)
        deploys = [a for a in self.calls if a[0].endswith("scripts/deploy.sh")]
        self.assertEqual(deploys, [[str(self.cli.DEPLOY), "--prune"]],
                         "deploy.sh must be called exactly once, with --prune, and its "
                         "orphan scan and reference check must not be reimplemented here")
        self.assertTrue(Path(self.tmp.name, "last-deploy").read_text().startswith("ok: "))
        self.assertIn(["systemctl", "restart", "symoneural-api"], self.calls)

    def test_a_failed_deploy_is_recorded_as_failed_and_leaves_the_service_alone(self):
        """dpkg's rule inverted: the postinst must not fail the package, but this command has
        no such constraint and returns the failure. What both share is that a service running
        the old code is better than one restarted against a half-published webroot."""
        def failing(argv, *_a, **_kw):
            self.calls.append([str(x) for x in argv])
            rc = 1 if str(argv[0]).endswith("deploy.sh") else 0
            return subprocess.CompletedProcess(argv, rc)

        self.shim_subprocess(failing)
        rc = self.cli.cmd_upgrade(self.args())
        self.assertEqual(rc, 1)
        self.assertTrue(Path(self.tmp.name, "last-deploy").read_text().startswith("FAILED: "))
        self.assertNotIn(["systemctl", "restart", "symoneural-api"], self.calls,
                         "the service was restarted after the publish failed")

    def test_no_restart_publishes_and_does_not_restart(self):
        rc = self.cli.cmd_upgrade(self.args(no_restart=True))
        self.assertEqual(rc, 0)
        self.assertNotIn(["systemctl", "restart", "symoneural-api"], self.calls)

    def test_the_service_check_asks_is_active_not_is_enabled(self):
        """A unit that is enabled but deliberately stopped must stay stopped; `is-enabled`
        would report it as wanted and `restart` would start it. This asserts the live call,
        not the comment above it."""
        self.cli.unit_is_active()
        systemctl = [a for a in self.calls if a[:1] == ["systemctl"]]
        self.assertTrue(systemctl, "no systemctl call was made")
        self.assertIn("is-active", systemctl[0])
        self.assertNotIn("is-enabled", systemctl[0])


class SudoReexecTests(unittest.TestCase):
    """`sudo_argv` exists as a function so this can be read without running it. There is no
    dry-run mode for sudo, and a test that actually re-exec'd would prompt for a password."""

    def setUp(self):
        self.cli = load_cli()

    def test_the_reexec_line_is_this_script_and_this_interpreter(self):
        argv = self.cli.sudo_argv(types.SimpleNamespace(check=False, no_restart=False))
        self.assertEqual(argv, ["sudo", sys.executable, str(CLI), "upgrade"])

    def test_no_restart_survives_the_reexec(self):
        """The flag is the operator saying "do not touch the running service". Losing it
        across the sudo boundary would restart it anyway, which is the opposite."""
        argv = self.cli.sudo_argv(types.SimpleNamespace(check=False, no_restart=True))
        self.assertEqual(argv[-1], "--no-restart")


if __name__ == "__main__":
    unittest.main()
