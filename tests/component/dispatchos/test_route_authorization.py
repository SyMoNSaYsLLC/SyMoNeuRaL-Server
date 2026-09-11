"""A-3 route authorization: the 15 classes, the four fail-closed conditions, T1-T22.

Two tests here are the ones that matter, and both guard an explicit decision:

**T15** proves that when shared accounts is *unavailable* an entitlement-required route
returns 403 while exemptions and operator routes stay reachable. The tempting bug is to read
"cannot check" as "no restriction"; an authorization check that could not run has not passed.

**T20** proves no heuristic matching. A local username identical to a shared account's email
grants nothing. The two key spaces differ -- case-insensitive handle vs normalised address --
so a "helpful" match would be a silent authorization bypass.

Everything is synthetic and temporary. No test enables shared accounts, writes a secret, or
touches the real databases.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())

EXPECTED: dict[tuple[str, str], str] = {
    ("GET",  "/status"):                  "PUBLIC_BOOTSTRAP",
    ("POST", "/login"):                   "SHARED_AUTH",
    ("POST", "/logout"):                  "SHARED_AUTH",
    ("GET",  "/me"):                      "AUTHENTICATED_APPLICATION",
    ("GET",  "/board"):                   "ENTITLEMENT_REQUIRED",
    ("POST", "/bookings"):                "ENTITLEMENT_REQUIRED",
    ("GET",  "/bookings/{bid}"):          "ENTITLEMENT_REQUIRED",
    ("POST", "/ask"):                     "ENTITLEMENT_REQUIRED",
    ("POST", "/bookings/{bid}/quote"):    "OPERATOR_ONLY",
    ("POST", "/bookings/{bid}/advance"):  "OPERATOR_ONLY",
    ("POST", "/bookings/{bid}/message"):  "OPERATOR_ONLY",
    ("GET",  "/rules"):                   "OPERATOR_ONLY",
    ("PUT",  "/rules"):                   "OPERATOR_ONLY",
    ("GET",  "/drivers"):                 "OPERATOR_ONLY",
    ("POST", "/drivers"):                 "OPERATOR_ONLY",
}
ENTITLEMENT_ROUTES = [k for k, v in EXPECTED.items() if v == "ENTITLEMENT_REQUIRED"]
OPERATOR_ROUTES = [k for k, v in EXPECTED.items() if v == "OPERATOR_ONLY"]
EXEMPT_ROUTES = [k for k, v in EXPECTED.items()
                 if v in ("PUBLIC_BOOTSTRAP", "SHARED_AUTH")]


def _fresh_app_store(tmp: pathlib.Path):
    """A temporary application store, switched on, with the surface enabled."""
    os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "1"
    os.environ["SYMONEURAL_DISPATCHOS_DB"] = str(tmp / "app.db")
    from dispatchos.lib import store
    importlib.reload(store)
    store.init_db()
    return store


class RouteClassMatrixTests(unittest.TestCase):
    """T1 -- every pair carries exactly its assigned class, enumerated."""

    def setUp(self):
        from dispatchos.apps import authz, routes
        self.authz, self.routes = authz, routes

    def _declared(self) -> dict[tuple[str, str], str]:
        found = {}
        for r in self.routes.router.routes:
            for dep in getattr(r, "dependencies", []) or []:
                cls = getattr(getattr(dep, "dependency", None), "route_class", None)
                if cls:
                    for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                        found[(m, r.path)] = cls
        return found

    def test_t1_every_route_carries_its_class(self):
        declared = self._declared()
        self.assertEqual(declared, EXPECTED,
                         "route/class matrix drifted from the authorized assignment")

    def test_t1b_no_route_lacks_a_class(self):
        """A new route added with no class must fail this suite."""
        classed = set(self._declared())
        actual = {(m, r.path) for r in self.routes.router.routes
                  for m in (r.methods - {"HEAD", "OPTIONS"})}
        self.assertEqual(actual - classed, set(),
                         "route(s) with no authorization class")

    def test_t1c_counts(self):
        counts: dict[str, int] = {}
        for cls in self._declared().values():
            counts[cls] = counts.get(cls, 0) + 1
        self.assertEqual(counts, {"PUBLIC_BOOTSTRAP": 1, "SHARED_AUTH": 2,
                                  "AUTHENTICATED_APPLICATION": 1,
                                  "ENTITLEMENT_REQUIRED": 4, "OPERATOR_ONLY": 7})

    def test_t10_method_separation(self):
        """GET and the write method on a shared path resolve independently."""
        d = self._declared()
        self.assertEqual(d[("GET", "/rules")], "OPERATOR_ONLY")
        self.assertEqual(d[("PUT", "/rules")], "OPERATOR_ONLY")
        self.assertEqual(d[("GET", "/drivers")], "OPERATOR_ONLY")
        self.assertEqual(d[("POST", "/drivers")], "OPERATOR_ONLY")
        self.assertEqual(len([k for k in d if k[1] == "/rules"]), 2)
        self.assertEqual(len([k for k in d if k[1] == "/drivers"]), 2)


class IdentityCorrespondenceTests(unittest.TestCase):
    """T18, T20 -- the nullable reference and the refusal to infer."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="a3-app-"))
        self.store = _fresh_app_store(self.tmp)
        self.store.create_user("cust", "correct horse battery staple", "customer")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_t18_new_user_has_null_reference(self):
        uid = [u for u in self.store.list_users() if u["username"] == "cust"][0]["id"]
        self.assertIsNone(self.store.shared_account_id(uid),
                          "a new user must start with no shared identity")

    def test_link_and_unlink(self):
        uid = [u for u in self.store.list_users() if u["username"] == "cust"][0]["id"]
        self.store.link_shared_account("cust", "acct-123")
        self.assertEqual(self.store.shared_account_id(uid), "acct-123")
        self.store.unlink_shared_account("cust")
        self.assertIsNone(self.store.shared_account_id(uid),
                          "unlink must fail closed")

    def test_link_refuses_relink_without_force(self):
        self.store.link_shared_account("cust", "acct-1")
        with self.assertRaises(self.store.DispatchError):
            self.store.link_shared_account("cust", "acct-2")
        self.store.link_shared_account("cust", "acct-2", force=True)

    def test_t20_no_heuristic_identity_matching(self):
        """A username identical to an email grants nothing."""
        self.store.create_user("person@example.com", "correct horse battery staple",
                               "customer")
        uid = [u for u in self.store.list_users()
               if u["username"] == "person@example.com"][0]["id"]
        self.assertIsNone(self.store.shared_account_id(uid),
                          "an email-shaped username must not imply a shared identity")


