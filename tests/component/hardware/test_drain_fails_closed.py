"""If the Python side cannot run, the governor must NOT report a drained card.

Commit B moved the drain arithmetic out of `scripts/gpu-governor.sh` into
`backend/gpu.py`. That introduces the runtime dependency bash was valuable for not
having, and it is acceptable only because the failure direction is right:

    a missing interpreter, a missing module, a timeout, a non-numeric line
        -> `vram_compute_used` returns 1
        -> `drain()` uses the CARD-WIDE reading against DRAIN_FLOOR_CARDWIDE_MIB (1500)
           instead of the compute floor (1024)
        -> cruder measure, STRICTER threshold: it waits longer, never hands over sooner

Failing the other way is the whole hazard: an unreadable card reading as an empty one and
being handed to the next tenant on no evidence. That loads weights onto a card that still
holds weights, which is the failure this component exists to prevent.

These run the REAL governor in an isolated root, so the production lock is never touched.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
GOV = ROOT / "scripts" / "gpu-governor.sh"
GPU_PY = ROOT / "backend" / "gpu.py"
CARDWIDE_FLOOR = 1500


def card_wide_mib() -> int:
    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True)
    try:
        return int(r.stdout.strip().splitlines()[0])
    except Exception:                                          # noqa: BLE001
        return -1


def isolated(tag: str, with_gpu_py: bool) -> pathlib.Path:
    r = pathlib.Path("/tmp/claude-1000/-home-google-Symoneural/"
                     "1889a362-4f5f-4042-89f7-6d42e0633e2b/scratchpad") / f"drain-{tag}"
    shutil.rmtree(r, ignore_errors=True)
    (r / "backend" / "apps").mkdir(parents=True)
    (r / "scripts").mkdir()
    (r / "run").mkdir()
    (r / "backend" / "server.py").write_text("")          # the governor's root guard
    shutil.copy2(GOV, r / "scripts" / "gpu-governor.sh")
    if with_gpu_py:
        shutil.copy2(GPU_PY, r / "backend" / "gpu.py")
    return r


def drain(root: pathlib.Path, pattern: str, timeout_s: str = "1") -> tuple[int, str]:
    env = dict(os.environ, SYMONEURAL_DRAIN_TIMEOUT_S=timeout_s,
               SYMONEURAL_GOVERNOR_LOG=str(root / "run" / "governor.log"))
    p = subprocess.run([str(root / "scripts" / "gpu-governor.sh"), "drain", pattern],
                       capture_output=True, text=True, env=env, timeout=180)
    return p.returncode, (p.stdout + p.stderr)


class DrainFailsClosedWithoutPython(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.card = card_wide_mib()
        if cls.card < CARDWIDE_FLOOR:
            raise unittest.SkipTest(
                f"the card holds {cls.card} MiB, below the {CARDWIDE_FLOOR} MiB card-wide "
                "floor -- with an idle card the degraded path legitimately reports drained, "
                "so this assertion would be vacuous. Load a surface and re-run.")

    def test_with_gpu_py_a_non_matching_pattern_drains(self):
        """The precise path: nothing matches the pattern, so compute is 0 and it settles.

        This is the control. Without it, the test below could pass because drain never
        succeeds for any reason at all.
        """
        root = isolated("have", with_gpu_py=True)
        rc, out = drain(root, "/no/such/process/path/")
        self.assertEqual(rc, 0, f"drain refused even with a clear compute reading:\n{out}")
        self.assertIn("settled at 0 MiB", out)
        self.assertNotIn("FALLBACK", out, "it fell back despite gpu.py being present")

    def test_without_gpu_py_it_refuses(self):
        """THE assertion. gpu.py absent, card holding memory -> must not report drained."""
        root = isolated("missing", with_gpu_py=False)
        rc, out = drain(root, "/no/such/process/path/")
        self.assertIn("FALLBACK", out,
                      "the degraded path did not announce itself -- a silent fallback is a "
                      "fallback nobody knows they are running on")
        self.assertNotEqual(
            rc, 0,
            f"THE GOVERNOR REPORTED A DRAINED CARD WITH NO COMPUTE READING while the card "
            f"held {self.card} MiB. That hands the GPU to the next tenant on no evidence.\n"
            f"{out}")
        self.assertIn("refusing to hand over", out)

    def test_a_broken_gpu_py_is_treated_as_missing(self):
        """Not just absent: present and exiting non-zero must fail the same way."""
        root = isolated("broken", with_gpu_py=True)
        (root / "backend" / "gpu.py").write_text(
            "import sys\nsys.exit(3)\n")
        rc, out = drain(root, "/no/such/process/path/")
        self.assertIn("FALLBACK", out)
        self.assertNotEqual(rc, 0, f"a gpu.py that exits 3 was treated as a reading:\n{out}")

    def test_a_gpu_py_printing_garbage_is_treated_as_missing(self):
        """The case the `case $out in *[!0-9]*` guard exists for: stdout that is not a
        number must never become one."""
        root = isolated("garbage", with_gpu_py=True)
        (root / "backend" / "gpu.py").write_text(
            "print('drained, probably')\n")
        rc, out = drain(root, "/no/such/process/path/")
        self.assertIn("FALLBACK", out)
        self.assertNotEqual(rc, 0, f"non-numeric stdout was accepted as a reading:\n{out}")


if __name__ == "__main__":
    unittest.main()
