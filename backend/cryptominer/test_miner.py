#!/usr/bin/env python3
"""Tests for the GPU miner surface. System interpreter, no GPU, nothing is ever started.

    python3 backend/cryptominer/test_miner.py

The hashrate parser is the part worth testing hardest, and the reason is a bug that shipped:
the regex required a literal `/s`, kawpowminer prints `48.51 Mh` without one, and so a
healthy miner reported "no hashrate reported yet" for its entire run. Nothing caught it
because the only test data anyone had was invented, and an invented line has `/s` in it
because that is how a human writes a hashrate.

So the fixture in `testdata/kawpowminer-1.2.4-sm120-bench.log` is **not written by hand**.
It is the byte-for-byte stdout of

    scripts/gpu-governor.sh with minerbuild -- \\
      timeout -s INT 150 contrib/kawpowminer/build/kawpowminer/kawpowminer -U -M 500000

captured on this box on 2026-08-17 — ANSI colour, interleaved governor lines and all. Any
future parser change has to keep passing against those exact bytes.

One limit stated plainly: that capture is `-M` simulation mode, because running against a
live pool needs a wallet this repo does not have. The speed line it produces
(`m HH:MM:SS kawpowminer 0:00 A2 48.51 Mh - cu0 48.51`) is emitted by kawpowminer's shared
`Farm`/telemetry path rather than by anything simulation-specific, and the `A2` accepted
counter in it increments from real accepted solutions during the run — but it is
benchmark-mode output and is labelled as such here rather than claimed as production.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))           # backend/apps, as backend/server.py does
import cryptominer  # noqa: E402

FIXTURE = HERE / "testdata" / "kawpowminer-1.2.4-sm120-bench.log"


class _WithLog:
    """Point the module's LOGFILE at a temporary file for the duration of a test."""

    def __init__(self, text: str | bytes):
        self.data = text.encode() if isinstance(text, str) else text

    def __enter__(self) -> pathlib.Path:
        fd, name = tempfile.mkstemp(prefix="miner-test-", suffix=".log")
        os.write(fd, self.data)
        os.close(fd)
        self.path = pathlib.Path(name)
        self.saved = cryptominer.LOGFILE
        cryptominer.LOGFILE = self.path
        return self.path

    def __exit__(self, *exc):
        cryptominer.LOGFILE = self.saved
        self.path.unlink(missing_ok=True)


def hashrate(text: str | bytes) -> float | None:
    with _WithLog(text):
        return cryptominer._hashrate_from_log()


# --------------------------------------------------------------- the real capture

class TestRealKawpowminerOutput(unittest.TestCase):
    """Against the captured bytes, not against a string somebody typed."""

    def setUp(self):
        self.assertTrue(FIXTURE.is_file(), f"missing capture: {FIXTURE}")
        self.raw = FIXTURE.read_bytes()

    def test_the_capture_really_has_no_slash_s(self):
        # If this ever fails the fixture has been edited, and the bug it pins is unpinned.
        self.assertIn(b"48.51 Mh", self.raw)
        self.assertNotIn(b"Mh/s", self.raw)
        self.assertNotIn(b"MH/s", self.raw)

    def test_the_old_regex_would_have_found_nothing(self):
        import re
        old = re.compile(r"(\d+(?:\.\d+)?)\s*(h|kh|mh|gh|th)/s", re.I)
        self.assertIsNone(old.search(self.raw.decode("utf-8", "replace")),
                          "the shipped regex matched after all — rewrite this test")

    def test_parses_the_capture(self):
        # Last line of the run is the summary: `Max 52.631720 Mh Mean 48.357568 Mh`.
        # The mean is the honest steady figure and is what the parser must report.
        self.assertAlmostEqual(hashrate(self.raw), 48.36, places=2)

    def test_a_mid_run_tail_parses_to_that_line_s_figure(self):
        # Cut the capture where a real poll would land: mid-run, last line a speed line.
        text = self.raw.decode("utf-8", "replace")
        cut = text.index("48.36 Mh")            # the 10:05:49 sample
        tail = text[:cut] + "48.36 Mh\x1b[0m - cu0 \x1b[36m48.36\x1b[0m\n"
        self.assertAlmostEqual(hashrate(tail), 48.36, places=2)

    def test_the_difficulty_line_is_not_read_as_a_rate(self):
        # `Epoch : 66 Difficulty : 4.29 Gh` is a share target. Read as a rate it is
        # 4290 MH/s from a card doing 48, and the rack would publish it.
        line = ("\x1b[94m i \x1b[35m10:03:24 \x1b[94msim       \x1b[0mEpoch : "
                "\x1b[97m66\x1b[0m Difficulty : \x1b[97m4.29 Gh\x1b[0m\n")
        self.assertIsNone(hashrate(line))
        self.assertAlmostEqual(hashrate("48.51 Mh\n" + line), 48.51, places=2)


