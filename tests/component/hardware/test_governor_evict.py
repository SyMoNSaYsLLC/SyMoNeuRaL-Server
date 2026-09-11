"""What `gpu-governor.sh evict` and `status` say about a surface that is not running.

R-172: `run/resident` outlives the process it names, so `evict` reports killing what was
already gone, and the governor log -- the only record an eviction leaves -- cannot be read
to find out whether anything was actually freed. The ledger prescribes the fix rather than
leaving it to taste: *"`status` and `evict` both treat the marker as a hint and the process
table as the fact."*

`a944fae` claimed to resolve this and covered only the half that was already honest.
`image`, `sigil` and the `*` fallback call `pkill` directly, so their `&& active=1` is a
real reading. The two arms that call a helper script cannot work that way, because both
helpers succeed whether or not anything was running:

    bin/symoneural-cli:346        cmd_stop_chat ends `return 0` unconditionally
    scripts/symoneural-ui.sh:95   the not-running path pkills, unlinks and exits 0

`comfy` is the surface R-172 reproduced with, so the commit missed the arm the request was
written about. `TheLogFollowsTheProcessTableTests` is red at that SHA for `chat` and
`comfy` and green for `image`, which is that finding stated as a test rather than as prose.

**These run the shipped script inside a throwaway root, and never touch this box.** The
file is copied byte-for-byte out of `scripts/` on every run, so it cannot drift from what
ships -- but `ROOT` is the skeleton, so `run/resident` is a temp file and the two stop
helpers are stubs. The stubs are not a convenience: they are an accurate model, each one
`exit 0` because that is exactly what the real helper does on the path under test. Running
the real ones against the real root would kill whatever is genuinely resident on the card,
which is not a side effect a unit test may have.

`TheMinerArmIsValidPythonTests` exists because `bash -n` passes over `gpu-governor.sh`
while line 204's `python3 -c` string does not parse. Shell syntax checking cannot see
inside a quoted program, so the only way to know that arm runs is to compile it.
"""
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())   # backend/apps -> repo root
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"

# The fake card. `evict` ends in `drain`, so the script asks nvidia-smi three questions on
# every one of these runs and must get answers that mean "settled" -- otherwise every case
# would spend DRAIN_TIMEOUT_S polling and assert on a timeout instead of on the log line
# under test. Empty compute output with rc 0 is a legitimate reading: it is what "nothing
# holds a CUDA context" looks like.
FAKE_SMI = """#!/usr/bin/env bash
case "$*" in
  *query-compute-apps*) exit 0 ;;
  *memory.used*) echo 0 ;;
  *memory.free*) echo 16303 ;;
  *) echo "fake nvidia-smi: unhandled query: $*" >&2; exit 1 ;;
esac
exit 0
"""

# Both stop helpers, modelled on the path this test exercises. Neither is a simplification:
# `cmd_stop_chat` ends `return 0` with no branch that can report having stopped nothing, and
# `symoneural-ui.sh stop` reaches `echo "symoneural-ui stopped"; exit 0` through its
# not-running branch. A helper that told the truth here would make this whole suite pass at
# HEAD, so the stubs are what makes the test about `evict` rather than about them.
STUB_OK = """#!/usr/bin/env bash
echo "$0 $*: succeeded whether or not anything was running" >&2
exit 0
"""


