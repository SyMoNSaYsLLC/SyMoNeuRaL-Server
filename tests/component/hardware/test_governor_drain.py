"""What `gpu-governor.sh drain` measures, exercised by running the real script.

These tests put a fake `nvidia-smi` first on `PATH` and invoke
`scripts/gpu-governor.sh drain` -- the actual file, not a reimplementation of its
arithmetic -- so what is asserted is the shipped branch rather than a tested one. The
governor calls `nvidia-smi` bare, which is what makes the injection work.

The bug they exist for is R-171. `drain` compared `--query-gpu=memory.used` against a
1500 MiB floor, and that reading counts **every** context on the device, graphics
included. This box runs its KDE session on the same card -- 1336-1432 MiB with nothing of
ours resident -- so the floor left 68-164 MiB of headroom for the question it was asking,
and 222 MiB of merely-*resident* ComfyUI spent it. `drain` then failed for 60 s,
`acquire chat` lost, and `/api/chat` answered 500 to every visitor, including a real one
from 96.37.45.61 at 14:58 on 2026-08-21. Raising the number only moves the coin flip: the
reading was measuring the wrong thing.

`test_desktop_baseline_alone_drains` is the one that was red before the fix. It is written
from the measured numbers of that trace rather than from round ones, so it fails for the
reason the site failed.
"""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())   # backend/apps -> repo root
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"

# The fake. It answers the three queries the governor asks and nothing else, and it
# answers them out of the environment so each case is a table row rather than a file.
#
# `FAKE_COMPUTE_RC` is the interesting knob: a real `nvidia-smi` that cannot enumerate
# compute apps exits non-zero, and an unreadable query must not silently read as an empty
# card. Empty output with rc 0 is a legitimate reading -- it is what "nothing holds a CUDA
# context" looks like -- so the two cases are deliberately separable here.
FAKE = """#!/usr/bin/env bash
case "$*" in
  *query-compute-apps*)   # process_name,used_memory -- one "<path>, <mib>" row per context
    if [ "${FAKE_COMPUTE_RC:-0}" != "0" ]; then exit "${FAKE_COMPUTE_RC}"; fi
    printf '%s' "${FAKE_COMPUTE:-}"
    [ -n "${FAKE_COMPUTE:-}" ] && printf '\\n'
    ;;
  *memory.used*) echo "${FAKE_USED:-0}" ;;
  *memory.free*) echo "$(( 16303 - ${FAKE_USED:-0} ))" ;;
  *) echo "fake nvidia-smi: unhandled query: $*" >&2; exit 1 ;;
esac
exit 0
"""

# Two real rows, measured on this box 2026-08-21: chat's engine resident with weights, and
# Garrett's own ComfyUI holding a CUDA context with nothing in it. The second is the 222 MiB
# that took the site down, and it is a *foreign* process -- not one of our surfaces, not
# evictable, and not something the governor may ignore either.
WARM_CHAT = "/home/google/Symoneural/symoneural-llm/build/bin/symoneural-llm, 8340"
IDLE_COMFY = "/home/google/Symoneural/external/ComfyUI (1) (1)/ComfyUI/.venv/bin/python3, 222"
# ComfyUI resident with its weights unloaded -- what `POST /free` leaves behind, and the
# state `apps/studio/comfy.py` waits for after every render.
FREED_COMFY = "/home/google/Symoneural/symoneural-ui/main.py, 666"


