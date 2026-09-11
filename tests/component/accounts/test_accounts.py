#!/usr/bin/env python3
"""Tests for SyMoNeuRaL Accounts. System interpreter, no network, no venv, no GPU.

    python3 backend/accounts/test_accounts.py

Every test runs against a throwaway sqlite file in a temp directory -- `SYMONEURAL_ACCOUNTS_DB`
exists for exactly this and for nothing else. Nothing here touches `run/`.

The cases that matter most are the ones where a bug looks like success:

  * a hash that equals the password, or that reaches a response dict
  * a session that outlives its expiry or its revocation
  * a throttle that engages and never lifts (a self-DoS that a "does it engage" test passes)
  * a missing `SYMONEURAL_SESSION_SECRET` that returns None instead of raising -- indistinguishable
    from a wrong password to the caller, which is the fail-open shape recorded as the most
    serious open finding in `.claude/HANDOVER.md` §5 item 1

Time is injected via the `now=` argument rather than slept, so the expiry and backoff tests
are exact and take no wall-clock. Real scrypt parameters are used throughout, so the suite
is seconds rather than milliseconds, and that is the point --
testing a cheap parameter set proves nothing about the one that ships.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import unittest

import accounts  # noqa: E402

SECRET = "test-secret-not-the-production-one-0123456789abcdef"
EMAIL = "garrett@symoneural.com"
PASSWORD = "a-long-enough-passphrase-42"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="symacct-test-"))
        self._env = dict(os.environ)
        os.environ["SYMONEURAL_ACCOUNTS_DB"] = str(self.dir / "accounts.db")
        os.environ["SYMONEURAL_SESSION_SECRET"] = SECRET
        os.environ["SYMONEURAL_ACCOUNTS_ENABLED"] = "1"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.dir, ignore_errors=True)

    def stored_hash(self, email=EMAIL) -> str:
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            row = c.execute("SELECT pw_hash FROM accounts WHERE email=?",
                            (accounts.normalise_email(email),)).fetchone()
        return row[0]


# --------------------------------------------------------------------- the switch

class TestFailsClosed(Base):
    """No secret means refuse. Not "no session", not "wrong password" -- refuse."""

    def test_every_entry_point_raises_with_no_session_secret(self):
        del os.environ["SYMONEURAL_SESSION_SECRET"]
        calls = {
            "create_account": lambda: accounts.create_account(EMAIL, PASSWORD),
            "verify": lambda: accounts.verify(EMAIL, PASSWORD),
            "issue_session": lambda: accounts.issue_session("whatever"),
            "read_session": lambda: accounts.read_session("symses1.a.b"),
            "revoke_session": lambda: accounts.revoke_session("symses1.a.b"),
            "account_public": lambda: accounts.account_public("whatever"),
            "change_password": lambda: accounts.change_password("x", PASSWORD, PASSWORD),
            "throttle_state": lambda: accounts.throttle_state(email=EMAIL),
        }
        for name, fn in calls.items():
            with self.subTest(entry_point=name):
                # The type is asserted, not merely "it was falsy". A caller that catches
                # Exception and continues is the bug; a distinct type is what makes that
                # catch visible in review.
                with self.assertRaises(accounts.AccountsUnavailable):
                    fn()

    def test_a_short_secret_is_treated_as_no_secret(self):
        os.environ["SYMONEURAL_SESSION_SECRET"] = "tooshort"
        self.assertFalse(accounts.enabled())
        with self.assertRaises(accounts.AccountsUnavailable):
            accounts.verify(EMAIL, PASSWORD)

    def test_the_surface_is_off_by_default(self):
        del os.environ["SYMONEURAL_ACCOUNTS_ENABLED"]
        self.assertFalse(accounts.enabled())
        del os.environ["SYMONEURAL_SESSION_SECRET"]
        self.assertFalse(accounts.enabled())

    def test_enabled_needs_both_switches(self):
        os.environ["SYMONEURAL_ACCOUNTS_ENABLED"] = "1"
        del os.environ["SYMONEURAL_SESSION_SECRET"]
        self.assertFalse(accounts.enabled())
        os.environ["SYMONEURAL_SESSION_SECRET"] = SECRET
        self.assertTrue(accounts.enabled())

    def test_unit_state_is_offline_when_not_configured(self):
        del os.environ["SYMONEURAL_ACCOUNTS_ENABLED"]
        state, detail = accounts.unit_state()
        self.assertEqual(state, "offline")
        self.assertIn("SYMONEURAL_ACCOUNTS_ENABLED", detail)


# --------------------------------------------------------------------- passwords

class TestPasswords(Base):
    def test_the_correct_password_is_accepted(self):
        made = accounts.create_account(EMAIL, PASSWORD)
        got = accounts.verify(EMAIL, PASSWORD)
        self.assertIsNotNone(got)
        self.assertEqual(got["id"], made["id"])

    def test_a_wrong_password_is_rejected(self):
        accounts.create_account(EMAIL, PASSWORD)
        self.assertIsNone(accounts.verify(EMAIL, PASSWORD + "!"))
        self.assertIsNone(accounts.verify(EMAIL, ""))
        self.assertIsNone(accounts.verify(EMAIL, PASSWORD[:-1]))

    def test_an_unknown_address_is_rejected_and_not_an_error(self):
        accounts.create_account(EMAIL, PASSWORD)
        self.assertIsNone(accounts.verify("nobody@example.com", PASSWORD))

    def test_the_stored_hash_is_never_the_password(self):
        accounts.create_account(EMAIL, PASSWORD)
        h = self.stored_hash()
        self.assertNotEqual(h, PASSWORD)
        self.assertNotIn(PASSWORD, h)
        # And it is not a plain digest of it either -- a salted KDF, not sha256(pw).
        for algo in ("md5", "sha1", "sha256", "sha512"):
            self.assertNotIn(hashlib.new(algo, PASSWORD.encode()).hexdigest(), h)

    def test_two_accounts_with_the_same_password_get_different_hashes(self):
        accounts.create_account("one@symoneural.com", PASSWORD)
        accounts.create_account("two@symoneural.com", PASSWORD)
        a = self.stored_hash("one@symoneural.com")
        b = self.stored_hash("two@symoneural.com")
        self.assertNotEqual(a, b)
        # Specifically the SALT differs. Equal salts with different digests would mean
        # something much stranger than a missing salt.
        self.assertNotEqual(a.split("$")[2], b.split("$")[2])

    def test_hashing_the_same_password_twice_differs(self):
        self.assertNotEqual(accounts.hash_password(PASSWORD),
                            accounts.hash_password(PASSWORD))

    def test_the_hash_records_its_own_parameters(self):
        h = accounts.hash_password(PASSWORD)
        self.assertTrue(h.startswith(
            f"scrypt$n={accounts.SCRYPT_N},r={accounts.SCRYPT_R},p={accounts.SCRYPT_P}$"))
        self.assertFalse(accounts.needs_rehash(h))
        self.assertTrue(accounts.needs_rehash("scrypt$n=16384,r=8,p=1$AAAA$BBBB"))
        self.assertTrue(accounts.needs_rehash("not-a-hash"))

    def test_a_legacy_hash_upgrades_after_a_successful_login(self):
        made = accounts.create_account(EMAIL, PASSWORD)
        salt = b"legacy-salt-1234"
        dk = accounts._derive(PASSWORD, salt, 65536, 8, 1)
        legacy = f"scrypt$n=65536,r=8,p=1${accounts._b64e(salt)}${accounts._b64e(dk)}"
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            c.execute("UPDATE accounts SET pw_hash=? WHERE id=?", (legacy, made["id"]))
        self.assertTrue(accounts.needs_rehash(self.stored_hash()))
        self.assertIsNotNone(accounts.verify(EMAIL, PASSWORD))
        upgraded = self.stored_hash()
        self.assertFalse(accounts.needs_rehash(upgraded))
        self.assertTrue(upgraded.startswith("scrypt$n=131072,r=8,p=1$"))

    def test_the_unknown_account_dummy_uses_the_current_cost(self):
        self.assertFalse(accounts.needs_rehash(accounts._DUMMY_HASH))

    def test_a_corrupt_hash_rejects_rather_than_raising(self):
        for bad in ("", "x", "scrypt$", "argon2$n=1$a$b", "scrypt$n=z,r=8,p=1$a$b"):
            with self.subTest(stored=bad):
                self.assertFalse(accounts.check_password(bad, PASSWORD))

    def test_short_and_obvious_passwords_are_refused(self):
        for bad in ("short", "12345678901", "password123", "PASSWORD"):
            with self.subTest(password=bad):
                with self.assertRaises(accounts.WeakPassword):
                    accounts.create_account(EMAIL, bad)

    def test_a_password_containing_the_email_name_is_refused(self):
        with self.assertRaises(accounts.WeakPassword):
            accounts.create_account(EMAIL, "garrett-garrett-garrett")

    def test_scrypt_needs_maxmem_passed_explicitly(self):
        """The gotcha this module documents, asserted rather than asserted-about.

        `hashlib.scrypt` defaults to `maxmem=0`, which OpenSSL reads as 32 MiB. At the
        shipped parameters the bare call raises. If a future Python or OpenSSL changes
        that default this test fails, which is the notification we want.
        """
        with self.assertRaises(ValueError):
            hashlib.scrypt(b"x", salt=b"y" * 16, n=accounts.SCRYPT_N,
                           r=accounts.SCRYPT_R, p=accounts.SCRYPT_P, dklen=32)
        # And the module's own call, which passes maxmem, does not.
        self.assertEqual(len(accounts._derive(PASSWORD, b"y" * 16, accounts.SCRYPT_N,
                                              accounts.SCRYPT_R, accounts.SCRYPT_P)), 32)


# --------------------------------------------------------------------- registration

class TestRegistration(Base):
    def test_duplicates_are_refused(self):
        accounts.create_account(EMAIL, PASSWORD)
        with self.assertRaises(accounts.AccountExists):
            accounts.create_account(EMAIL, PASSWORD + "-different")

    def test_duplicates_are_refused_case_and_whitespace_insensitively(self):
        accounts.create_account(EMAIL, PASSWORD)
        with self.assertRaises(accounts.AccountExists):
            accounts.create_account("  GARRETT@SymOneural.COM ", PASSWORD)

    def test_malformed_addresses_are_refused(self):
        for bad in ("", "   ", "garrett", "garrett@", "@symoneural.com",
                    "garrett@symoneural", "a b@symoneural.com", "a@@b.com",
                    "a@" + "x" * 300 + ".com"):
            with self.subTest(email=bad):
                with self.assertRaises(accounts.InvalidEmail):
                    accounts.create_account(bad, PASSWORD)

    def test_the_address_the_visitor_typed_is_kept_alongside_the_normalised_one(self):
        made = accounts.create_account("  Garrett@SymOneural.com ", PASSWORD)
        self.assertEqual(made["email"], EMAIL)
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            shown = c.execute("SELECT email_shown FROM accounts").fetchone()[0]
        self.assertEqual(shown, "Garrett@SymOneural.com")

    def test_an_account_may_carry_a_quote_id_and_no_amount(self):
        made = accounts.create_account(EMAIL, PASSWORD, quote_id="Q-2026-0001")
        self.assertEqual(made["quote_id"], "Q-2026-0001")
        # The schema must not have grown anything price-shaped. This is a rule from
        # .claude/CLAUDE.md, not a preference, and a column is how it would get broken.
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            cols = {r[1].lower() for r in c.execute("PRAGMA table_info(accounts)")}
        for banned in ("price", "amount", "plan", "tier", "cost", "usd", "cents",
                       "subscription", "seats", "billing"):
            self.assertNotIn(banned, cols)


# --------------------------------------------------------------------- leakage

class TestNothingLeaksTheHash(Base):
    def test_account_public_carries_no_hash_or_salt(self):
        made = accounts.create_account(EMAIL, PASSWORD)
        stored = self.stored_hash()
        salt = stored.split("$")[2]
        dk = stored.split("$")[3]
        for d in (made, accounts.account_public(made["id"]),
                  accounts.find_by_email(EMAIL), accounts.verify(EMAIL, PASSWORD)):
            blob = json.dumps(d)
            self.assertNotIn(stored, blob)
            self.assertNotIn(salt, blob)
            self.assertNotIn(dk, blob)
            self.assertNotIn(PASSWORD, blob)
            self.assertNotIn("scrypt", blob)

    def test_public_output_is_an_allowlist_not_a_denylist(self):
        """A column added later must not appear until somebody adds it deliberately.

        Written this way because the realistic failure is not `del d['pw_hash']` being
        forgotten today; it is a `recovery_answer` column added in six months and
        published by a dict comprehension over `row.keys()`.
        """
        made = accounts.create_account(EMAIL, PASSWORD)
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            c.execute("ALTER TABLE accounts ADD COLUMN secret_note TEXT")
            c.execute("UPDATE accounts SET secret_note='do-not-publish'")
            c.commit()
        pub = accounts.account_public(made["id"])
        self.assertEqual(set(pub), set(accounts.PUBLIC_FIELDS))
        self.assertNotIn("do-not-publish", json.dumps(pub))


# --------------------------------------------------------------------- sessions

class TestSessions(Base):
    def setUp(self):
        super().setUp()
        self.acct = accounts.create_account(EMAIL, PASSWORD)

    def test_a_fresh_session_reads_back(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        s = accounts.read_session(t, now=1001.0)
        self.assertIsNotNone(s)
        self.assertEqual(s["account_id"], self.acct["id"])
        self.assertEqual(s["account"]["email"], EMAIL)
        self.assertNotIn("verifier", json.dumps(s))

    def test_a_session_expires(self):
        t = accounts.issue_session(self.acct["id"], ttl_s=60, now=1000.0)
        self.assertIsNotNone(accounts.read_session(t, now=1059.0))
        self.assertIsNone(accounts.read_session(t, now=1060.0))
        self.assertIsNone(accounts.read_session(t, now=100000.0))

    def test_a_revoked_session_is_rejected(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        self.assertIsNotNone(accounts.read_session(t, now=1001.0))
        self.assertTrue(accounts.revoke_session(t))
        self.assertIsNone(accounts.read_session(t, now=1002.0))
        # Idempotent: revoking twice is not an error, and reports it changed nothing.
        self.assertFalse(accounts.revoke_session(t))

    def test_a_tampered_token_is_rejected(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        prefix, sid, rand = t.split(".")
        for bad in (f"{prefix}.{sid}.{'A' * len(rand)}",     # right sid, wrong secret half
                    f"{prefix}.{sid}",                       # truncated
                    f"nope.{sid}.{rand}",                    # wrong prefix
                    t + "x", t[:-1], "", "....", sid):
            with self.subTest(token=bad[:24]):
                self.assertIsNone(accounts.read_session(bad, now=1001.0))

    def test_knowing_the_sid_alone_cannot_revoke_someone_elses_session(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        _, sid, rand = t.split(".")
        self.assertFalse(accounts.revoke_session(f"symses1.{sid}.{'A' * len(rand)}"))
        self.assertIsNotNone(accounts.read_session(t, now=1001.0))

    def test_the_database_stores_a_verifier_and_not_the_token(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            rows = c.execute("SELECT sid, verifier FROM sessions").fetchall()
        self.assertEqual(len(rows), 1)
        sid, verifier = rows[0]
        self.assertNotIn(t, verifier)
        self.assertNotIn(t.split(".")[2], verifier)
        self.assertNotEqual(verifier, sid)

    def test_a_verifier_read_out_of_the_database_is_not_a_usable_token(self):
        """The actual claim, not the weaker one.

        `test_the_database_stores_a_verifier_and_not_the_token` only proves the stored
        string is not the token. What matters is that somebody holding a COPY OF THE FILE
        cannot log in with what they found -- which is the whole reason the secret exists
        when the rows are already authoritative.
        """
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            sid, verifier = c.execute("SELECT sid, verifier FROM sessions").fetchone()
        for stolen in (verifier,
                       f"symses1.{sid}.{verifier}",
                       f"{accounts.TOKEN_PREFIX}.{sid}.{verifier}",
                       sid):
            with self.subTest(attempt=stolen[:32]):
                self.assertIsNone(accounts.read_session(stolen, now=1001.0))
                self.assertFalse(accounts.revoke_session(stolen))
        # ... and the real token still works, so the loop above proved a refusal rather
        # than a broken session.
        self.assertIsNotNone(accounts.read_session(t, now=1001.0))

    def test_changing_the_password_is_throttled_too(self):
        """A stolen session must not be an unmetered oracle for the real password."""
        new = "another-long-enough-passphrase"
        for i in range(accounts.ACCOUNT_FREE_FAILS + 1):
            self.assertFalse(accounts.change_password(self.acct["id"], "wrong-guess-here",
                                                      new, now=1000.0 + i))
        last = 1000.0 + accounts.ACCOUNT_FREE_FAILS
        with self.assertRaises(accounts.Throttled):
            accounts.change_password(self.acct["id"], PASSWORD, new, now=last + 1)
        # It shares the account key with login, so login is locked too -- four wrong
        # guesses at one password are four wrong guesses however they were made.
        with self.assertRaises(accounts.Throttled):
            accounts.verify(EMAIL, PASSWORD, now=last + 1)

    def test_rotating_the_server_secret_invalidates_every_session(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        self.assertIsNotNone(accounts.read_session(t, now=1001.0))
        os.environ["SYMONEURAL_SESSION_SECRET"] = SECRET[::-1]
        self.assertIsNone(accounts.read_session(t, now=1001.0))

    def test_a_disabled_account_has_no_live_session(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        self.assertTrue(accounts.set_disabled(self.acct["id"]))
        self.assertIsNone(accounts.read_session(t, now=1001.0))
        self.assertIsNone(accounts.verify(EMAIL, PASSWORD, now=1001.0))
        with self.assertRaises(accounts.AccountsError):
            accounts.issue_session(self.acct["id"], now=1001.0)

    def test_changing_the_password_revokes_live_sessions(self):
        t = accounts.issue_session(self.acct["id"], now=1000.0)
        new = "another-long-enough-passphrase"
        self.assertTrue(accounts.change_password(self.acct["id"], PASSWORD, new))
        self.assertIsNone(accounts.read_session(t, now=1001.0))
        self.assertIsNone(accounts.verify(EMAIL, PASSWORD, now=1001.0))
        self.assertIsNotNone(accounts.verify(EMAIL, new, now=1001.0))

    def test_changing_the_password_requires_the_old_one(self):
        self.assertFalse(accounts.change_password(self.acct["id"], "wrong-one-entirely",
                                                  "another-long-enough-passphrase"))

    def test_sessions_for_lists_live_ones_only(self):
        a = accounts.issue_session(self.acct["id"], ttl_s=60, now=1000.0)
        b = accounts.issue_session(self.acct["id"], ttl_s=6000, now=1000.0)
        self.assertEqual(len(accounts.sessions_for(self.acct["id"], now=1001.0)), 2)
        self.assertEqual(len(accounts.sessions_for(self.acct["id"], now=1100.0)), 1)
        accounts.revoke_session(b)
        self.assertEqual(accounts.sessions_for(self.acct["id"], now=1100.0), [])
        self.assertIsNone(accounts.read_session(a, now=1100.0))


# --------------------------------------------------------------------- throttle

class TestThrottle(Base):
    """Account-scoped backoff. This is the module's answer to an unthrottled API.

    Rate limiting is OFF across the whole API today at the operator's instruction
    (`backend/server.py`, `_rate_for`). Nothing here re-enables it: this is a per-account
    lockout, it counts failures rather than requests, and a correct password never
    touches it. See `backend/accounts/docs/accounts-spec.md` for why those are different things.
    """

    def setUp(self):
        super().setUp()
        accounts.create_account(EMAIL, PASSWORD)

    def fail_until_locked(self, t: float) -> float:
        """Fail one past the free allowance and return the time of the last attempt.

        Returned rather than assumed: the first lockout is ACCOUNT_BASE_LOCK_S long, so a
        test that probes at a hardcoded offset silently stops testing anything the moment
        somebody tunes the constant. Ask the module where it is instead.
        """
        for i in range(accounts.ACCOUNT_FREE_FAILS + 1):
            accounts.verify(EMAIL, "wrong-password-here", now=t + i)
        last = t + accounts.ACCOUNT_FREE_FAILS
        st = accounts.throttle_state(email=EMAIL, now=last)["account"]
        self.assertTrue(st and st["locked"], f"expected a lockout, got {st}")
        return last

    def test_the_throttle_engages_after_n_failures(self):
        t = 1000.0
        for i in range(accounts.ACCOUNT_FREE_FAILS):
            self.assertIsNone(accounts.verify(EMAIL, "wrong-password-here", now=t + i))
        # The next failure locks it.
        self.assertIsNone(accounts.verify(EMAIL, "wrong-password-here", now=t + 10))
        with self.assertRaises(accounts.Throttled) as ctx:
            accounts.verify(EMAIL, "wrong-password-here", now=t + 11)
        self.assertEqual(ctx.exception.scope, "account")
        self.assertGreaterEqual(ctx.exception.retry_after, 1)

    def test_a_locked_account_refuses_even_the_correct_password(self):
        last = self.fail_until_locked(1000.0)
        with self.assertRaises(accounts.Throttled):
            accounts.verify(EMAIL, PASSWORD, now=last + 1)

    def test_the_lockout_lifts(self):
        """A lockout with no exit is a self-DoS, and "does it engage" passes on that bug."""
        last = self.fail_until_locked(1000.0)
        with self.assertRaises(accounts.Throttled):
            accounts.verify(EMAIL, PASSWORD, now=last + 1)
        later = last + accounts.ACCOUNT_MAX_LOCK_S + 1
        self.assertIsNotNone(accounts.verify(EMAIL, PASSWORD, now=later))

    def test_the_backoff_grows(self):
        t = 1000.0
        waits = []
        for i in range(accounts.ACCOUNT_FREE_FAILS + 4):
            try:
                accounts.verify(EMAIL, "wrong-password-here", now=t)
            except accounts.Throttled:
                pass
            st = accounts.throttle_state(email=EMAIL, now=t)
            if st["account"] and st["account"]["locked"]:
                waits.append(st["account"]["retry_after"])
            t += accounts.ACCOUNT_MAX_LOCK_S + 1     # step past each lock to fail again
        self.assertGreater(len(waits), 2)
        self.assertEqual(waits, sorted(waits), f"backoff went backwards: {waits}")
        # Sorted alone passes on a FLAT sequence, which is a throttle that never gets
        # harder. Assert it actually grew.
        self.assertGreater(waits[-1], waits[0], f"backoff is constant: {waits}")

    def test_a_success_clears_the_counter(self):
        t = 1000.0
        for i in range(accounts.ACCOUNT_FREE_FAILS):
            accounts.verify(EMAIL, "wrong-password-here", now=t + i)
        self.assertIsNotNone(accounts.verify(EMAIL, PASSWORD, now=t + 10))
        self.assertIsNone(accounts.throttle_state(email=EMAIL, now=t + 11)["account"])

    def test_the_address_counter_is_separate_from_the_account_counter(self):
        """Spraying one password across many accounts must still cost the address."""
        t = 1000.0
        for i in range(accounts.IP_FREE_FAILS + 1):
            accounts.create_account(f"user{i}@symoneural.com", PASSWORD)
        for i in range(accounts.IP_FREE_FAILS + 1):
            accounts.verify(f"user{i}@symoneural.com", "wrong-password-here",
                            ip="203.0.113.9", now=t + i)
        last = t + accounts.IP_FREE_FAILS
        with self.assertRaises(accounts.Throttled) as ctx:
            accounts.verify("user0@symoneural.com", PASSWORD, ip="203.0.113.9",
                            now=last + 1)
        self.assertEqual(ctx.exception.scope, "ip")
        # A different address is unaffected -- the lockout is not global.
        self.assertIsNotNone(accounts.verify("user0@symoneural.com", PASSWORD,
                                             ip="198.51.100.4", now=last + 1))

    def test_the_throttle_survives_a_restart(self):
        """It is in sqlite, not in memory. `systemctl restart symoneural-api` is routine
        here, so an in-memory counter would mean the attacker's cost is "wait for a
        deploy" -- which is no cost at all."""
        last = self.fail_until_locked(1000.0)
        # Simulating a restart is simply talking to the same file again -- there is no
        # process-local state to clear, and that is the property under test.
        with sqlite3.connect(os.environ["SYMONEURAL_ACCOUNTS_DB"]) as c:
            n = c.execute("SELECT fails FROM attempts WHERE scope='account'").fetchone()[0]
        self.assertGreaterEqual(n, accounts.ACCOUNT_FREE_FAILS + 1)
        with self.assertRaises(accounts.Throttled):
            accounts.verify(EMAIL, PASSWORD, now=last + 1)


# --------------------------------------------------------------------- selftest

class TestSelftest(Base):
    def test_selftest_reports_ok_when_configured(self):
        r = accounts.selftest()
        self.assertTrue(r["ok"], r)
        self.assertIsNone(r["error"])
        self.assertEqual(r["accounts"], 0)
        self.assertEqual(r["scrypt"]["mem_mib"], 128)
        self.assertGreater(r["hash_ms"], 0)

    def test_selftest_reports_the_fail_closed_path_rather_than_raising(self):
        del os.environ["SYMONEURAL_SESSION_SECRET"]
        r = accounts.selftest()
        self.assertFalse(r["ok"])
        self.assertFalse(r["secret_present"])
        self.assertIn("SYMONEURAL_SESSION_SECRET", r["error"])

    def test_the_database_is_not_under_site(self):
        os.environ.pop("SYMONEURAL_ACCOUNTS_DB")
        p = str(accounts.db_path())
        self.assertNotIn("/site/", p)
        self.assertIn("/run/accounts/", p)
        # And it cannot be the governor's mutex.
        self.assertNotIn("gpu.lock", p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