# --------------------------------------------------------------- both spellings

class TestUnitsAndSpellings(unittest.TestCase):

    def test_bare_unit_no_slash_s(self):
        self.assertAlmostEqual(hashrate("A2 48.51 Mh - cu0 48.51"), 48.51)

    def test_with_slash_s(self):
        self.assertAlmostEqual(hashrate("GPU0: 51.14 MH/s kawpow"), 51.14)

    def test_no_space_before_unit_requires_slash_s(self):
        # t-rex prints `51.14MH/s`. Allowed, because /s disambiguates it.
        self.assertAlmostEqual(hashrate("51.14MH/s"), 51.14)

    def test_slash_sec_still_matches(self):
        self.assertAlmostEqual(hashrate("total 48.51 Mh/sec"), 48.51)

    def test_every_scale(self):
        for text, want in [("48510000 h/s", 48.51), ("48510 kh", 48.51),
                           ("48.51 Mh", 48.51), ("0.04851 Gh", 48.51),
                           ("0.00004851 Th/s", 48.51)]:
            self.assertAlmostEqual(hashrate(text), 48.51, places=2, msg=text)

    def test_case_insensitive(self):
        for text in ("48.51 mh", "48.51 MH", "48.51 Mh", "48.51 mH/S"):
            self.assertAlmostEqual(hashrate(text), 48.51, msg=text)

    def test_integer_without_a_decimal_point(self):
        self.assertAlmostEqual(hashrate("48 Mh"), 48.0)


# --------------------------------------------------------------- what must NOT match

class TestFalsePositives(unittest.TestCase):

    def test_english_ordinals_are_not_terahashes(self):
        # `4th` -> 4 TH/s -> 4,000,000 MH/s. This is why a space is required when there
        # is no `/s`.
        for junk in ("mining the 4th block", "on its 20th attempt", "1st 2nd 3rd 4th"):
            self.assertIsNone(hashrate(junk), junk)

    def test_hours_are_not_hashes(self):
        for junk in ("up for 5 hours", "ran 12 hrs", "eta 3 hours 20 min"):
            self.assertIsNone(hashrate(junk), junk)

    def test_a_number_and_a_unit_on_different_lines_do_not_join(self):
        # `\s` matches a newline; the tail interleaves governor lines with miner output,
        # so this is a live hazard rather than a hypothetical one.
        self.assertIsNone(hashrate("Generated DAG + Light in 591\nhash target reached"))

    def test_governor_lines_alone_report_nothing(self):
        gov = ("2026-08-17 09:07:57  wait     'miner' wants the card\n"
               "2026-08-17 09:07:57  drain    settled at 970 MiB after 0s (floor 1500 MiB)\n"
               "2026-08-17 09:07:57  acquire  'miner' holds the card -- 14889 MiB free, waited 0s\n")
        self.assertIsNone(hashrate(gov))

    def test_megabytes_and_gigabytes_are_not_hashrates(self):
        self.assertIsNone(hashrate("Generating DAG + Light : 1.54 GB. 13.95 GB left."))

    def test_empty_and_missing(self):
        self.assertIsNone(hashrate(""))
        cryptominer.LOGFILE, saved = pathlib.Path("/nonexistent/miner.log"), cryptominer.LOGFILE
        try:
            self.assertIsNone(cryptominer._hashrate_from_log())
        finally:
            cryptominer.LOGFILE = saved


class TestRunMarker(unittest.TestCase):
    """A fresh run must not inherit the previous run's last number."""

    def test_output_before_the_marker_is_ignored(self):
        log = ("[10:05:49] 48.51 Mh - cu0 48.51\n"
               "Simulation results : Max 52.63 Mh Mean 48.35 Mh\n"
               f"\n{cryptominer.RUN_MARKER} 2026-08-17 11:00:00 ===\n"
               "kawpowminer 1.2.4\nGenerating DAG + Light : 1.54 GB\n")
        self.assertIsNone(hashrate(log),
                          "reported the previous run's figure while the DAG was building")

    def test_output_after_the_marker_is_read(self):
        log = ("[10:05:49] 99.99 Mh\n"
               f"\n{cryptominer.RUN_MARKER} 2026-08-17 11:00:00 ===\n"
               "[11:00:20] 48.51 Mh\n")
        self.assertAlmostEqual(hashrate(log), 48.51)


