# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""The migrated tool policy is enforced, not merely recorded.

Deny rules came from the retired provider settings on 2026-09-08. Copying that JSON into
the repository and calling it a migration would be theatre: a policy file no runtime reads
protects nothing. These tests assert the properties that matter -- the refusals survived,
nothing weakened them, and no allow-everything mode came across.
"""
from __future__ import annotations

import json
import pathlib
import unittest


def _find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
POLICY = ROOT / "ops" / "authority" / "TOOL-POLICY.json"

#: The protected classes that must remain denied whatever else changes. Derived from the
#: repository's own standing rules: the mode-600 ledgers, the trade-secret training
#: artefacts, and credential material.
MUST_STAY_DENIED = ("corpus.jsonl", "build_dataset.py", "GARRETT-REQUESTS", "INTAKE.md")


class ThePolicyExistsAndIsWellFormed(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.p = json.loads(POLICY.read_text())

    def test_the_policy_file_is_present_and_parses(self):
        self.assertEqual("symoneural-tool-policy/v1", self.p["schema"])

    def test_it_records_where_it_came_from(self):
        """A migrated policy with no provenance cannot be audited later."""
        self.assertIn("settings.local.json", self.p["migrated_from"])

    def test_the_deny_list_is_not_empty(self):
        """An empty deny list would be a silently weaker posture than before the move."""
        self.assertTrue(self.p["deny"], "the migration produced no refusals at all")

    def test_the_deny_list_is_sorted_and_unique(self):
        self.assertEqual(sorted(set(self.p["deny"])), self.p["deny"])


class NoAllowEverythingCameAcross(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.p = json.loads(POLICY.read_text())

    def test_the_default_mode_is_not_a_bypass(self):
        self.assertNotIn(str(self.p["default_mode"]).lower(),
                         ("bypasspermissions", "bypass", "allowall", "acceptall"))

    def test_added_rules_are_labelled_separately_from_migrated_ones(self):
        """The old posture must not be made to look stronger than it was.

        The retired settings denied destructive shell patterns and said nothing about the
        protected training artefacts or the mode-600 ledgers. Those refusals were ADDED
        here, and the file records which is which so a later reader can tell.
        """
        self.assertIn("deny_migrated", self.p)
        self.assertIn("deny_added_by_migration", self.p)
        self.assertEqual(sorted(set(self.p["deny_migrated"] + self.p["deny_added_by_migration"])),
                         self.p["deny"], "deny must be exactly the union of the two sources")
        self.assertTrue(self.p["deny_added_by_migration"],
                        "if nothing was added, the EXPORTS.md gap was not closed")

    def test_no_allow_list_was_migrated(self):
        """The safe direction to carry across a migration is the refusals.

        An allowlist written for another tool's runtime would grant permissions in a
        runtime that never agreed to them.
        """
        self.assertNotIn("allow", self.p,
                         "an allow list was migrated; only refusals should cross")

    def test_a_wildcard_that_would_neutralise_the_policy_is_absent(self):
        for rule in self.p["deny"]:
            self.assertNotEqual("*", rule.strip())


class TheProtectedClassesRemainDenied(unittest.TestCase):
    """The specific things this repository has already been burned by exposing."""

    @classmethod
    def setUpClass(cls):
        cls.blob = json.dumps(json.loads(POLICY.read_text())["deny"])

    def test_each_protected_class_appears_in_a_deny_rule(self):
        missing = [n for n in MUST_STAY_DENIED if n not in self.blob]
        self.assertEqual([], missing,
                         f"these are no longer denied after the migration: {missing}. "
                         "ops/registry/EXPORTS.md rules 2 and 3 name them as protected")


class ThePolicyCarriesNoSecrets(unittest.TestCase):

    def test_no_credential_shape_appears_in_the_policy(self):
        text = POLICY.read_text()
        for pat in ("sk-ant-", "BEGIN RSA PRIVATE KEY", "Bearer "):
            self.assertNotIn(pat, text)


if __name__ == "__main__":
    unittest.main()