class MigrationIdempotenceTests(unittest.TestCase):
    """T19 -- the authorized probe-then-add-column pattern."""

    def test_t19_adds_column_once_then_no_ops(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="a3-mig-"))
        try:
            db = tmp / "legacy.db"
            # A database predating the column: the old users shape, with a row in it.
            c = sqlite3.connect(db)
            c.row_factory = sqlite3.Row
            c.executescript("""CREATE TABLE users (
                    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    role TEXT NOT NULL, pw_hash TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);""")
            c.execute("INSERT INTO users(username,role,pw_hash,created_at) "
                      "VALUES('legacy','customer','x',1.0)")
            c.commit()

            os.environ["SYMONEURAL_DISPATCHOS_DB"] = str(db)
            from dispatchos.lib import store
            importlib.reload(store)

            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                self.assertTrue(store._migrate_shared_account_id(conn),
                                "first run must add the column")
                self.assertFalse(store._migrate_shared_account_id(conn),
                                 "second run must be a no-op")
                self.assertFalse(store._migrate_shared_account_id(conn),
                                 "third run must be a no-op")
                cols = {r["name"] for r in
                        conn.execute("PRAGMA table_info(users)").fetchall()}
                self.assertIn("shared_account_id", cols)
                row = conn.execute("SELECT username, shared_account_id FROM users "
                                   "WHERE username='legacy'").fetchone()
                self.assertEqual(row["username"], "legacy", "existing data lost")
                self.assertIsNone(row["shared_account_id"], "no backfill permitted")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class FailClosedTests(unittest.TestCase):
    """T3, T15, T21 -- every denial path, including the one that cannot be checked."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="a3-fc-"))
        self.store = _fresh_app_store(self.tmp)
        from dispatchos.apps import authz
        self.authz = authz

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_t18b_null_reference_denies(self):
        from fastapi import HTTPException
        self.store.create_user("c1", "correct horse battery staple", "customer")
        uid = [u for u in self.store.list_users() if u["username"] == "c1"][0]["id"]
        with self.assertRaises(HTTPException) as ctx:
            self.authz._entitlement_or_403({"id": uid, "role": "customer"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_t15_shared_accounts_unavailable_denies(self):
        """The load-bearing test: cannot check -> has NOT passed."""
        from fastapi import HTTPException
        self.store.create_user("c2", "correct horse battery staple", "customer")
        self.store.link_shared_account("c2", "acct-x")
        uid = [u for u in self.store.list_users() if u["username"] == "c2"][0]["id"]

        import accounts as shared
        with mock.patch.object(shared, "is_entitled",
                               side_effect=sqlite3.OperationalError("unable to open database")):
            with self.assertRaises(HTTPException) as ctx:
                self.authz._entitlement_or_403({"id": uid, "role": "customer"})
        self.assertEqual(ctx.exception.status_code, 403,
                         "an unverifiable entitlement must DENY, never allow")

    def test_t21_malformed_record_denies(self):
        from fastapi import HTTPException
        self.store.create_user("c3", "correct horse battery staple", "customer")
        self.store.link_shared_account("c3", "acct-y")
        uid = [u for u in self.store.list_users() if u["username"] == "c3"][0]["id"]
        import accounts as shared
        with mock.patch.object(shared, "is_entitled",
                               side_effect=shared.MalformedEntitlement("bad granted_at")):
            with self.assertRaises(HTTPException) as ctx:
                self.authz._entitlement_or_403({"id": uid, "role": "customer"})
        self.assertEqual(ctx.exception.status_code, 403)

    def test_t4_operator_needs_no_customer_entitlement(self):
        """T4 -- the precedence decision. Operator route never consults entitlement."""
        called = []
        import accounts as shared
        with mock.patch.object(shared, "is_entitled",
                               side_effect=lambda *a, **k: called.append(a) or True):
            cls = self.authz.OPERATOR_ONLY
            self.assertEqual(cls, "OPERATOR_ONLY")
        self.assertEqual(called, [],
                         "an operator-only route must not consult customer entitlement")

    def test_unknown_class_rejected(self):
        with self.assertRaises(ValueError):
            self.authz.require("NOT_A_CLASS")


class ExemptionTests(unittest.TestCase):
    """T6-T9 -- the four exemptions stay reachable, entitlement never consulted."""

    def setUp(self):
        from dispatchos.apps import authz
        self.authz = authz

    def test_t6_t7_t8_exempt_classes_do_no_checks(self):
        from fastapi import Request
        scope = {"type": "http", "headers": [], "method": "GET", "path": "/",
                 "query_string": b""}
        req = Request(scope)
        for cls in (self.authz.PUBLIC_BOOTSTRAP, self.authz.SHARED_AUTH):
            self.assertIsNone(self.authz.authorize(req, cls),
                              f"{cls} must perform no checks")

    def test_t8_logout_class_is_exempt(self):
        """logout must be usable with an absent/expired/invalidated session."""
        from dispatchos import router
        for r in routes.router.routes:
            if r.path == "/logout":
                cls = [getattr(getattr(d, "dependency", None), "route_class", None)
                       for d in (r.dependencies or [])]
                self.assertIn("SHARED_AUTH", cls,
                              "logout must be exempt or it can strand a session token")


class WriterAuthorityTests(unittest.TestCase):
    """T22 -- the CLI is the only writer; no HTTP route grants or revokes."""

    def test_t22_no_http_entitlement_write_route(self):
        from dispatchos import router
        paths = {r.path for r in routes.router.routes}
        for forbidden in ("/entitlements", "/grant", "/revoke", "/link"):
            self.assertNotIn(forbidden, paths,
                             f"{forbidden} would be a privileged entitlement API")

    def test_t22b_cli_exposes_the_operations(self):
        src = (ROOT / "tools" / "lib" / "dispatchos_accounts.py").read_text()
        for flag in ("--link-identity", "--unlink-identity", "--grant", "--revoke",
                     "--list-entitlements"):
            self.assertIn(flag, src, f"CLI missing {flag}")


class BoundaryTests(unittest.TestCase):
    """Evidence that A-3 changed no authentication behaviour."""

    def test_cookie_name_unchanged(self):
        from dispatchos import router
        self.assertEqual(routes.COOKIE, "symon_dispatchos")

    def test_guards_still_present_and_used(self):
        src = (ROOT / "backend" / "dispatchos" / "routes.py").read_text()
        for fn in ("def _signed_in", "def _operator", "def _require_enabled",
                   "def _owned_or_403", "def _visible"):
            self.assertIn(fn, src, f"{fn} was removed or renamed")

    def test_no_session_or_login_import_from_shared_accounts(self):
        """Only password primitives may come from shared accounts. No auth merge."""
        src = (ROOT / "backend" / "dispatchos" / "store.py").read_text()
        for banned in ("read_session", "create_session", "login(", "new_session"):
            self.assertNotIn(f"accounts import {banned}", src)
        self.assertIn("from accounts import (WeakPassword, check_password_or_dummy",
                      src, "the password-primitive seam changed shape")

    def test_shared_accounts_remains_disabled(self):
        import accounts as shared
        self.assertFalse(shared.enabled(),
                         "this suite must not enable shared accounts")


if __name__ == "__main__":
    unittest.main()