# --------------------------------------------------------------- the gate

class TestOffByDefault(unittest.TestCase):
    """Nothing in this module may arm mining on its own."""

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in
                      ("SYMONEURAL_MINING_ENABLED", "SYMONEURAL_MINER_CMD", "SYMONEURAL_MINER_CMD",
                       "SYMONEURAL_MINER_ENV")}
        for k in self.saved:
            os.environ.pop(k, None)
        self.envdir = tempfile.TemporaryDirectory()
        self.envfile = pathlib.Path(self.envdir.name) / "miner.env"
        self.saved_envfile = cryptominer.ENVFILE
        cryptominer.ENVFILE = self.envfile
        cryptominer._env_key = None
        cryptominer._env_applied.clear()

    def tearDown(self):
        cryptominer.ENVFILE = self.saved_envfile
        cryptominer._env_key = None
        cryptominer._env_applied.clear()
        self.envdir.cleanup()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_config_means_offline(self):
        self.assertFalse(cryptominer.enabled())
        state, detail = cryptominer.unit_state()
        self.assertEqual(state, "offline")
        self.assertIn("SYMONEURAL_MINING_ENABLED=1", detail)

    def test_the_shipped_example_arms_nothing(self):
        # Somebody will `cp miner.env.example miner.env` and walk away. That must be inert.
        example = HERE / "miner.env.example"
        self.assertTrue(example.is_file())
        self.envfile.write_text(example.read_text())
        self.assertFalse(cryptominer.enabled(),
                         "copying the example turned mining ON — it must ship disabled")

    def test_all_three_are_required(self):
        cmd = "/bin/echo mining"
        for missing in ("SYMONEURAL_MINING_ENABLED", "SYMONEURAL_MINER_CMD", "SYMONEURAL_MINER_CMD"):
            lines = {"SYMONEURAL_MINING_ENABLED": "1", "SYMONEURAL_MINER_CMD": cmd,
                     "SYMONEURAL_MINER_CMD": "s3cret"}
            lines.pop(missing)
            self.envfile.write_text("".join(f"{k}={v}\n" for k, v in lines.items()))
            cryptominer._env_key = None
            cryptominer._env_applied.clear()
            for k in ("SYMONEURAL_MINING_ENABLED", "SYMONEURAL_MINER_CMD", "SYMONEURAL_MINER_CMD"):
                os.environ.pop(k, None)
            self.assertFalse(cryptominer.enabled(), f"enabled without {missing}")

    def test_a_full_config_enables_and_reads_ready(self):
        self.envfile.write_text("SYMONEURAL_MINING_ENABLED=1\n"
                                "SYMONEURAL_MINER_CMD=/bin/echo mining\n"
                                "SYMONEURAL_MINER_CMD=/x/miner\n")
        self.assertTrue(cryptominer.enabled())
        self.assertEqual(cryptominer.unit_state()[0], "ready")

    def test_an_edit_is_picked_up_without_a_restart(self):
        self.envfile.write_text("SYMONEURAL_MINING_ENABLED=0\n")
        self.assertFalse(cryptominer.enabled())
        os.utime(self.envfile, (0, 0))          # force a distinct mtime
        self.envfile.write_text("SYMONEURAL_MINING_ENABLED=1\n"
                                "SYMONEURAL_MINER_CMD=/bin/echo mining\n"
                                "SYMONEURAL_MINER_CMD=/x/miner\n")
        self.assertTrue(cryptominer.enabled(),
                        "the file changed and enabled() did not notice")

    def test_a_real_exported_variable_beats_the_file(self):
        os.environ["SYMONEURAL_MINING_ENABLED"] = "0"
        self.envfile.write_text("SYMONEURAL_MINING_ENABLED=1\nSYMONEURAL_MINER_CMD=/bin/echo\n"
                                "SYMONEURAL_MINER_CMD=/x/miner\n")
        cryptominer.load_env(force=True)
        self.assertEqual(os.environ["SYMONEURAL_MINING_ENABLED"], "0",
                         "the file overrode a variable the operator exported")

    def test_the_file_cannot_set_arbitrary_variables(self):
        self.envfile.write_text("LD_PRELOAD=/tmp/evil.so\nPATH=/tmp\n"
                                "SYMONEURAL_MINER_CMD=/x/miner\n")
        report = cryptominer.load_env(force=True)
        self.assertNotEqual(os.environ.get("LD_PRELOAD"), "/tmp/evil.so")
        self.assertNotEqual(os.environ.get("PATH"), "/tmp")
        self.assertIn("LD_PRELOAD", report["ignored_keys"])

    def test_quotes_and_comments(self):
        self.envfile.write_text('# a comment\n\nexport SYMONEURAL_MINER_CMD="/x/miner --algo kawpow"\n')
        cryptominer.load_env(force=True)
        self.assertEqual(os.environ["SYMONEURAL_MINER_CMD"], "/x/miner --algo kawpow")

    def test_a_missing_binary_is_offline_not_ready(self):
        self.envfile.write_text("SYMONEURAL_MINING_ENABLED=1\n"
                                "SYMONEURAL_MINER_CMD=/no/such/miner --algo kawpow\n"
                                "SYMONEURAL_MINER_CMD=/x/miner\n")
        self.assertEqual(cryptominer.unit_state()[0], "offline")



    def test_start_refuses_when_disabled(self):
        import asyncio
        out = asyncio.run(cryptominer.start())
        self.assertFalse(out["ok"])
        self.assertIn("disabled", out["error"])


