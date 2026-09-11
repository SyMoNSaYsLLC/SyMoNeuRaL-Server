#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""`/api/status` must not claim GPU health it does not have.

On 2026-09-09 a `dist-upgrade` replaced the NVIDIA driver while the box kept running. The
kernel module and the userspace library disagreed, every GPU path failed, and **nothing on
the box said so** -- `/api/status` reported `chat: ready` and `image: ready` because those
states were computed from files on disk. An operator reading that sees "the app is broken"
and would never try the one thing that fixes it, which is a reboot.

These tests fake the mismatch rather than causing one. Breaking the driver on this box to
test the driver check would be both destructive and unnecessary: the check reads the exit
status and stderr of one `nvidia-smi` call, and both are trivially substitutable.

The properties being locked in:

  * a mismatch is reported as **its own state**, not as a generic surface failure, and its
    detail line names the required action;
  * the **CPU surfaces keep serving** -- a GPU driver fault is not a ravencalc outage, which
    is exactly why this lives in the status computation and not in an `ExecStartPre`;
  * "no GPU on this host" and "nvidia-smi failed for some other reason" are distinguished
    from a mismatch, because only a mismatch is fixed by rebooting;
  * `nvidia-persistenced` being down is reported but does **not** take the surfaces offline.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest
from unittest import mock


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise RuntimeError("repo root not found: no backend/api.py marker above this file")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

import api  # noqa: E402


class _Completed:
    """Just enough of CompletedProcess for `_read_smi` to read."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


HEALTHY_SMI = "1234, 16303, 22.5, 44"

# `_PERSISTENCED_PID.exists()` is exercised for real rather than mocked: a Path instance's
# `exists` attribute is read-only, and swapping the constant for a path that genuinely does
# or does not exist tests the actual call instead of a stand-in for it.
PID_PRESENT = ROOT / "backend" / "api.py"                 # exists, by definition
PID_ABSENT = ROOT / "run" / "no-such-persistenced.pid"    # does not

MISMATCH_STDERR = (
    "Failed to initialize NVML: Driver/library version mismatch\n"
    "NVML library version: 615.71\n"
)


class GpuDriverHealth(unittest.TestCase):

    def setUp(self) -> None:
        # Both caches must be cleared or a case reads the previous case's answer.
        api._telemetry_at = 0.0
        api._smi_fault = ("ok", "")
        self.addCleanup(self._reset)

    def _reset(self) -> None:
        api._telemetry_at = 0.0
        api._smi_fault = ("ok", "")

    # -- the classifier ---------------------------------------------------------------
    def test_mismatch_is_its_own_state_and_names_the_action(self):
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(9, "", MISMATCH_STDERR)):
            state, detail = api.gpu_driver_health()
        self.assertEqual("mismatch", state)
        self.assertIn("REBOOT REQUIRED", detail,
                      "the detail must name the action; a reboot is the only fix and an "
                      "operator would not guess it from a 500")
        self.assertIn("restarting this service will not fix it", detail.lower())

    def test_absent_driver_is_not_reported_as_a_mismatch(self):
        """No GPU at all is a different problem with a different answer: not a reboot."""
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError()):
            state, detail = api.gpu_driver_health()
        self.assertEqual("absent", state)
        self.assertNotIn("REBOOT", detail.upper())

    def test_an_unexplained_failure_is_not_dressed_up_as_a_mismatch(self):
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(2, "", "some other nvidia-smi gripe")):
            state, detail = api.gpu_driver_health()
        self.assertEqual("unreadable", state)
        self.assertIn("exited 2", detail)
        self.assertIn("some other nvidia-smi gripe", detail)

    def test_healthy_driver_with_persistenced_up_is_ok(self):
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")), \
             mock.patch.object(api, "_PERSISTENCED_PID", PID_PRESENT):
            state, detail = api.gpu_driver_health()
        self.assertEqual("ok", state)
        self.assertEqual("", detail)

    def test_persistenced_down_is_reported_but_is_not_a_mismatch(self):
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")), \
             mock.patch.object(api, "_PERSISTENCED_PID", PID_ABSENT):
            state, detail = api.gpu_driver_health()
        self.assertEqual("persistenced_down", state)
        self.assertIn("nvidia-persistenced", detail)

    # -- what the rack actually reports -----------------------------------------------
    def test_a_mismatch_takes_the_gpu_rows_offline_and_leaves_the_cpu_rows_serving(self):
        """The whole point: a GPU driver fault is not a ravencalc outage."""
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(9, "", MISMATCH_STDERR)):
            status = api.build_status()

        states = {u.id: u.state for u in status.units}
        self.assertEqual("offline", states["chat"], states)
        self.assertEqual("offline", states["image"], states)
        self.assertEqual("ready", states["ravencalc"],
                         "ravencalc is CPU-only and must keep serving through a driver "
                         "fault -- this is why the check is not an ExecStartPre")

        self.assertEqual("mismatch", status.gpu.driver)
        self.assertIn("REBOOT REQUIRED", status.gpu.driver_detail or "")

    def test_the_healthy_rack_reports_no_driver_fault(self):
        """Guards against the check firing on a working box, which would be worse."""
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")), \
             mock.patch.object(api, "_PERSISTENCED_PID", PID_PRESENT):
            status = api.build_status()
        self.assertEqual("ok", status.gpu.driver)
        self.assertIsNone(status.gpu.driver_detail)
        states = {u.id: u.state for u in status.units}
        self.assertIn(states["chat"], ("ready", "busy", "queued"), states)

    def test_persistenced_down_does_not_take_the_surfaces_offline(self):
        """It costs cold-start latency, not availability. Reporting it as an outage would
        be the same overstatement in the other direction."""
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")), \
             mock.patch.object(api, "_PERSISTENCED_PID", PID_ABSENT):
            status = api.build_status()
        self.assertEqual("persistenced_down", status.gpu.driver)
        states = {u.id: u.state for u in status.units}
        self.assertIn(states["chat"], ("ready", "busy", "queued"), states)

    # -- the cost of the check --------------------------------------------------------
    def test_it_adds_no_extra_nvidia_smi_exec(self):
        """`/api/status` is polled and drives the websocket, so an added exec per request
        would be a real regression. The driver state rides on the telemetry call."""
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")) as run:
            api.build_status()
            calls_after_status = run.call_count
            api.gpu_driver_health()
            self.assertEqual(calls_after_status, run.call_count,
                             "gpu_driver_health() spawned a process instead of reading "
                             "the telemetry cache")

    def test_the_cache_expires_so_a_fault_is_noticed(self):
        """A cached 'ok' that never refreshes would hide the very fault this detects."""
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(0, HEALTHY_SMI, "")), \
             mock.patch.object(api, "_PERSISTENCED_PID", PID_PRESENT):
            self.assertEqual("ok", api.gpu_driver_health()[0])
        # Within the TTL the old answer stands...
        with mock.patch.object(subprocess, "run",
                               return_value=_Completed(9, "", MISMATCH_STDERR)):
            self.assertEqual("ok", api.gpu_driver_health()[0],
                             "expected the 1s cache to still be warm")
            api._telemetry_at = 0.0          # ...and once it expires, the fault surfaces
            self.assertEqual("mismatch", api.gpu_driver_health()[0])
        self.assertLessEqual(api._TELEMETRY_TTL, 5.0,
                             "the staleness window is documented as ~1s; a longer one "
                             "would need the docstring updated with it")


if __name__ == "__main__":
    unittest.main()
