"""`symoneural.sh off` is documented as the kill switch, so it has to actually kill.

CLAUDE.md: *"`./scripts/symoneural.sh on|off|status`   # the live API (off is the kill
switch)"*. It was not one. Every function in the script keyed off `run/api.pid`, and
`symoneural-api.service` is `Type=exec` with no `PIDFile=`, so a systemd-managed API writes
none. Two consequences, both worse than they look:

* `status` printed `api        down` and then printed a correct `/api/status` JSON body
  underneath it -- a readout contradicting itself, measured here while the API had been up
  for 2h38m.
* `off` found no pidfile, killed nothing, and printed *"surfaces off. static pages
  unaffected; the card is free."* unconditionally. And had it found a pid, the unit is
  `Restart=always` / `RestartSec=3`.

The tests below run the real script inside a **fake repo root** -- its own `backend/server.py`
marker and a stub `scripts/gpu-governor.sh` -- with stub `systemctl`, `curl` and `pkill` on
PATH. That is deliberate: an earlier draft ran the script in place, which would have called
the real governor's `release chat` on this machine. A test for a kill switch must not be able
to touch the thing it is testing.

The stubs are the whole point of the fixture, so what each one asserts is worth stating:
`curl` exiting 0 IS "something is answering on the port", which is the state in which
announcing success is the bug.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REAL = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "symoneural.sh"


class FakeRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="symon-svc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "backend").mkdir()
        (self.tmp / "backend" / "server.py").write_text("# marker the script's root guard reads\n")
        (self.tmp / "scripts").mkdir()
        shutil.copy2(REAL, self.tmp / "scripts" / "symoneural.sh")
        gov = self.tmp / "scripts" / "gpu-governor.sh"
        gov.write_text("#!/usr/bin/env bash\nexit 0\n")
        gov.chmod(0o755)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def _stub(self, name, body):
        p = self.bin / name
        p.write_text(f"#!/usr/bin/env bash\n{body}\n")
        p.chmod(0o755)

    def _run(self, *argv, port_answers, unit_active):
        # `curl` exiting 0 is the script's only test for "is anything actually serving".
        self._stub("curl", "exit 0" if port_answers else "exit 7")
        self._stub("systemctl", "exit 0" if unit_active else "exit 3")
        self._stub("pkill", "exit 0")
        self._stub("sudo", "exit 1")   # non-interactive escalation unavailable
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        return subprocess.run([str(self.tmp / "scripts" / "symoneural.sh"), *argv],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_off_refuses_to_claim_success_while_the_port_still_answers(self):
        """The exact bug: this printed the success line and exited 0.

        Unit inactive so no escalation is needed -- the script gets all the way through its
        own kill path and *then* finds something still serving, which is the case where the
        old unconditional success line was a flat lie. (Whatever is answering is a hand-
        started copy, which is exactly the situation `status` now reports as owner UNKNOWN.)
        """
        r = self._run("off", port_answers=True, unit_active=False)
        self.assertNotIn("surfaces off", r.stdout,
                         "off announced success while something was still serving the port")
        self.assertIn("STILL UP", r.stderr)
        self.assertNotEqual(0, r.returncode, "a kill switch that failed must not exit 0")

    def test_off_refuses_rather_than_lying_when_it_cannot_stop_the_unit(self):
        """No root and the unit is active: it must say the command, not claim success.

        This is the branch the first draft of the test above actually hit, and the behaviour
        is right: `sudo -n` fails, so the script exits before its own kill path. Recording it
        as its own case because "refused loudly" and "verified nothing is left" are two
        different guarantees and a kill switch owes both.
        """
        r = self._run("off", port_answers=True, unit_active=True)
        self.assertNotIn("surfaces off", r.stdout)
        self.assertIn("sudo systemctl stop", r.stderr)
        self.assertNotEqual(0, r.returncode)

    def test_off_says_success_only_once_nothing_answers(self):
        r = self._run("off", port_answers=False, unit_active=False)
        self.assertIn("surfaces off", r.stdout, r.stderr)
        self.assertEqual(0, r.returncode, r.stderr)

    def test_status_reports_up_when_the_unit_owns_it_and_there_is_no_pidfile(self):
        r = self._run("status", port_answers=True, unit_active=True)
        self.assertIn("up", r.stdout.splitlines()[0])
        self.assertNotIn("down", r.stdout.splitlines()[0],
                         "status said down about a systemd-managed API that was up")

    def test_status_reports_an_unowned_listener_rather_than_down(self):
        """Nothing in the pidfile, unit inactive, port answering -- the honest answer is
        `up, owner UNKNOWN`, because `down` is false and silently pretending it is a normal
        managed start would hide a second copy fighting for the port."""
        r = self._run("status", port_answers=True, unit_active=False)
        first = r.stdout.splitlines()[0]
        self.assertIn("UNKNOWN", first, first)

    def test_status_says_down_when_nothing_is_there(self):
        r = self._run("status", port_answers=False, unit_active=False)
        self.assertIn("down", r.stdout.splitlines()[0])

    def test_on_prefers_the_unit_over_spawning_a_second_copy(self):
        """Two API processes would race for the port; the one systemd restarts always wins."""
        r = self._run("on", port_answers=True, unit_active=True)
        self.assertIn("already up", r.stdout, r.stderr)


class SourceContractTests(unittest.TestCase):
    """Two invariants the fixture above cannot reach, asserted on the text instead."""

    def test_off_stops_the_unit_rather_than_killing_the_process(self):
        src = REAL.read_text()
        self.assertIn("stop \"$UNIT\"", src,
                      "off does not stop the unit; Restart=always makes a kill a 3s pause")

    def test_escalation_is_non_interactive(self):
        """A kill switch that blocks on a password prompt is a kill switch that hangs."""
        self.assertIn("sudo -n systemctl", REAL.read_text())


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    unittest.main()