class TestUnitStateValues(unittest.TestCase):
    """The four strings api.py's Unit model will accept, and nothing else."""

    ALLOWED = {"ready", "busy", "queued", "offline"}

    def test_every_branch_returns_a_legal_state(self):
        cases = [
            {"enabled": False, "installed": False, "running": False},
            {"enabled": True, "installed": False, "running": False},
            {"enabled": True, "installed": True, "running": False},
            {"enabled": True, "installed": True, "running": True,
             "holds_gpu_lock": False, "lock_holder": "chat"},
            {"enabled": True, "installed": True, "running": True,
             "holds_gpu_lock": True, "hashrate_mh_s": None},
            {"enabled": True, "installed": True, "running": True,
             "holds_gpu_lock": True, "hashrate_mh_s": 48.51, "hashrate_age_s": 3},
            {"enabled": True, "installed": True, "running": True,
             "holds_gpu_lock": True, "hashrate_mh_s": 48.51, "hashrate_age_s": 600},
        ]
        for st in cases:
            state, detail = cryptominer.unit_state(st)
            self.assertIn(state, self.ALLOWED, st)
            self.assertTrue(detail, st)

    def test_a_started_miner_that_has_not_won_the_lock_is_queued_not_busy(self):
        st = {"enabled": True, "installed": True, "running": True,
              "holds_gpu_lock": False, "lock_holder": "image"}
        state, detail = cryptominer.unit_state(st)
        self.assertEqual(state, "queued")
        self.assertIn("image", detail)

    def test_a_hashrate_is_never_shown_without_the_miner_having_reported_it(self):
        st = {"enabled": True, "installed": True, "running": True,
              "holds_gpu_lock": True, "hashrate_mh_s": None}
        self.assertNotIn("MH/s", cryptominer.unit_state(st)[1])

    def test_a_stalled_miner_says_so_beside_the_number(self):
        st = {"enabled": True, "installed": True, "running": True,
              "holds_gpu_lock": True, "hashrate_mh_s": 48.51, "hashrate_age_s": 600}
        self.assertIn("no output for 600s", cryptominer.unit_state(st)[1])


class TestPidfile(unittest.TestCase):

    def setUp(self):
        self.saved = cryptominer.PIDFILE
        self.tmp = tempfile.TemporaryDirectory()
        cryptominer.PIDFILE = pathlib.Path(self.tmp.name) / "miner.pid"

    def tearDown(self):
        cryptominer.PIDFILE = self.saved
        self.tmp.cleanup()

    def test_no_pidfile_is_not_running(self):
        self.assertFalse(cryptominer.running())

    def test_garbage_pidfile_is_not_running(self):
        cryptominer.PIDFILE.write_text("not a number")
        self.assertFalse(cryptominer.running())

    def test_a_dead_pid_is_not_running(self):
        cryptominer.PIDFILE.write_text("999999")
        self.assertFalse(cryptominer.running())

    def test_a_live_pid_that_is_not_ours_is_not_running(self):
        # Pid reuse. Our own pid is alive and is emphatically not gpu-governor.sh, so
        # this stands in for a recycled pid — which, trusted, would make stop() SIGTERM
        # a process group belonging to somebody else.
        cryptominer.PIDFILE.write_text(str(os.getpid()))
        self.assertFalse(cryptominer.running(),
                         "a recycled pid was accepted as the miner")

    def test_a_zombie_is_not_running(self):
        # The miner is a child of the API process, so between its exit and the reap it is
        # a zombie -- and `os.kill(pid, 0)` succeeds against a zombie. /proc/<pid>/cmdline
        # is empty for one, which is what actually settles it.
        pid = os.fork()
        if pid == 0:
            os._exit(0)                        # noqa: SLF001 -- child, never returns
        try:
            for _ in range(200):               # let it become a zombie
                if pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z":
                    break
                time.sleep(0.01)
            cryptominer.PIDFILE.write_text(str(pid))
            os.kill(pid, 0)                    # the premise: signal 0 still succeeds
            self.assertFalse(cryptominer.running(),
                             "a zombie was reported as a running miner")
        finally:
            os.waitpid(pid, 0)

    def test_stop_on_a_stale_pidfile_is_a_no_op_and_clears_it(self):
        cryptominer.PIDFILE.write_text("999999")
        out = cryptominer.stop()
        self.assertTrue(out["ok"])
        self.assertIsNone(out["stopped"])
        self.assertFalse(cryptominer.PIDFILE.exists())


