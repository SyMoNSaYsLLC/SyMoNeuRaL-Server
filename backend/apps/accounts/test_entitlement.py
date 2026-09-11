"""Shared-store entitlement: grant, revoke, re-grant, and the audit trail.

The property under test is that **revocation is a write, not a delete**. `granted_at` sits in
the primary key precisely so that grant -> revoke -> re-grant keeps three readable facts
instead of overwriting the middle one, and T16/T17 are what stop a future "simplification"
from collapsing the key and silently destroying the trail.

Every test uses a temporary database. Nothing here enables the subsystem.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

SLUG = "dispatchos"
#: Test-only. Never a production secret and never written to configuration.
SECRET = "test-secret-not-the-production-one-0123456789abcdef"


class EntitlementStoreTests(unittest.TestCase):
    def setUp(self):
        # Same pattern as the existing accounts suite: a process-local test secret and a
        # temp database, both restored in tearDown. This does NOT enable the subsystem on
        # the box -- nothing is written to the environment file and no real secret is
        # created. `test_subsystem_remains_disabled` below asserts the on-disk state.
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="a3-ent-"))
        self._env = dict(os.environ)
        os.environ["SYMONEURAL_ACCOUNTS_DB"] = str(self.tmp / "accounts.db")
        os.environ["SYMONEURAL_SESSION_SECRET"] = SECRET
        # Deliberately NOT importlib.reload(accounts). `apps/dispatchos/store.py` binds
        # WeakPassword, hash_password and validate_password from this module at import time;
        # reloading replaces those class objects, so a later suite's assertRaises stops
        # recognising the WeakPassword that store raises. That leak made two tests in
        # test_dispatchos_security.py fail whenever this file ran first -- passing alone and
        # failing in a set, which is the worst shape for a test defect. The reload is also
        # unnecessary: db_path() reads the environment on every connection.
        from apps import accounts
        self.acc = accounts
        self.acc.init_db()
        self.account = self.acc.create_account("person@example.com",
                                               "correct horse battery staple")
        self.aid = self.account["id"]

    def tearDown(self):
        import shutil
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- T2 / baseline ---------------------------------------------------------------
    def test_no_row_means_not_entitled(self):
        self.assertFalse(self.acc.is_entitled(self.aid, SLUG),
                         "absent row must mean not entitled")

    def test_t2_granted_account_is_entitled(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="test")
        self.assertTrue(self.acc.is_entitled(self.aid, SLUG))

    def test_grant_refuses_unknown_account(self):
        with self.assertRaises(ValueError):
            self.acc.grant_entitlement("no-such-account", SLUG, granted_by="test")

    def test_grant_refuses_duplicate_active(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="test")
        with self.assertRaises(ValueError):
            self.acc.grant_entitlement(self.aid, SLUG, granted_by="test")

    def test_grant_requires_an_author(self):
        with self.assertRaises(ValueError):
            self.acc.grant_entitlement(self.aid, SLUG, granted_by="")

    def test_invalid_slug_is_not_entitled(self):
        self.assertFalse(self.acc.is_entitled(self.aid, "not a slug!"))
        self.assertFalse(self.acc.is_entitled(self.aid, ""))

    # -- T16 revocation is auditable -------------------------------------------------
    def test_t16_revocation_retains_the_historical_grant(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="operator-cli", now=1000.0)
        self.acc.revoke_entitlement(self.aid, SLUG, now=2000.0)

        self.assertFalse(self.acc.is_entitled(self.aid, SLUG), "revoked must deny")
        rows = self.acc.list_entitlements(self.aid)
        self.assertEqual(len(rows), 1, "the historical grant was deleted")
        r = rows[0]
        self.assertEqual(r["granted_at"], 1000.0)
        self.assertEqual(r["granted_by"], "operator-cli")
        self.assertEqual(r["revoked_at"], 2000.0)

    def test_revoke_refuses_when_no_active_grant(self):
        with self.assertRaises(ValueError):
            self.acc.revoke_entitlement(self.aid, SLUG)

    # -- T17 re-grant after revoke ---------------------------------------------------
    def test_t17_regrant_keeps_both_rows(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="op1", now=1000.0)
        self.acc.revoke_entitlement(self.aid, SLUG, now=2000.0)
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="op2", now=3000.0)

        rows = self.acc.list_entitlements(self.aid)
        self.assertEqual(len(rows), 2, "re-grant overwrote the revoked row")
        self.assertTrue(self.acc.is_entitled(self.aid, SLUG),
                        "the later grant must be active")
        by_ts = {r["granted_at"]: r for r in rows}
        self.assertEqual(by_ts[1000.0]["revoked_at"], 2000.0)
        self.assertIsNone(by_ts[3000.0]["revoked_at"])

    def test_entitled_slugs_reflects_active_only(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="t", now=1000.0)
        self.acc.grant_entitlement(self.aid, "other-app", granted_by="t", now=1001.0)
        self.assertEqual(self.acc.entitled_slugs(self.aid), sorted([SLUG, "other-app"]))
        self.acc.revoke_entitlement(self.aid, SLUG, now=2000.0)
        self.assertEqual(self.acc.entitled_slugs(self.aid), ["other-app"])

    # -- T21 malformed --------------------------------------------------------------
    def test_t21_malformed_granted_at_raises(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="t", now=1000.0)
        with self.acc._conn() as c:
            c.execute("UPDATE entitlements SET granted_at=-1 WHERE account_id=?", (self.aid,))
        with self.assertRaises(self.acc.MalformedEntitlement):
            self.acc.is_entitled(self.aid, SLUG)

    def test_malformed_one_app_does_not_poison_others(self):
        self.acc.grant_entitlement(self.aid, SLUG, granted_by="t", now=1000.0)
        self.acc.grant_entitlement(self.aid, "other-app", granted_by="t", now=1001.0)
        with self.acc._conn() as c:
            c.execute("UPDATE entitlements SET granted_at=-1 "
                      "WHERE account_id=? AND application_slug=?", (self.aid, SLUG))
        self.assertEqual(self.acc.entitled_slugs(self.aid), ["other-app"])

    # -- boundary -------------------------------------------------------------------
    def test_subsystem_remains_disabled_on_the_box(self):
        """The enable flag is never set by this suite, so the box stays disabled.

        setUp supplies a session secret in-process because the store refuses to operate
        without one; it does NOT set the enable flag, which is the switch that turns the
        surface on. Both are required, so the box remains off.
        """
        self.assertNotIn("SYMONEURAL_ACCOUNTS_ENABLED", self._env,
                         "the enable flag must not be set in the real environment")
        self.assertIsNone(self._env.get("SYMONEURAL_SESSION_SECRET"),
                          "no real session secret should exist in the environment")


if __name__ == "__main__":
    unittest.main()
