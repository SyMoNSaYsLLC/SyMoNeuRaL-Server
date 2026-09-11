#!/usr/bin/env python3
"""Structural and dry-run checks for the sequential browser-suite runner."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tests" / "run_ui_verification.mjs"


class UiVerificationRunnerTests(unittest.TestCase):
    def test_required_suites_are_ordered_and_awaited(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("const REQUIRED = ['applications', 'responsive', 'frontend', 'chat']", source)
        self.assertIn("const result = await runSuite(name, definitions[name])", source)
        self.assertNotIn("Promise.all(", source)

    def test_success_marker_is_only_the_canonical_pass_branch(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn("canonicalPassed ? 'ALL REQUIRED UI SUITES PASSED'", source)
        self.assertIn("'FAILED OR INCOMPLETE'", source)

    def test_package_script_points_at_the_runner(self):
        package = json.loads((ROOT / "tests" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["scripts"]["verify:ui"], "node run_ui_verification.mjs")

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_dry_run_needs_no_browser_or_api_and_shows_exact_order(self):
        record = ROOT / "docs" / "ops" / "SMOKE-APPLICATIONS.md"
        before = record.read_bytes() if record.exists() else None
        check = subprocess.run(["node", "--check", str(RUNNER)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        run = subprocess.run(["node", str(RUNNER), "--dry-run"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        positions = [run.stdout.index(f"{name}:") for name in
                     ("applications", "responsive", "frontend", "chat")]
        self.assertEqual(positions, sorted(positions))
        after = record.read_bytes() if record.exists() else None
        self.assertEqual(after, before, "--dry-run changed the canonical smoke record")


if __name__ == "__main__":
    unittest.main(verbosity=2)