class FakeCard(unittest.TestCase):
    """The harness: a fake card on PATH and one helper that runs the real subcommand.

    A base class rather than a mixin on each suite, and deliberately not a suite that the
    scoped tests subclass -- inheriting the cases as well as the helper would re-run every
    unscoped assertion under a second class name and report thirteen tests as twenty-one.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        bindir = pathlib.Path(cls._tmp.name)
        smi = bindir / "nvidia-smi"
        smi.write_text(FAKE)
        smi.chmod(0o755)
        cls.bindir = str(bindir)
        # Fake readings must not be written into run/governor.log. R-171 was diagnosed out
        # of that file, and a synthetic "drain FAILED: still 9772 MiB" line sitting in it
        # would be a trap laid for the next diagnosis.
        cls.logfile = str(bindir / "governor.log")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def drain(self, compute="", used=0, compute_rc=0, timeout_s=2, pat=None):
        env = dict(os.environ)
        env["PATH"] = self.bindir + os.pathsep + env.get("PATH", "")
        env["FAKE_COMPUTE"] = compute
        env["FAKE_USED"] = str(used)
        env["FAKE_COMPUTE_RC"] = str(compute_rc)
        env["SYMONEURAL_GOVERNOR_LOG"] = self.logfile
        # The failure path polls for DRAIN_TIMEOUT_S, which is 60 s in service. Two failing
        # cases at 60 s would add two minutes to a 124 s suite, so the timeout is
        # overridable -- and the poll itself is what is under test, not its duration.
        env["SYMONEURAL_DRAIN_TIMEOUT_S"] = str(timeout_s)
        argv = [str(GOVERNOR), "drain"] + ([pat] if pat else [])
        p = subprocess.run(argv, env=env,
                           capture_output=True, text=True, timeout=120)
        # log() tees to stderr, so the reading the governor took is readable here.
        return p.returncode, p.stderr


class DrainTests(FakeCard):
    """`drain` with no argument: is the card clear of CUDA contexts."""

    def test_desktop_baseline_alone_drains(self):
        """R-171 exactly: the card reads 1558 MiB and none of it is a tenant.

        1336 MiB of KDE plus a 222 MiB idle ComfyUI CUDA context. Nothing holding weights,
        nothing to wait for -- and the old floor refused to hand over for 60 s.
        """
        rc, err = self.drain(compute=IDLE_COMFY, used=1558)
        self.assertEqual(rc, 0, f"drain refused an idle card:\n{err}")
        self.assertIn("222 MiB", err)

    def test_nothing_resident_drains_immediately(self):
        """No CUDA context at all, desktop busy. Empty compute output reads as 0, not as
        an error."""
        rc, err = self.drain(compute="", used=1432)
        self.assertEqual(rc, 0, err)
        self.assertIn("settled at 0 MiB", err)

    def test_a_tenant_that_has_not_let_go_still_fails(self):
        """The case drain exists for: llama-server resident at 8340 MiB.

        This is the assertion that stops the fix from being "always return 0". A tenant
        still holding weights must not be handed over, or the next surface allocates into
        memory that is still held and dies at step 0.
        """
        rc, err = self.drain(compute=WARM_CHAT, used=9772)
        self.assertEqual(rc, 1)
        self.assertIn("FAILED", err)
        self.assertIn("8340 MiB", err)

    def test_two_contexts_are_summed(self):
        """Compute memory is a sum over contexts, not the first row.

        Reading only `head -1` would see 8340 and hand over a card holding 8562 -- and it
        is the second row that a scoped drain has to be able to pick out.
        """
        rc, err = self.drain(compute=WARM_CHAT + "\n" + IDLE_COMFY, used=13500)
        self.assertEqual(rc, 1)
        self.assertIn("8562 MiB", err)

    def test_unreadable_compute_query_falls_back_and_says_so(self):
        """`nvidia-smi` cannot enumerate compute apps: fail open, loudly.

        Failing *closed* would wedge the card on a driver hiccup; failing open silently
        would hand it over on no evidence at all. So the whole-card reading and its own
        wider floor are used, and the log says which reading was taken -- the split
        between the two figures is the only reason R-171 was diagnosable.
        """
        rc, err = self.drain(compute="", used=1432, compute_rc=9)
        self.assertEqual(rc, 0, err)
        self.assertIn("unreadable", err)
        self.assertIn("card-wide", err)

    def test_fallback_still_refuses_a_full_card(self):
        rc, err = self.drain(compute="", used=9772, compute_rc=9)
        self.assertEqual(rc, 1)
        self.assertIn("FAILED", err)

    def test_non_numeric_reading_falls_back(self):
        """`[N/A]` and `[Not Supported]` are real readings from real drivers."""
        rc, err = self.drain(compute="/some/proc, [Not Supported]", used=1432)
        self.assertEqual(rc, 0, err)
        self.assertIn("unreadable", err)

    def test_log_line_carries_both_figures(self):
        """The compute figure and the card figure, in one line, labelled.

        A single number in this log is what made R-171 take an afternoon: `drain settled at
        1336 MiB` and `drain FAILED: still 1558 MiB` are indistinguishable from a tenant
        that will not let go unless you already know the desktop is on the card.
        """
        rc, err = self.drain(compute=IDLE_COMFY, used=1558)
        self.assertEqual(rc, 0, err)
        self.assertIn("compute", err)
        self.assertIn("1558 MiB", err)


class ScopedDrainTests(FakeCard):
    """`drain <proc-substring>` asks whether one process let go, not whether the card is clear.

    `symoneural-ui.sh stop` is the caller. Unscoped is wrong there and misleadingly so: chat
    is often legitimately warm at ~8.1 GiB, so stopping the render UI would report
    `drain FAILED` about a card doing exactly what it should -- the same
    log-says-the-wrong-thing failure this whole change exists to end.
    """

    def test_our_process_let_go_while_another_tenant_is_warm(self):
        rc, err = self.drain(compute=WARM_CHAT, used=9772,
                             pat="symoneural-ui/main.py")
        self.assertEqual(rc, 0, f"scoped drain waited on somebody else's memory:\n{err}")
        self.assertIn("settled at 0 MiB", err)
        self.assertIn("symoneural-ui/main.py", err)

    def test_our_process_has_not_let_go(self):
        rc, err = self.drain(compute="/x/symoneural-ui/main.py, 11800\n" + WARM_CHAT,
                            used=13600, pat="symoneural-ui/main.py")
        self.assertEqual(rc, 1)
        self.assertIn("11800 MiB", err)

    def test_a_freed_render_engine_counts_as_drained(self):
        """666 MiB is a live ComfyUI holding no weights, and that is what /free produces.

        `apps/studio/comfy.py` waits on exactly this after every render. A floor below 666
        would report `drained: false` about an engine that did precisely what it was asked,
        and the caller escalates from that to stopping the process -- so the floor being
        under a measured idle figure is the R-171 mistake in a new unit.
        """
        rc, err = self.drain(compute=FREED_COMFY, used=2000, pat="symoneural-ui/main.py")
        self.assertEqual(rc, 0, f"a freed render engine read as an un-drained tenant:\n{err}")
        self.assertIn("666 MiB", err)

    def test_the_unscoped_form_still_sees_a_foreign_tenant(self):
        """The reason the eviction handoff is NOT scoped.

        A foreign context is not evictable and not ignorable: the incoming surface is about
        to allocate 5-13 GB, and if something else holds 12 of them it dies at step 0
        whether or not we own the process holding them.
        """
        rc, err = self.drain(compute="/opt/somebody-elses-torch, 12000", used=13400)
        self.assertEqual(rc, 1)
        self.assertIn("12000 MiB", err)


class TheFloorIsNotCalibratedOnDesktopNoiseTests(unittest.TestCase):
    """The floor and the reading have to move together, and the source says which."""

    def setUp(self):
        self.text = GOVERNOR.read_text()

    def test_drain_does_not_read_the_whole_card_as_its_primary_measure(self):
        """`drain` must reach for the compute reader first.

        Written as an assertion on the source because the behavioural tests above can be
        satisfied by a floor raised to 2000 MiB, which is the fix R-171 says explicitly
        does not work: it moves the coin flip rather than changing what is measured.
        """
        body = self.text.split("drain() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("vram_compute_used", body)

    def test_the_compute_floor_is_below_the_desktop_baseline(self):
        """1432 MiB of KDE measured on this box. A compute floor at or above that is the
        old bug wearing the new reader's name."""
        for line in self.text.splitlines():
            if line.startswith("DRAIN_FLOOR_MIB="):
                floor = int(line.split("=", 1)[1].split()[0])
                self.assertLess(floor, 1336, "the floor is back above the desktop baseline")
                self.assertGreater(floor, 666, "the floor is under a freed ComfyUI's own idle")
                return
        self.fail("DRAIN_FLOOR_MIB is not set in gpu-governor.sh")


if __name__ == "__main__":
    unittest.main()
