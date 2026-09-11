#!/usr/bin/env python3
"""Security regression tests for the DispatchOS store and login boundary.

The store is loaded directly so this suite remains runnable with the system Python even
when the optional FastAPI runtime is absent.  Every database is a throwaway temp file.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

STORE_PATH = ROOT / "backend" / "apps" / "dispatchos" / "store.py"
SPEC = importlib.util.spec_from_file_location("dispatchos_security_store", STORE_PATH)
assert SPEC and SPEC.loader
store = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(store)


class Base(unittest.TestCase):
    def setUp(self):
        self.tempdir = pathlib.Path(tempfile.mkdtemp(prefix="dispatch-security-"))
        self.old_db = os.environ.get("SYMONEURAL_DISPATCHOS_DB")
        os.environ["SYMONEURAL_DISPATCHOS_DB"] = str(self.tempdir / "dispatchos.db")
        store.init_db()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("SYMONEURAL_DISPATCHOS_DB", None)
        else:
            os.environ["SYMONEURAL_DISPATCHOS_DB"] = self.old_db
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def insert_user(self, username: str = "operator", pw_hash: str = "test-hash") -> int:
        with sqlite3.connect(os.environ["SYMONEURAL_DISPATCHOS_DB"]) as conn:
            cur = conn.execute(
                "INSERT INTO users(username, role, pw_hash, label, created_at) "
                "VALUES(?,?,?,?,?)", (username, "operator", pw_hash, "Operator", 1.0))
            return int(cur.lastrowid)


class TestPasswordPolicy(Base):
    def test_create_user_reuses_the_fifteen_character_account_policy(self):
        with mock.patch.object(store, "hash_password", return_value="test-hash"):
            with self.assertRaises(store.DispatchError):
                store.create_user("operator", "only-14-chars!", "operator")

    def test_set_password_reuses_the_fifteen_character_account_policy(self):
        self.insert_user()
        with mock.patch.object(store, "hash_password", return_value="test-hash"):
            with self.assertRaises(store.DispatchError):
                store.set_password("operator", "only-14-chars!")


class TestLoginSecurity(Base):
    def test_a_real_current_hash_issues_a_readable_session(self):
        password = "a-genuinely-long-passphrase-42"
        made = store.create_user("operator", password, "operator", "Operator")
        token = store.login("operator", password, ip="198.51.100.7")
        self.assertIsNotNone(token)
        session = store.read_session(token)
        self.assertIsNotNone(session)
        self.assertEqual(session["id"], made["id"])
        self.assertNotIn(password, str(session))

    def test_unknown_user_does_not_generate_a_fresh_dummy_hash(self):
        # Generating a new dummy hash on each request doubles the unknown-user cost and
        # makes the timing distinguishable from a wrong password for a real user.
        with mock.patch.object(store, "hash_password",
                               side_effect=AssertionError("fresh dummy hash generated")):
            self.assertIsNone(store.login("missing", "wrong-password"))

    def test_account_throttle_is_persisted_and_engages(self):
        self.insert_user()
        checker = ("check_password_or_dummy" if hasattr(store, "check_password_or_dummy")
                   else "check_password")
        with mock.patch.object(store, checker, return_value=False):
            for i in range(store.ACCOUNT_FREE_FAILS + 1):
                self.assertIsNone(store.login("operator", "wrong", now=1000.0 + i))
            with self.assertRaises(store.DispatchThrottled):
                store.login("operator", "wrong", now=1004.0)
        with sqlite3.connect(os.environ["SYMONEURAL_DISPATCHOS_DB"]) as conn:
            row = conn.execute(
                "SELECT fails FROM login_attempts WHERE scope='account' AND key='operator'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row[0], store.ACCOUNT_FREE_FAILS + 1)

    def test_address_throttle_is_separate_from_account_throttle(self):
        checker = ("check_password_or_dummy" if hasattr(store, "check_password_or_dummy")
                   else "check_password")
        with mock.patch.object(store, checker, return_value=False):
            for i in range(store.IP_FREE_FAILS + 1):
                self.assertIsNone(store.login(
                    f"sprayed-user-{i}", "wrong", ip="203.0.113.8", now=2000.0 + i))
            with self.assertRaises(store.DispatchThrottled) as caught:
                store.login("another-user", "wrong", ip="203.0.113.8", now=2021.0)
        self.assertEqual(caught.exception.scope, "ip")

    def test_password_reset_revokes_existing_sessions(self):
        uid = self.insert_user()
        with sqlite3.connect(os.environ["SYMONEURAL_DISPATCHOS_DB"]) as conn:
            conn.execute(
                "INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                ("stolen-session", uid, 1.0, 9999999999.0))
        with mock.patch.object(store, "hash_password", return_value="replacement-hash"):
            store.set_password("operator", "a-new-long-passphrase")
        with sqlite3.connect(os.environ["SYMONEURAL_DISPATCHOS_DB"]) as conn:
            count = conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (uid,)).fetchone()[0]
        self.assertEqual(count, 0)


class TestRouteSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "backend" / "apps" / "dispatchos" / "routes.py").read_text(
            encoding="utf-8")

    def test_login_hashing_runs_off_the_event_loop(self):
        self.assertIn("await asyncio.to_thread(store.login", self.source)

    def test_dispatch_responses_are_marked_no_store(self):
        self.assertIn("dependencies=[Depends(_no_store)]", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
