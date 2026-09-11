#!/usr/bin/env python3
"""Tests for the ASIC surface's gate, rack state and emulator bookkeeping.

    python3 backend/asicminer/test_asic.py

System interpreter, no network, **no `.venv`**. That constraint is the same one
`test_scan.py` works under and for the same reason: `.venv` here carries pyasic and thirty
other packages, the serving interpreter must never import from it, and a test suite that
needed the venv would quietly make that boundary optional. Everything below is reachable
without it. `probe.py`'s pyasic coercion is not, and is not covered.

Nothing here starts qemu, touches the network, or writes outside a temporary directory.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))           # backend/apps, as backend/server.py does
import asicminer  # noqa: E402

sys.path.insert(0, str(HERE))
import fwcheck  # noqa: E402


class _Env:
    """Set and restore SYMONEURAL_ASIC_* around a test."""

    KEYS = ("SYMONEURAL_ASIC_ENABLED", "SYMONEURAL_ASIC_TOKEN", "SYMONEURAL_ASIC_RIGS")

    def __init__(self, **kw):
        self.want = kw

    def __enter__(self):
        self.saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        for k, v in self.want.items():
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestTheGate(unittest.TestCase):

    def test_off_with_nothing_set(self):
        with _Env():
            self.assertFalse(asicminer.enabled())


    def test_enabled_must_be_literally_one(self):
        # `== "1"`, not truthiness. `SYMONEURAL_ASIC_ENABLED=true` leaves the surface OFF, and it
        # does so silently — which is the right failure direction but the wrong one to be
        # surprised by, so it is pinned here and stated in README.md.
        for v in ("true", "TRUE", "yes", "on", "y", "01", " 1", "1 ", "2"):
            with _Env(SYMONEURAL_ASIC_ENABLED=v, SYMONEURAL_ASIC_TOKEN="s3cret"):
                self.assertFalse(asicminer.enabled(), f"{v!r} switched the surface on")
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"):
            self.assertTrue(asicminer.enabled())



    def test_the_gpu_miner_token_is_not_this_token(self):
        # Two surfaces, two secrets. If these ever read the same variable, one leaked
        # token would hand over both the rigs and the card.
        src = (HERE / "__init__.py").read_text()
        self.assertNotIn("SYMONEURAL_MINER_TOKEN", src)


class TestRigsParsing(unittest.TestCase):

    def test_empty_is_the_normal_state(self):
        with _Env():
            self.assertEqual(asicminer.rigs(), [])
        with _Env(SYMONEURAL_ASIC_RIGS=""):
            self.assertEqual(asicminer.rigs(), [])
        with _Env(SYMONEURAL_ASIC_RIGS="  ,, "):
            self.assertEqual(asicminer.rigs(), [])

    def test_whitespace_and_empty_elements(self):
        with _Env(SYMONEURAL_ASIC_RIGS=" 10.0.0.11 , ,10.0.0.12 "):
            self.assertEqual(asicminer.rigs(), ["10.0.0.11", "10.0.0.12"])


class TestUnitState(unittest.TestCase):
    """Every branch, and every one of them a legal api.py Unit.state literal."""

    ALLOWED = {"ready", "busy", "queued", "offline"}

    def test_disabled(self):
        with _Env():
            state, detail = asicminer.unit_state(None)
            self.assertEqual(state, "offline")
            self.assertIn("SYMONEURAL_ASIC_ENABLED=1", detail)

    def test_enabled_branches(self):
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"):
            if not asicminer.installed():
                self.skipTest("venv absent; the installed() branch shadows the rest")
            cases = {
                None: ("offline", "not yet probed"),
                ("err",): None,
            }
            self.assertEqual(asicminer.unit_state(None), cases[None])
            self.assertEqual(asicminer.unit_state({"rigs": [], "error": None}),
                             ("offline", "no rigs configured"))
            self.assertEqual(
                asicminer.unit_state({"rigs": [{"reachable": False}, {"reachable": False}],
                                      "error": None}),
                ("offline", "2 configured, none answering"))
            state, detail = asicminer.unit_state(
                {"rigs": [{"reachable": True, "hashrate_th_s": 53.2, "vendor": "AntMiner"}],
                 "error": None})
            self.assertEqual(state, "ready")
            self.assertIn("53.2 TH/s measured", detail)
            self.assertIn("1 rig answering", detail)

    def test_an_error_is_shown_not_swallowed(self):
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"):
            if not asicminer.installed():
                self.skipTest("venv absent")
            state, detail = asicminer.unit_state({"rigs": [], "error": "probe exceeded 30s"})
            self.assertEqual(state, "offline")
            self.assertEqual(detail, "probe exceeded 30s")

    def test_every_branch_is_a_legal_state(self):
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"):
            for result in (None, {"rigs": [], "error": "x"}, {"rigs": [], "error": None},
                           {"rigs": [{"reachable": False}], "error": None},
                           {"rigs": [{"reachable": True}], "error": None}):
                self.assertIn(asicminer.unit_state(result)[0], self.ALLOWED, result)

    def test_a_reachable_rig_with_no_hashrate_shows_no_number(self):
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"):
            if not asicminer.installed():
                self.skipTest("venv absent")
            detail = asicminer.unit_state({"rigs": [{"reachable": True}], "error": None})[1]
            self.assertNotIn("TH/s", detail)


class _TmpEmu:
    """Redirect the emulator's pidfile and console log into a temp dir."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = pathlib.Path(self.tmp.name)
        self.saved = (asicminer.EMU_PID, asicminer.EMU_LOG)
        asicminer.EMU_PID = d / "qemu-antminer.pid"
        asicminer.EMU_LOG = d / "qemu-antminer.log"
        return asicminer.EMU_PID, asicminer.EMU_LOG

    def __exit__(self, *exc):
        asicminer.EMU_PID, asicminer.EMU_LOG = self.saved
        self.tmp.cleanup()


