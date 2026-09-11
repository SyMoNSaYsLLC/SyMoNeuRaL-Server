"""Acquiring the surface that is already resident must still evict, when a NEW engine is coming.

## The bug this was written for, measured 2026-09-11

`cmd_acquire` decided whether to evict by comparing surface NAMES:

    if [ -n "$prev" ] && [ "$prev" != "$surface" ]; then evict "$prev"; fi

A benchmark took the card with `acquire chat` while the production Qwen chat engine was
resident, also as `chat`. The names matched, so the governor evicted nothing, and the
candidate engine then died on arrival:

    ggml_backend_cuda_buffer_type_alloc_buffer: allocating 12036.68 MiB on device 0:
    cudaMalloc failed: out of memory

Both processes were legitimately "chat". They were not the same process, and they could not
co-fit: 12.8 GiB of gpt-oss weights against 8.3 GiB of resident Qwen on a 16.3 GiB card.

## Why this is the same defect `c1cb1007` already fixed one function away

That commit replaced pattern-matching eviction with eviction by recorded pid, under the
heading **"a pattern is not an identity"**. The correction was never carried into `acquire`,
where the same confusion survives one level up: **a surface NAME is not an identity either.**
`run/engine` records `<surface> <pid> <pgid>` precisely because the surface alone does not say
which process is meant.

## Why the fix is an explicit flag and not a cleverer inference

The governor cannot infer the answer, because both readings of "acquire the resident surface"
are real and they want opposite behaviour:

* **reuse** -- `api.py` acquires `chat` for a second chat request against the engine that is
  already running. Evicting here would kill the engine it is about to use, on every request.
* **replace** -- a candidate swap brings different weights under the same surface name. Not
  evicting here is an OOM.

Only the caller knows which. So `--new-engine` is how it says so, and the default is
unchanged -- an existing caller cannot acquire a new behaviour by accident.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"

STUB_OK = "#!/bin/sh\nexit 0\n"
# Reports an empty card, so `drain` returns at once and the test measures eviction only.
FAKE_SMI = "#!/bin/sh\necho 0\n"


class SameSurfaceSkeleton(unittest.TestCase):
    """A throwaway root with the real script, plus a live process standing in for an engine."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "backend").mkdir()
        (self.root / "backend" / "api.py").write_text("# skeleton\n")
        (self.root / "run").mkdir()
        (self.root / "scripts").mkdir()
        (self.root / "bin").mkdir()
        self.governor = self.root / "scripts" / "gpu-governor.sh"
        shutil.copy2(GOVERNOR, self.governor)              # the shipped file, not a rewrite

        # `_stop-chat` must NOT work here. If the fallback pattern path could stop the
        # engine, this test would pass without the identity path ever running.
        for stub in (self.root / "bin" / "symoneural-cli",
                     self.root / "scripts" / "symoneural-ui.sh"):
            stub.write_text(STUB_OK)
            stub.chmod(0o755)

        self.bindir = self.root / "fakebin"
        self.bindir.mkdir()
        smi = self.bindir / "nvidia-smi"
        smi.write_text(FAKE_SMI)
        smi.chmod(0o755)
        self.logfile = self.root / "governor.log"
        self._engines: list[subprocess.Popen] = []

    def tearDown(self):
        for p in self._engines:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
        self._tmp.cleanup()

    def fake_engine(self, surface: str) -> subprocess.Popen:
        """A real, live, killable process recorded as `surface`'s engine.

        `sleep` rather than a mock: `evict_by_pid` sends real signals and reads
        `/proc/<pid>/stat`, so anything that is not a process would test nothing. It leads
        its own process group, matching how `api.py` spawns the engine.
        """
        proc = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self._engines.append(proc)
        pgid = os.getpgid(proc.pid)
        (self.root / "run" / "engine").write_text(f"{surface} {proc.pid} {pgid}\n")
        return proc

    def run_governor(self, *argv, resident=None):
        if resident is not None:
            (self.root / "run" / "resident").write_text(resident)
            boot = pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            (self.root / "run" / "resident.boot").write_text(boot + "\n")
        env = dict(os.environ)
        env["PATH"] = str(self.bindir) + os.pathsep + env.get("PATH", "")
        env["SYMONEURAL_GOVERNOR_LOG"] = str(self.logfile)
        env["SYMONEURAL_DRAIN_TIMEOUT_S"] = "2"
        p = subprocess.run([str(self.governor), *argv], env=env,
                           capture_output=True, text=True, timeout=180)
        return p.returncode, p.stdout, p.stderr

    def assert_dead(self, proc: subprocess.Popen, msg: str, timeout: int = 20):
        for _ in range(timeout):
            if proc.poll() is not None:
                return
            time.sleep(1)
        self.fail(msg)


class ReplacingTheEngineUnderTheSameSurface(SameSurfaceSkeleton):
    """THE RED TEST. Same surface, different process, `--new-engine` declared."""

    def test_acquiring_the_resident_surface_with_new_engine_evicts_it(self):
        engine = self.fake_engine("chat")
        rc, out, err = self.run_governor("acquire", "chat", "30", "--new-engine",
                                         resident="chat")
        self.assertEqual(0, rc, f"acquire failed:\n{out}\n{err}")
        self.assert_dead(
            engine,
            "the recorded chat engine is STILL ALIVE after `acquire chat --new-engine`.\n"
            "The incoming caller declared it is bringing its own engine, so the resident one "
            "had to go. This is the OOM measured on 2026-09-11:\n"
            f"{err}")

    def test_it_says_what_it_did_and_why(self):
        """The log is how this gets diagnosed at 3am. Silence is the thing being fixed."""
        self.fake_engine("chat")
        _, _, err = self.run_governor("acquire", "chat", "30", "--new-engine",
                                      resident="chat")
        self.assertIn("chat", err)
        self.assertRegex(
            err, r"(?i)new engine|replac|same surface",
            f"the log does not say a same-surface replacement happened:\n{err}")


class TheDefaultIsUnchanged(SameSurfaceSkeleton):
    """The reuse case. Without the flag, acquiring the resident surface must NOT evict.

    This is the half that makes the fix safe. `api.py` acquires `chat` on every chat
    request against an engine that is already running; if that started evicting, the
    surface would kill its own engine once per request.
    """

    def test_acquiring_the_resident_surface_without_the_flag_leaves_it_alone(self):
        engine = self.fake_engine("chat")
        rc, out, err = self.run_governor("acquire", "chat", "30", resident="chat")
        self.assertEqual(0, rc, f"acquire failed:\n{out}\n{err}")
        time.sleep(3)
        self.assertIsNone(
            engine.poll(),
            "acquiring the ALREADY-RESIDENT surface killed its engine. That is the reuse "
            f"path -- api.py does this on every chat request:\n{err}")


class ADifferentSurfaceStillEvicts(SameSurfaceSkeleton):
    """Regression guard: the behaviour that already worked must keep working."""

    def test_a_foreign_surface_still_evicts_the_resident_engine(self):
        engine = self.fake_engine("chat")
        rc, out, err = self.run_governor("acquire", "image", "30", resident="chat")
        self.assertEqual(0, rc, f"acquire failed:\n{out}\n{err}")
        self.assert_dead(engine, f"a foreign surface no longer evicts:\n{err}")


if __name__ == "__main__":
    unittest.main()