class TestGovernorContract(unittest.TestCase):
    """The command this module hands the governor is the whole GPU-safety story."""

    def test_it_is_the_with_form_and_the_surface_is_named(self):
        src = (HERE / "__init__.py").read_text()
        self.assertIn('[str(GOVERNOR), "with", SURFACE, "--", *argv]', src,
                      "start() no longer uses `gpu-governor.sh with <surface> --`, "
                      "which is the form that releases the card even on a crash")

    def test_the_surface_name_matches_the_governor_s_case_arm(self):
        gov = (cryptominer.ROOT / "scripts" / "gpu-governor.sh").read_text()
        self.assertIn(f"    {cryptominer.SURFACE})", gov,
                      f"gpu-governor.sh has no `{cryptominer.SURFACE})` arm — eviction "
                      "would fall through to the '*)' arm and pkill the LLM engine instead")

    def test_no_bare_release_anywhere_in_this_module(self):
        import re as _re
        src = (HERE / "__init__.py").read_text()
        for m in _re.finditer(r'"release"', src):
            self.fail("this module calls the governor's `release` directly; it must only "
                      "ever use the `with` form, which names the surface on both halves")

    def test_stop_signals_the_group_not_the_pid(self):
        src = (HERE / "__init__.py").read_text()
        self.assertIn("os.killpg", src)
        self.assertNotIn("os.kill(pid, signal.SIGTERM)", src)


class _Cmd:
    """Run a test against one `SYMONEURAL_MINER_CMD`, with the env file out of the way.

    The file is pointed at a path that does not exist, so `load_env()` finds nothing and the
    exported variable is the only source. Without this a developer's own `miner.env` would
    decide the result and the suite would pass or fail depending on whose box it ran on.
    """

    def __init__(self, cmd: str):
        self.cmd = cmd

    def __enter__(self):
        self.saved_file = cryptominer.ENVFILE
        self.saved_cmd = os.environ.get("SYMONEURAL_MINER_CMD")
        self.saved_key = cryptominer._env_key
        cryptominer.ENVFILE = pathlib.Path(tempfile.gettempdir()) / "sym-no-such-miner.env"
        cryptominer._env_key = None
        cryptominer._env_applied.clear()
        os.environ["SYMONEURAL_MINER_CMD"] = self.cmd
        return self

    def __exit__(self, *exc):
        cryptominer.ENVFILE = self.saved_file
        cryptominer._env_key = self.saved_key
        cryptominer._env_applied.clear()
        if self.saved_cmd is None:
            os.environ.pop("SYMONEURAL_MINER_CMD", None)
        else:
            os.environ["SYMONEURAL_MINER_CMD"] = self.saved_cmd


