# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""A published rate limit must be the enforced one. There were three answers before.

Measured 2026-09-08 on the running box:

    appdocs.py prose        chat 120/min, 3,000/hour     what visitors were told
    api.py _RATE_SUGGESTED  chat 120,     2000           what the code suggested
    pid 1507                no bucket at all             what was enforced

Three of the four published hourly figures disagreed with the table beside them, and none
of the four was applied -- `_rate_for` returned `(0, 0)` and `check_rate` reads a missing
limiter as "allow". A burst of 150 posts to `ravencalc` in 1.64 s drew no 429.

The published figure is the load-bearing one: somebody outside this box plans against it.
So these tests assert the three agree, and that the default is a real bucket rather than
none.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import re
import sys
import unittest

def _find_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up for the marker; never count parents. See symoneural-audit/README.md.

    Written this way after `bin/symoneural-audit` reported this very file. Two new test
    files opened with `parents[2]` and pushed the ratchet from 81 to 83 -- in the same
    session that built the ratchet and wrote the README recommending this function. Habit
    is stronger than intent, which is the argument for the check existing at all.
    """
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "backend"))

from runtime.lib import ratelimits                                          # noqa: E402
from registry.lib import appdocs                                             # noqa: E402


class PublishedEqualsEnforced(unittest.TestCase):

    def test_every_published_figure_comes_from_the_enforced_table(self):
        """No hand-typed numbers left in the prose.

        A literal survives a change to BUDGETS; a call to `prose()` cannot. This is the
        check that would have caught 3,000-versus-2000 on the day it was typed.
        """
        src = pathlib.Path(appdocs.__file__).read_text()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        stragglers = re.findall(r'limits="[^"]*\d[,\d]*\s*requests/min[^"]*"', code)
        self.assertEqual([], stragglers,
                         "these publish a hand-typed rate figure instead of calling "
                         "ratelimits.prose(); it will drift from the enforced table")

    def test_the_prose_reads_back_the_numbers_it_was_built_from(self):
        for surface, (per_min, per_hour) in ratelimits.BUDGETS.items():
            with self.subTest(surface=surface):
                text = ratelimits.prose(surface)
                self.assertIn(f"{per_min:,}", text)
                self.assertIn(f"{per_hour:,}", text)

    def test_an_unset_surface_gets_a_real_bucket_not_no_bucket(self):
        """The defect itself: the default was (0, 0), which check_rate lets through.

        Reimported with the environment cleared, because module scope reads it once.
        """
        saved = {k: v for k, v in os.environ.items() if k.startswith("SYMONEURAL_RATE_")}
        for k in saved:
            del os.environ[k]
        try:
            api = importlib.import_module("api")
            api = importlib.reload(api)
            for surface in ("chat", "remix", "image", "ravencalc"):
                with self.subTest(surface=surface):
                    self.assertEqual(api._rate_for(surface), ratelimits.BUDGETS[surface],
                                     "an unset surface must fall back to the published "
                                     "budget, not to no limit")
        finally:
            os.environ.update(saved)

    def test_an_env_override_still_wins(self):
        """The operator's knob has to keep working, or this fix takes it away."""
        api = importlib.import_module("api")
        os.environ["SYMONEURAL_RATE_CHAT"] = "7/11"
        try:
            self.assertEqual(api._rate_for("chat"), (7, 11))
        finally:
            del os.environ["SYMONEURAL_RATE_CHAT"]


if __name__ == "__main__":
    unittest.main()
