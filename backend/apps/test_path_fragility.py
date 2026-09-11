# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""A ratchet on move-fragile path resolution. It may go down; it must not go up.

`symoneural-audit` counts files that compute a repo root by counting parents rather than by
searching for a marker. On 2026-09-08 that class broke the interactive client the moment it
was moved one directory deeper, and the same run found 81 more files that would break the
same way without saying so.

Eighty-one is too many to fix in the session that found them and too many to leave
uncounted. So this pins the number. New code cannot add to it, and each repair lowers it --
at which point this test fails and tells you to lower the baseline, which is the only kind
of failure worth having here.

Deliberately a ratchet and not a hard zero. A test that has been failing since the day it
was written gets skipped, and then the guard is gone.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import unittest

def _find_root(start: pathlib.Path) -> pathlib.Path:
    """The pattern this test exists to enforce, used by this test.

    The first version of this file opened with `ROOT = pathlib.Path(__file__).parents[2]`
    -- the exact construct it was written to count. The ratchet caught its own author on the
    next full run: 82 silent findings against a baseline of 81, and the eighty-second was
    this file. Left recorded rather than quietly corrected, because a guard that exempts
    itself is the first step to a guard that exempts everything.
    """
    for cand in (start, *start.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
AUDIT = ROOT / "symoneural-audit" / "bin" / "symoneural-audit"

#: Measured 2026-09-08 at b0acd286+. Lower this when files are repaired. Never raise it:
#: raising it is how a ratchet becomes a rubber stamp.
SILENT_DEPTH_ROOT_BASELINE = 81


class PathFragilityDoesNotGrow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not AUDIT.is_file():
            raise unittest.SkipTest(f"symoneural-audit not present at {AUDIT}")
        out = subprocess.run(["python3", str(AUDIT), "--json"],
                             capture_output=True, text=True, timeout=600)
        cls.findings = json.loads(out.stdout)["findings"]

    def _silent(self, cls_name: str) -> list:
        return [f for f in self.findings
                if f["class"] == cls_name and f["confidence"] == "silent"]

    def test_the_auditor_can_see_anything_at_all(self):
        """A scanner that finds nothing passes forever for the wrong reason.

        If `git ls-files` fails, or the suffix filter stops matching, every assertion below
        becomes vacuously true. So prove the walk works before trusting an absence.
        """
        self.assertTrue(self.findings,
                        "the auditor returned zero findings of any class, which on this "
                        "repo means the walk is broken rather than the code being clean")

    def test_silent_depth_root_does_not_grow(self):
        n = len(self._silent("depth-root"))
        self.assertLessEqual(
            n, SILENT_DEPTH_ROOT_BASELINE,
            f"{n} files now compute a repo root by counting parents with no marker "
            f"assertion, up from {SILENT_DEPTH_ROOT_BASELINE}. Resolve the root by "
            f"searching upward for backend/api.py instead -- see symoneural-audit/README.md")
        if n < SILENT_DEPTH_ROOT_BASELINE:
            self.fail(f"good news, and the baseline is now stale: {n} silent findings, "
                      f"baseline says {SILENT_DEPTH_ROOT_BASELINE}. Lower it to {n}.")


if __name__ == "__main__":
    unittest.main()