class Skeleton(unittest.TestCase):
    """A throwaway repo root holding the real script and stubs for everything it shells to."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "backend").mkdir()
        # The governor refuses to run without this: it is the guard that turns a wrong
        # ROOT into an immediate failure instead of a silently unshared lock.
        (self.root / "backend" / "server.py").write_text("# skeleton\n")
        (self.root / "run").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "bin").mkdir()
        self.governor = self.root / "scripts" / "gpu-governor.sh"
        shutil.copy2(GOVERNOR, self.governor)          # the shipped file, not a rewrite
        for stub in (self.root / "bin" / "symoneural-cli",
                     self.root / "scripts" / "symoneural-ui.sh"):
            stub.write_text(STUB_OK)
            stub.chmod(0o755)
        self.bindir = self.root / "fakebin"
        self.bindir.mkdir()
        smi = self.bindir / "nvidia-smi"
        smi.write_text(FAKE_SMI)
        smi.chmod(0o755)
        # Fake readings must not reach run/governor.log. R-171 was diagnosed out of that
        # file and a synthetic line in it would be a trap laid for the next diagnosis.
        self.logfile = self.root / "governor.log"

    def tearDown(self):
        self._tmp.cleanup()

    def run_governor(self, *argv, resident=None):
        if resident is not None:
            (self.root / "run" / "resident").write_text(resident)
        env = dict(os.environ)
        env["PATH"] = str(self.bindir) + os.pathsep + env.get("PATH", "")
        env["SYMONEURAL_GOVERNOR_LOG"] = str(self.logfile)
        env["SYMONEURAL_DRAIN_TIMEOUT_S"] = "2"
        p = subprocess.run([str(self.governor), *argv], env=env,
                           capture_output=True, text=True, timeout=120)
        # log() tees to stderr, so the reading the governor took is readable here.
        return p.returncode, p.stdout, p.stderr

    def evict(self, surface):
        """`evict` is internal, so drive it the way `acquire` does: a foreign marker."""
        rc, out, err = self.run_governor("acquire", "sigil", "5", resident=surface)
        return rc, out, err


class TheLogFollowsTheProcessTableTests(Skeleton):
    """Every arm, with nothing of that surface running. The log must say so.

    Red at a944fae for `chat` and `comfy`, green for `image` -- the exit-code inference the
    commit added works only where the stop action is a bare `pkill`.
    """

    def assert_stale(self, surface, err):
        self.assertIn("treating as stale", err,
                      f"evict '{surface}' over a dead marker did not report it stale:\n{err}")
        self.assertNotIn("stopping '%s'" % surface, err,
                         f"evict '{surface}' claimed to stop a process that was not running:\n{err}")

    def test_chat_over_a_dead_marker_reports_stale(self):
        _, _, err = self.evict("chat")
        self.assert_stale("chat", err)

    def test_comfy_over_a_dead_marker_reports_stale(self):
        # The surface R-172 was reported against, and the one a944fae left broken.
        _, _, err = self.evict("comfy")
        self.assert_stale("comfy", err)

    def test_image_over_a_dead_marker_reports_stale(self):
        _, _, err = self.evict("image")
        self.assert_stale("image", err)

    def test_miner_over_a_dead_marker_reports_stale(self):
        _, _, err = self.evict("miner")
        self.assert_stale("miner", err)

    def test_an_unknown_surface_over_a_dead_marker_reports_stale(self):
        _, _, err = self.evict("something-nobody-registered")
        self.assert_stale("something-nobody-registered", err)

    def test_the_marker_is_cleared_either_way(self):
        self.evict("comfy")
        self.assertFalse((self.root / "run" / "resident").read_text().strip() == "comfy",
                         "a stale marker survived the eviction that read it")

    def test_a_dead_marker_does_not_block_the_acquire(self):
        # The point of the whole exercise: a surface that is gone must not cost the next
        # tenant the card. R-171 is what that failure looks like from the visitor's side.
        rc, _, err = self.evict("comfy")
        self.assertEqual(rc, 0, f"acquire failed behind a dead marker:\n{err}")


class TheStopHelpersCannotReportFailureTests(unittest.TestCase):
    """Why exit-code inference cannot work for two of the arms -- read off the real files.

    This is the one assertion in the file that reads source rather than running anything,
    and it is here so that a future change making either helper honest shows up as a red
    line telling you this suite's premise has moved, rather than as two tests that quietly
    stop testing what they claim to.
    """

    def test_cmd_stop_chat_returns_zero_unconditionally(self):
        src = (ROOT / "bin" / "symoneural-cli").read_text()
        body = re.search(r"def cmd_stop_chat\(.*?\n(.*?)\n\n", src, re.S)
        self.assertIsNotNone(body, "cmd_stop_chat not found in bin/symoneural-cli")
        returns = re.findall(r"^\s+return (.+)$", body.group(1), re.M)
        self.assertEqual(returns, ["0"],
                         "cmd_stop_chat now has a branch that can report failure -- "
                         "the premise of TheLogFollowsTheProcessTableTests has changed")

    def test_symoneural_ui_stop_exits_zero_when_nothing_was_running(self):
        src = (ROOT / "scripts" / "symoneural-ui.sh").read_text()
        self.assertIn("symoneural-ui stopped", src)
        self.assertNotIn("exit 1", src.split("stop)")[-1][:1200],
                         "symoneural-ui.sh stop now has a failure exit -- see the docstring")


class TheMinerArmIsValidPythonTests(unittest.TestCase):
    """`bash -n` cannot see inside a `python3 -c` string, so compile the one that is in there.

    a944fae collapsed the quoted $ROOT interpolation into three consecutive double quotes
    followed by /backend/apps, which raises `SyntaxError: unterminated triple-quoted string
    literal` -- see `test_the_broken_literal_is_gone`. The arm then always fell
    through to its pgid `pkill`, and nothing anywhere went red: the shell parses fine, the
    miner is inert without SYMONEURAL_MINER_CMD, and `run/miner.pid` does not exist.
    """

    def setUp(self):
        self.src = GOVERNOR.read_text()

    def test_the_miner_arm_compiles(self):
        m = re.search(r"python3 -c (.+?cryptominer\.stop\(\)')", self.src, re.S)
        self.assertIsNotNone(m, "the miner arm's python3 -c program is gone")
        # Let shlex do the quote-splicing rather than a regex: the argument is written as
        # \'...\'"$ROOT"\'...\', three adjacent quoted runs that the shell concatenates into
        # one word, and a non-greedy regex stops at the first inner quote and hands back a
        # fragment that would fail to compile for a reason that is not the bug. $ROOT is
        # substituted first because the shell expands it before python ever sees it.
        program = shlex.split(m.group(1).replace('"$ROOT"', "/repo"))[0]
        compile(program, "<miner-arm>", "exec")

    def test_the_broken_literal_is_gone(self):
        self.assertNotIn('"""/backend/apps', self.src,
                         "the collapsed $ROOT interpolation from a944fae is back")


class StatusReadsTheProcessTableTests(Skeleton):
    """`status` printed the marker and nothing else, which is the same defect one surface on.

    R-172 names `status` explicitly alongside `evict`. A line reading
    `resident surface   comfy` over a dead process is not a smaller truth than a wrong one:
    it is the reading somebody uses to decide the card is busy.
    """

    def test_a_dead_marker_is_reported_as_not_running(self):
        _, out, _ = self.run_governor("status", resident="comfy")
        line = [l for l in out.splitlines() if l.startswith("resident surface")]
        self.assertTrue(line, f"no resident line in status output:\n{out}")
        self.assertIn("comfy", line[0])
        self.assertRegex(line[0], r"not running|stale|no process",
                         "status reported a marker with nothing behind it as though the "
                         "surface were live:\n" + line[0])

    def test_no_marker_reads_none(self):
        _, out, _ = self.run_governor("status")
        self.assertIn("resident surface   none", out)


if __name__ == "__main__":
    unittest.main()