class TestPoolDetection(unittest.TestCase):
    """A miner with nowhere to submit a share earns nothing, and must say so.

    The discriminator is the absence of a pool URL, not the presence of `-M`. kawpowminer's
    own `-H test` output: "When playing with benchmark or simulation no connection
    specification is needed ie. you can omit any -P argument."
    """

    def test_the_benchmark_command_that_shipped_names_no_pool(self):
        # This is verbatim what miner.env on this box was set to while the rack was
        # reporting 53.01 MH/s as though the machine were mining.
        with _Cmd("/usr/bin/kawpowminer -U -M 500000"):
            self.assertIsNone(cryptominer.pool())
            self.assertTrue(cryptominer.benchmarking())

    def test_a_pool_is_found_in_both_flag_forms(self):
        for cmd in ("/usr/bin/kawpowminer -U -P stratum+tcp://rvn.pool.example:4444",
                    "/usr/bin/kawpowminer -U --pool stratum+tcp://rvn.pool.example:4444",
                    "/usr/bin/kawpowminer -U --pool=stratum+tcp://rvn.pool.example:4444",
                    "/usr/bin/kawpowminer -U stratum+tcp://rvn.pool.example:4444"):
            with _Cmd(cmd):
                self.assertEqual(cryptominer.pool(),
                                 "stratum+tcp://rvn.pool.example:4444", cmd)
                self.assertFalse(cryptominer.benchmarking(), cmd)

    def test_the_wallet_and_password_never_come_back_out(self):
        wallet = "RJ7cbCJ3xQTHkV8VgTgFcHrCJcpsVwXBFq.rig1"
        with _Cmd(f"/usr/bin/kawpowminer -P stratum+tcp://{wallet}:p@ss@rvn.example:4444"):
            got = cryptominer.pool()
            self.assertEqual(got, "stratum+tcp://rvn.example:4444")
            self.assertNotIn(wallet.split(".")[0], got)
            self.assertNotIn("p@ss", got)
            # and not via the whole status payload either, which /api/gpuminer/status
            # serialises wholesale
            import json as _json
            blob = _json.dumps(cryptominer.status())
            self.assertNotIn("p@ss", blob)

    def test_a_url_belonging_to_another_flag_is_not_read_as_a_pool(self):
        # Under-disclosure is the dangerous direction: mistake this for a pool and the
        # benchmark caveat switches itself off while the rack shows a real hashrate.
        # A bare http URL is included on purpose: kawpowminer does accept an http getWork
        # pool, but `--api-bind` takes an http URL too, so the bare form is only honoured for
        # a `stratum*` scheme. An http pool must be written the documented way, with -P. The
        # cost is over-disclosure (a benchmark caveat on something that might earn), which is
        # the safe direction; the alternative silently hides the caveat.
        for cmd in ("/usr/bin/kawpowminer -U -M 500000 --api-bind http://127.0.0.1:3333",
                    "/usr/bin/kawpowminer -U -M 500000 --report-url https://logs.example/x",
                    "/usr/bin/kawpowminer -U -M 500000 http://getwork.example:8080",
                    "/usr/bin/kawpowminer -U -M 500000 --something file:///tmp/x"):
            with _Cmd(cmd):
                self.assertIsNone(cryptominer.pool(), cmd)
                self.assertTrue(cryptominer.benchmarking(),
                                f"the benchmark caveat was switched off by: {cmd}")

    def test_a_stratum_url_counts_wherever_it_appears(self):
        """A deliberate decision, pinned here so it is not "fixed" by accident.

        A `stratum*` URL is read as a pool even when it is some other flag's value. No
        kawpowminer option other than the pool options takes a stratum URL, so a stratum URL
        anywhere in the command means a pool is configured; tightening this would cost more
        than it buys. The ambiguous scheme is `http`, and that is already excluded from the
        bare form -- see `_POOL_SCHEME`.
        """
        with _Cmd("/usr/bin/kawpowminer -U -M 500000 --user stratum+tcp://x.example:4444"):
            self.assertEqual(cryptominer.pool(), "stratum+tcp://x.example:4444")
            self.assertFalse(cryptominer.benchmarking())

    def test_an_explicit_pool_flag_is_still_taken_at_its_word(self):
        # The operator naming a pool outranks scheme-guessing.
        with _Cmd("/usr/bin/kawpowminer -P stratum2+ssl://rvn.example:5555"):
            self.assertEqual(cryptominer.pool(), "stratum2+ssl://rvn.example:5555")
            self.assertFalse(cryptominer.benchmarking())

    def test_an_unconfigured_surface_is_not_called_a_benchmark(self):
        with _Cmd(""):
            self.assertFalse(cryptominer.benchmarking())
            self.assertIsNone(cryptominer.pool())

    def test_the_rack_says_a_benchmark_earns_nothing(self):
        st = {"enabled": True, "installed": True, "running": True, "holds_gpu_lock": True,
              "hashrate_mh_s": 53.01, "hashrate_age_s": 2, "benchmark": True}
        state, detail = cryptominer.unit_state(st)
        self.assertEqual(state, "busy")
        self.assertIn("53.01 MH/s", detail)        # the measurement is NOT hidden
        self.assertIn("earns nothing", detail)
        self.assertIn("benchmark", detail.lower())

    def test_a_real_pool_run_is_not_labelled_a_benchmark(self):
        st = {"enabled": True, "installed": True, "running": True, "holds_gpu_lock": True,
              "hashrate_mh_s": 53.01, "hashrate_age_s": 2, "benchmark": False}
        state, detail = cryptominer.unit_state(st)
        self.assertEqual(state, "busy")
        self.assertNotIn("earns nothing", detail)
        self.assertNotIn("benchmark", detail.lower())

    def test_ready_discloses_it_before_the_card_is_ever_taken(self):
        st = {"enabled": True, "installed": True, "running": False, "benchmark": True}
        state, detail = cryptominer.unit_state(st)
        self.assertEqual(state, "ready")
        self.assertIn("earns nothing", detail)

    def test_a_status_dict_without_the_key_still_reads_as_a_legal_state(self):
        # unit_state() is called with dicts built elsewhere; a missing key must not throw.
        st = {"enabled": True, "installed": True, "running": True, "holds_gpu_lock": True,
              "hashrate_mh_s": 53.01}
        self.assertEqual(cryptominer.unit_state(st)[0], "busy")

    def test_status_carries_both_fields(self):
        with _Cmd("/usr/bin/kawpowminer -U -M 500000"):
            st = cryptominer.status()
            self.assertIn("pool", st)
            self.assertIn("benchmark", st)
            self.assertTrue(st["benchmark"])