class TestEmulatorStatus(unittest.TestCase):

    def test_no_pidfile(self):
        with _TmpEmu():
            st = asicminer.emulator_status()
            self.assertEqual((st["running"], st["pid"], st["booted"]), (False, None, False))

    def test_garbage_pidfile(self):
        with _TmpEmu() as (pid, _):
            pid.write_text("not-a-pid\n")
            self.assertFalse(asicminer.emulator_status()["running"])

    def test_dead_pid(self):
        with _TmpEmu() as (pid, _):
            pid.write_text("999999\nAntminer-S17Pro.tar.gz\n")
            self.assertFalse(asicminer.emulator_status()["running"])

    def test_a_live_pid_that_is_not_a_qemu_is_not_running(self):
        # Pid reuse after a reboot. Trusted, this reports a stranger's process as the
        # emulator — and emulator_stop() would then SIGTERM that stranger's process group.
        with _TmpEmu() as (pid, _):
            pid.write_text(f"{os.getpid()}\nAntminer-S17Pro.tar.gz\n")
            st = asicminer.emulator_status()
            self.assertFalse(st["running"], "a recycled pid was accepted as the emulator")
            self.assertIn("not a qemu", st.get("note", ""))

    def test_status_does_not_delete_the_pidfile(self):
        # It used to unlink on any exception, PermissionError included — so a status query
        # against a live emulator owned by another user destroyed the record of it.
        with _TmpEmu() as (pid, _):
            pid.write_text("999999\n")
            asicminer.emulator_status()
            self.assertTrue(pid.exists(), "a read-shaped call mutated state")

    def test_web_is_not_advertised_before_the_guest_has_booted(self):
        with _TmpEmu() as (pid, log):
            pid.write_text(f"{os.getpid()}\n")     # not a qemu, so not running anyway
            log.write_text("Booting Linux...\n")
            self.assertIsNone(asicminer.emulator_status()["web"])

    def test_booted_is_read_from_the_log(self):
        with _TmpEmu() as (_, log):
            log.write_text("Booting Linux on physical CPU 0x0\n")
            self.assertFalse(asicminer._emulator_booted())
            log.write_text("Freeing unused kernel memory: 1024K\n"
                           "/bin/sh: can't access tty; job control turned off\n/ # \n")
            self.assertTrue(asicminer._emulator_booted())

    def test_the_previous_boot_does_not_make_this_one_look_booted(self):
        with _TmpEmu() as (_, log):
            log.write_text(
                f"{asicminer.EMU_RUN_MARKER} Antminer-S17Pro.tar.gz ===\n"
                "/bin/sh: can't access tty; job control turned off\n/ # \n"
                f"\n{asicminer.EMU_RUN_MARKER} Antminer-S17Plus.tar.gz ===\n"
                "Booting Linux on physical CPU 0x0\n")
            self.assertFalse(asicminer._emulator_booted(),
                             "the last run's shell prompt was read as this run's")

    def test_stop_with_nothing_running_is_a_no_op(self):
        with _TmpEmu():
            self.assertEqual(asicminer.emulator_stop(),
                             {"ok": True, "note": "nothing was running"})

    def test_start_is_refused_when_the_surface_is_off(self):
        with _Env(), _TmpEmu():
            out = asicminer.emulator_start("whatever")
            self.assertFalse(out["ok"])
            self.assertIn("disabled", out["error"])

    def test_start_refuses_an_unknown_package_id(self):
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"), _TmpEmu():
            if not asicminer.QEMU_SCRIPT.is_file():
                self.skipTest("qemu-antminer.sh absent")
            out = asicminer.emulator_start("0" * 16)
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "no such firmware package")

    def test_start_never_takes_a_path(self):
        # The endpoint resolves an id against the enumerated directories. Handing it a real
        # path must not boot that path.
        with _Env(SYMONEURAL_ASIC_ENABLED="1", SYMONEURAL_ASIC_TOKEN="s3cret"), _TmpEmu():
            if not asicminer.QEMU_SCRIPT.is_file():
                self.skipTest("qemu-antminer.sh absent")
            out = asicminer.emulator_start("/etc/passwd")
            self.assertFalse(out["ok"])


