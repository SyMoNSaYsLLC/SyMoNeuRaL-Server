#!/usr/bin/env python3
"""Tests for the legacy env-var promotion.

The failure this guards against is not an exception, it is a box that comes up looking
healthy with surfaces missing. `/etc/symoneural/api.env` on a running box still carries the
`SYM_*` spelling, and every gate in `backend/apps/` now asks for `SYMONEURAL_*`; if promotion
regresses, `enabled()` returns False everywhere at once, the rack renders fewer rows, and
nothing in any log says why. So the assertions here are about the exact semantics an upgrade
depends on -- promoted, not overwritten, idempotent -- rather than about the happy path.

Stdlib only, on purpose: backend/apps/ tests are collected by the main pytest run.
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys
import unittest

from apps import symoneuralenv as env  # noqa: E402


class PromoteTests(unittest.TestCase):
    def test_a_legacy_name_is_copied_to_the_new_prefix(self):
        d = {"SYM_STUDIO_TOKEN": "s3cret"}
        self.assertEqual(env.promote(d, warn=False),
                         [("SYM_STUDIO_TOKEN", "SYMONEURAL_STUDIO_TOKEN")])
        self.assertEqual(d["SYMONEURAL_STUDIO_TOKEN"], "s3cret")

    def test_the_legacy_name_survives_the_promotion(self):
        """Deliberate, and not laziness. `subprocess` children inherit this environment, and
        this repo spawns several -- llama-server, stable-diffusion.cpp, the asicminer venv,
        `scripts/gpu-governor.sh`. Deleting the old name would take it away from a child that
        has not been renamed yet, which is a harder failure to find than a duplicate."""
        d = {"SYM_CODER_ENABLED": "1"}
        env.promote(d, warn=False)
        self.assertEqual(d["SYM_CODER_ENABLED"], "1")

    def test_an_existing_new_name_is_never_overwritten(self):
        """The operator mid-migration: both spellings set, different values. The new spelling
        is what the code asks for, so it has to win -- otherwise editing the env file to the
        new name would have no effect until the old line was also deleted, which is the
        opposite of a migration path."""
        d = {"SYM_STUDIO_TOKEN": "old", "SYMONEURAL_STUDIO_TOKEN": "new"}
        self.assertEqual(env.promote(d, warn=False), [])
        self.assertEqual(d["SYMONEURAL_STUDIO_TOKEN"], "new")

    def test_a_conflict_is_logged_at_warning(self):
        d = {"SYM_STUDIO_TOKEN": "old", "SYMONEURAL_STUDIO_TOKEN": "new"}
        with self.assertLogs("symoneural.env", level=logging.WARNING) as cm:
            env.promote(d)
        self.assertTrue(any("both set" in line for line in cm.output), cm.output)

    def test_a_promotion_is_logged_at_warning_and_names_the_variable(self):
        """A silent promotion means the env file is never fixed. The deprecation notice IS
        the migration, so its absence is a regression even though everything still works."""
        with self.assertLogs("symoneural.env", level=logging.WARNING) as cm:
            env.promote({"SYM_MINER_TOKEN": "t"})
        joined = " ".join(cm.output)
        self.assertIn("SYM_MINER_TOKEN", joined)
        self.assertIn("api.env", joined)

    def test_promotion_is_idempotent(self):
        d = {"SYM_GATEWAY_NETWORK": "testnet"}
        env.promote(d, warn=False)
        self.assertEqual(env.promote(d, warn=False), [])
        self.assertEqual(d, {"SYM_GATEWAY_NETWORK": "testnet",
                             "SYMONEURAL_GATEWAY_NETWORK": "testnet"})

    def test_nothing_outside_the_legacy_prefix_is_touched(self):
        """`SYMBOL_PATH` and `SYMFONY_ENV` are not ours. The prefix includes the underscore
        for exactly this reason, and a variable already carrying the new prefix must not be
        promoted a second time into `SYMONEURAL_ONEURAL_...`."""
        d = {"PATH": "/usr/bin", "SYMBOLS": "x", "SYMFONY_ENV": "prod",
             "SYMONEURAL_NEWS_ENABLED": "1"}
        before = dict(d)
        self.assertEqual(env.promote(d, warn=False), [])
        self.assertEqual(d, before)

    def test_an_already_migrated_environment_promotes_nothing(self):
        """The end state. When this returns [] on every box, the module can be deleted."""
        self.assertEqual(
            env.promote({"SYMONEURAL_CODER_ENABLED": "1",
                         "SYMONEURAL_CODER_TOKEN": "t"}, warn=False), [])

    def test_the_name_helpers_round_trip(self):
        for legacy in ("SYM_STUDIO_TOKEN", "SYM_ASIC_ENABLED", "SYM_X"):
            self.assertEqual(env.legacy_name(env.new_name(legacy)), legacy)

    def test_the_default_target_is_the_process_environment(self):
        """`promote()` with no argument is how `api.py` calls it. Asserted because passing a
        dict is how every test above works, and a default that had drifted to a throwaway
        copy would leave all of them green and the serving path unmigrated."""
        name = "SYM_TEST_PROMOTE_DEFAULT_TARGET"
        want = env.new_name(name)
        # The whole environment is snapshotted and restored, not just the two names above.
        # This is the one test that mutates the interpreter's own environment, and the other
        # suites in `backend/apps/` gate on these variables: promoting a `SYM_CODER_TOKEN`
        # that some other test happened to leave set would hand a later test a token it
        # never set, and that test would pass for the wrong reason. A suite whose result
        # depends on file collection order is not a suite.
        saved = dict(os.environ)
        try:
            os.environ[name] = "yes"
            env.promote(warn=False)
            self.assertEqual(os.environ.get(want), "yes")
            self.assertIn((name, want), env.promoted())
        finally:
            os.environ.clear()
            os.environ.update(saved)


if __name__ == "__main__":
    unittest.main()