class TestEnvCacheKey(unittest.TestCase):
    """`_env_key` must hold the stat stamp, not the last config name parsed out of the file.

    The bug: the stat tuple and the loop variable were both called `key`, so `_env_key` ended
    up as the string "SYMONEURAL_MINER_GPU". A tuple never equals a string, the cache never hit, and
    every `enabled()` / `token_ok()` / `gpu_index()` call re-read and re-parsed the file and
    re-wrote os.environ — five file reads per `status()`, on the rack's poll path.
    """

    def setUp(self):
        self.saved_file = cryptominer.ENVFILE
        self.dir = tempfile.TemporaryDirectory()
        self.f = pathlib.Path(self.dir.name) / "miner.env"
        cryptominer.ENVFILE = self.f
        cryptominer._env_key = None
        cryptominer._env_applied.clear()

    def tearDown(self):
        cryptominer.ENVFILE = self.saved_file
        cryptominer._env_key = None
        cryptominer._env_applied.clear()
        self.dir.cleanup()

    def test_the_stamp_is_a_stat_tuple(self):
        self.f.write_text("SYMONEURAL_MINER_GPU=0\nSYMONEURAL_MINER_CMD=s3cret\n")
        cryptominer.load_env()
        self.assertIsInstance(cryptominer._env_key, tuple,
                              "_env_key is not the stat stamp — the loop variable has "
                              "shadowed it again and the cache is dead")
        self.assertEqual(len(cryptominer._env_key), 3)

    def test_the_second_read_is_a_cache_hit(self):
        self.f.write_text("SYMONEURAL_MINER_CMD=/x/miner\n")
        self.assertTrue(cryptominer.load_env()["reread"])
        self.assertFalse(cryptominer.load_env()["reread"])
        self.assertFalse(cryptominer.load_env()["reread"])

    def test_force_reads_through_the_cache(self):
        self.f.write_text("SYMONEURAL_MINER_CMD=/x/miner\n")
        cryptominer.load_env()
        self.assertTrue(cryptominer.load_env(force=True)["reread"])

    def test_every_branch_returns_the_same_shape(self):
        missing = cryptominer.load_env()                  # no file
        self.f.write_text("LD_PRELOAD=/tmp/evil.so\nSYMONEURAL_MINER_CMD=s3cret\n")
        full = cryptominer.load_env()                     # full parse
        cached = cryptominer.load_env()                   # cache hit
        for a, b in (("missing", missing), ("full", full), ("cached", cached)):
            self.assertEqual(sorted(b), ["applied", "found", "ignored_keys", "path",
                                         "reread"], a)
        self.assertEqual(full["ignored_keys"], ["LD_PRELOAD"])
        self.assertEqual(cached["ignored_keys"], ["LD_PRELOAD"],
                         "a cache hit dropped ignored_keys, so the shape of "
                         "/api/gpuminer/status changed depending on cache state")

    def test_a_deleted_and_recreated_file_is_re_read(self):
        self.f.write_text("SYMONEURAL_MINER_CMD=first\n")
        cryptominer.load_env()
        self.f.unlink()
        self.assertFalse(cryptominer.load_env()["found"])
        os.environ.pop("SYMONEURAL_MINER_CMD", None)
        cryptominer._env_applied.clear()
        self.f.write_text("SYMONEURAL_MINER_CMD=second\n")
        self.assertTrue(cryptominer.load_env()["reread"])
        self.assertEqual(os.environ.get("SYMONEURAL_MINER_CMD"), "second")