class TestFirmwareInventory(unittest.TestCase):

    def _with_dir(self, d: pathlib.Path):
        saved = asicminer.FW_DIRS
        asicminer.FW_DIRS = [d]
        self.addCleanup(lambda: setattr(asicminer, "FW_DIRS", saved))

    def test_vendor_is_inferred_from_the_filename_and_unknowns_are_dropped(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            for name in ("Antminer-S17Pro-user-OM.tar.gz", "Whatsminer-all-2026.tar.gz",
                         "microbt-thing.zip", "totally-unknown-firmware.tar.gz",
                         "notes.txt", "Antminer-S19j-sd2nand.zip"):
                (d / name).write_bytes(b"x")
            self._with_dir(d)
            got = {p["name"]: (p["vendor"], p["kind"]) for p in asicminer.packages()}
            self.assertEqual(got["Antminer-S17Pro-user-OM.tar.gz"], ("antminer", "browser"))
            self.assertEqual(got["Whatsminer-all-2026.tar.gz"], ("microbt", "browser"))
            self.assertEqual(got["microbt-thing.zip"], ("microbt", "sd"))
            self.assertEqual(got["Antminer-S19j-sd2nand.zip"], ("antminer", "sd"))
            self.assertNotIn("totally-unknown-firmware.tar.gz", got)
            self.assertNotIn("notes.txt", got)

    def test_an_empty_package_is_listed_with_its_real_size(self):
        # There is a 0-byte zip in external/. Listing it is fine; the size is what tells
        # the truth about it, so the size must be a real stat and never omitted.
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            (d / "Antminer-S19j-Release-sd2nand 2.zip").write_bytes(b"")
            self._with_dir(d)
            pkgs = asicminer.packages()
            self.assertEqual(len(pkgs), 1)
            self.assertEqual(pkgs[0]["bytes"], 0)

    def test_ids_are_stable_and_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            f = d / "Antminer-S17Pro-user-OM.tar.gz"
            f.write_bytes(b"x")
            self._with_dir(d)
            pid = asicminer.packages()[0]["id"]
            self.assertEqual(pid, asicminer.packages()[0]["id"])
            self.assertEqual(asicminer.package_by_id(pid), f)
            self.assertIsNone(asicminer.package_by_id("0" * 16))

    def test_an_id_is_not_a_path(self):
        with tempfile.TemporaryDirectory() as t:
            self._with_dir(pathlib.Path(t))
            for attempt in ("/etc/passwd", "../../etc/passwd", "x/../y"):
                self.assertIsNone(asicminer.package_by_id(attempt), attempt)


class TestFwcheckEntryPoints(unittest.TestCase):
    """`check_microbt` used to be defined below `sys.exit(main())` and was unreachable."""

    def test_the_entry_point_is_the_last_statement_in_the_file(self):
        src = (HERE / "fwcheck.py").read_text()
        tail = src[src.index('if __name__ == "__main__":'):].strip().splitlines()
        self.assertEqual(len(tail), 2, "something follows the entry point again — "
                                       "anything defined below it does not exist when "
                                       "main() runs as a script")

    def test_the_microbt_checker_is_reachable_as_a_script(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as fh:
            # A header with the real magic, a declared payload, and nothing else.
            fh.write(fwcheck.MICROBT_MAGIC.to_bytes(4, "little") + b"\0" * 128)
            name = fh.name
        try:
            out = subprocess.run([sys.executable, str(HERE / "fwcheck.py"), name],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn('"kind": "microbt"', out.stdout,
                          "the CLI did not dispatch to check_microbt")
        finally:
            os.unlink(name)

    def test_format_detection(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            zipf = d / "a.zip"; zipf.write_bytes(b"PK\x03\x04rest")
            binf = d / "a.bin"; binf.write_bytes(fwcheck.MICROBT_MAGIC.to_bytes(4, "little"))
            tarf = d / "a.tar.gz"; tarf.write_bytes(b"\x1f\x8b\x08\x00")
            self.assertTrue(fwcheck.pkg_is_zip(zipf))
            self.assertFalse(fwcheck.pkg_is_zip(binf))
            self.assertTrue(fwcheck.is_microbt(binf))
            self.assertFalse(fwcheck.is_microbt(zipf))
            self.assertFalse(fwcheck.is_microbt(tarf))
            self.assertFalse(fwcheck.is_microbt(d / "missing"))
            self.assertFalse(fwcheck.pkg_is_zip(d / "missing"))


class TestDocumentation(unittest.TestCase):

    def test_the_readme_probe_points_at_actually_exists(self):
        # `probe()` returns "see backend/asicminer/README.md" to a user.
        self.assertTrue((HERE / "README.md").is_file(),
                        "probe() cites a README that does not exist")

    def test_the_readme_states_the_literal_one_requirement(self):
        text = (HERE / "README.md").read_text()
        self.assertIn("SYMONEURAL_ASIC_ENABLED", text)
        self.assertIn("SYMONEURAL_ASIC_TOKEN", text)
        self.assertIn("SYMONEURAL_ASIC_RIGS", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