class TestDocumentation(unittest.TestCase):
    """The README is where the measured KawPow figure lives, so it must not drift.

    It is also cited by name in `selftest()`'s `note`, which is the same shape of promise
    `asicminer.probe()` made for weeks before there was a README to read.
    """

    def setUp(self):
        self.readme = HERE / "README.md"

    def test_the_readme_selftest_cites_exists(self):
        self.assertTrue(self.readme.is_file(),
                        "selftest()'s note cites README.md, which does not exist")

    def test_it_documents_every_key_the_env_file_honours(self):
        text = self.readme.read_text()
        for key in cryptominer._ENV_KEYS:
            self.assertIn(key, text, f"{key} is honoured by load_env() but undocumented")

    def test_it_documents_no_key_the_env_file_ignores(self):
        # A README naming a variable the parser drops sends an operator to debug a token.
        import re as _re
        text = self.readme.read_text()
        for name in set(_re.findall(r"\bSYMONEURAL_[A-Z_]+\b", text)):
            self.assertIn(name, cryptominer._ENV_KEYS | {"SYMONEURAL_ASIC_TOKEN", "SYMONEURAL_MINER_ENV"},
                          f"README documents {name}, which load_env() would ignore")

    def test_the_test_count_it_quotes_is_the_real_one(self):
        # The README's first verifiable claim is how many tests there are. It shipped as "60"
        # while the suite was 70, which is the exact drift this class exists to catch — and
        # it did not catch it, because nothing asserted on the number.
        import re as _re
        source = pathlib.Path(__file__).read_text()
        actual = len(_re.findall(r"^    def test_", source, _re.M))
        stated = _re.search(r"#\s*(\d+) tests", self.readme.read_text())
        self.assertIsNotNone(stated, "the README no longer states a test count")
        self.assertEqual(int(stated.group(1)), actual,
                         f"README says {stated.group(1)} tests; this file defines {actual}")

    def test_it_carries_the_measured_figure_and_labels_it(self):
        text = self.readme.read_text()
        self.assertIn("53.01", text, "the measured steady-state figure is not recorded")
        self.assertIn("measured", text.lower())
        self.assertIn("kawpowminer 1.2.4+commit.8bd0d598.dirty", text,
                      "the figure is not attributed to the binary that produced it")

    def test_it_states_the_benchmark_caveat_beside_the_figure(self):
        text = self.readme.read_text().lower()
        self.assertIn("earns nothing", text)
        self.assertIn("no pool", text)

    def test_it_quotes_the_fixture_s_own_summary_rather_than_paraphrasing(self):
        summary = "Max 52.631720 Mh Mean 48.357568 Mh"
        self.assertIn(summary, self.readme.read_text())
        with open(FIXTURE, "rb") as fh:
            self.assertIn(summary.encode(), fh.read(),
                          "the README quotes a summary line the fixture does not contain")

    def test_it_offers_no_earnings_number(self):
        # The one number this surface must never invent. Pricing goes to the mailbox.
        #
        # A bare "$" is NOT the test: the README legitimately contains `$EDITOR` and
        # `$SYMONEURAL_MINER_CMD` in shell examples. What must not appear is a currency amount or
        # a per-period rate. `assertNotRegex`'s own message quotes the whole document, which
        # for a file this size buries the finding, so each check carries a short one.
        import re as _re
        text = self.readme.read_text()
        self.assertIn("symonsayadmin@symoneural.com", text,
                      "pricing questions are not directed to the mailbox")
        for pattern, what in ((r"[$€£]\s?\d", "a currency amount"),
                              (r"\bUSD\b", "a USD figure"),
                              (r"\bper (?:day|month|year)\b", "a per-period rate"),
                              (r"/(?:day|month|year)\b", "a per-period rate"),
                              (r"\bprofit", "a profitability claim"),
                              (r"\brevenue\b", "a revenue claim")):
            self.assertIsNone(_re.search(pattern, text, _re.I),
                              f"README appears to carry {what} — this surface measures "
                              f"hashrate and never claims earnings (matched /{pattern}/)")

    def test_it_leaks_no_secret(self):
        # Guards against somebody pasting a working miner.env into the docs.
        text = self.readme.read_text()
        for token in ("SYMONEURAL_MINER_CMD=", "stratum+tcp://R"):
            self.assertNotIn(token, text, f"{token!r} looks like real config, not an example")


if __name__ == "__main__":
    unittest.main(verbosity=1)
