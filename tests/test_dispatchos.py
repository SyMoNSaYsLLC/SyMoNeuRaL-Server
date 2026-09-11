"""DispatchOS: the lifecycle, the two tiers, the quote engine, and what SyMon AI refuses.

Task #106.

Every test here runs against a throwaway store via `SYMONEURAL_DISPATCHOS_DB`, so a run
never touches `run/dispatchos.db`. The surface is switched on per-test through
`SYMONEURAL_DISPATCHOS_ENABLED`, and one test deliberately leaves it off to prove the
fail-closed path.

**The tests that matter most are the negative ones.** A dispatch board that shows jobs is
easy; the things that would actually cost something are a customer seeing another
customer's trip, a quote inventing a price on a page that promises there is none, a
reminder that claims to have been sent, and SyMon AI starting a 7B on a contended card in
front of a customer. Those are the four this file is built around.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("SYMONEURAL_DISPATCHOS_DB", "")

from fastapi import FastAPI                                    # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402

import dispatchos                                    # noqa: E402
import accounts as shared_accounts                   # noqa: E402
from dispatchos.lib import ai, quotes, store                  # noqa: E402

PW = "a-long-enough-password"

#: Test-only session secret. Never a production secret, never written to configuration.
#: The shared accounts store refuses to operate without one, and these suites now need it
#: because A-3 routes their entitlement lookup through that store. Supplying it in-process
#: does NOT enable the surface on the box -- enablement additionally needs its own flag,
#: which nothing here sets.
SHARED_SECRET = "test-secret-not-the-production-one-0123456789abcdef"

#: The application slug the entitlement seam looks up.
APP_SLUG = "dispatchos"


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SYMONEURAL_DISPATCHOS_DB"] = str(pathlib.Path(self._tmp.name) / "d.db")
        os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "1"
        store.init_db()
        store.seed_demo_users({"garrett": PW, "ben": PW,
                               "garrett-rider": PW, "ben-rider": PW})
        self._provision_entitlement()
        app = FastAPI()
        app.include_router(dispatchos.router, prefix="/api/dispatchos")
        app.include_router(dispatchos.ui_router)
        self.app = app
        self.c = TestClient(app)
        ai.set_ask_model(None)

    def _provision_entitlement(self) -> None:
        """Give every seeded user a shared identity and an active grant.

        A-3 put four routes behind ENTITLEMENT_REQUIRED, so a caller with a valid session
        but no entitlement now gets 403. These suites predate entitlement and provisioned
        none, which is why seventeen of them failed: the 403 was correct and the fixture was
        stale.

        The entitlement is REAL, not mocked. Nothing here weakens, bypasses or removes the
        class -- the seam runs end to end against a throwaway shared store, so the tests
        still exercise the authorization path they always did plus the new one. Proving the
        deny side is `test_route_authorization.py`'s job (T3, T15, T18), and that suite is
        deliberately left alone.

        Everything is temporary and process-local: a temp database and a test secret, both
        removed in tearDown. No customer is provisioned and the surface stays off.
        """
        os.environ["SYMONEURAL_ACCOUNTS_DB"] = str(
            pathlib.Path(self._tmp.name) / "shared-accounts.db")
        os.environ["SYMONEURAL_SESSION_SECRET"] = SHARED_SECRET
        # Deliberately NOT importlib.reload(shared_accounts). `store` binds WeakPassword,
        # hash_password and validate_password from that module at import time, so reloading
        # it replaces the class objects and leaves store raising a WeakPassword that a later
        # suite's `assertRaises` no longer recognises. That is a real leak: it made two tests
        # in a different file fail only when this file ran first. The reload is also
        # unnecessary -- the store resolves its database path per connection from the
        # environment, so setting the variable above is enough.
        shared_accounts.init_db()

        for username in ("garrett", "ben", "garrett-rider", "ben-rider"):
            account = shared_accounts.create_account(f"{username}@fixture.invalid", PW)
            store.link_shared_account(username, account["id"])
            shared_accounts.grant_entitlement(account["id"], APP_SLUG,
                                              granted_by="test-fixture")

    def tearDown(self):
        ai.set_ask_model(None)
        self._tmp.cleanup()
        os.environ.pop("SYMONEURAL_DISPATCHOS_ENABLED", None)
        os.environ.pop("SYMONEURAL_ACCOUNTS_DB", None)
        os.environ.pop("SYMONEURAL_SESSION_SECRET", None)

    def login(self, who, pw=PW):
        c = TestClient(self.app)
        r = c.post("/api/dispatchos/login", json={"username": who, "password": pw})
        self.assertEqual(r.status_code, 200, r.text)
        return c


# ------------------------------------------------------------------ the four logins

class LoginTests(Base):

    def test_the_four_accounts_exist_at_two_tiers(self):
        """Garrett's acceptance test, asserted: two people, two tiers, four logins."""
        users = {u["username"]: u["role"] for u in store.list_users()}
        self.assertEqual(users, {
            "garrett": "operator", "ben": "operator",
            "garrett-rider": "customer", "ben-rider": "customer"})

    def test_each_of_the_four_can_actually_sign_in(self):
        for who in ("garrett", "ben", "garrett-rider", "ben-rider"):
            with self.subTest(who=who):
                r = self.c.post("/api/dispatchos/login",
                                json={"username": who, "password": PW})
                self.assertEqual(r.status_code, 200, f"{who} could not sign in: {r.text}")
                self.assertEqual(r.json()["user"]["username"], who)

    def test_wrong_password_and_unknown_user_give_the_same_answer(self):
        a = self.c.post("/api/dispatchos/login",
                        json={"username": "garrett", "password": "wrong-password-here"})
        b = self.c.post("/api/dispatchos/login",
                        json={"username": "nobody", "password": "wrong-password-here"})
        self.assertEqual(a.status_code, 401)
        self.assertEqual(b.status_code, 401)
        self.assertEqual(a.json()["detail"], b.json()["detail"],
                         "a different answer for an unknown user is a username oracle")

    def test_no_password_is_defaulted(self):
        """`seed_demo_users` must never invent a password.

        A default credential in a repository is a live credential the moment somebody
        deploys without reading the file.
        """
        store.init_db()
        made = store.seed_demo_users({})       # no passwords offered
        self.assertEqual(made, [])

    def test_signed_out_is_401_not_a_board(self):
        self.assertEqual(self.c.get("/api/dispatchos/board").status_code, 401)

    def test_switched_off_is_503(self):
        os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "0"
        r = self.c.get("/api/dispatchos/board")
        self.assertEqual(r.status_code, 503)


# ------------------------------------------------------------------ the two tiers

class RoleTests(Base):

    def test_a_customer_sees_only_their_own_trips(self):
        g = self.login("garrett-rider")
        b = self.login("ben-rider")
        g.post("/api/dispatchos/bookings",
               json={"pickup": "A", "dropoff": "B", "when_text": "soon"})
        seen_by_ben = b.get("/api/dispatchos/board").json()["bookings"]
        self.assertEqual(seen_by_ben, [],
                         "a customer can see another customer's trip -- that is the leak")
        seen_by_garrett = g.get("/api/dispatchos/board").json()["bookings"]
        self.assertEqual(len(seen_by_garrett), 1)

    def test_an_operator_sees_every_trip(self):
        self.login("garrett-rider").post(
            "/api/dispatchos/bookings", json={"pickup": "A", "dropoff": "B"})
        self.login("ben-rider").post(
            "/api/dispatchos/bookings", json={"pickup": "C", "dropoff": "D"})
        board = self.login("garrett").get("/api/dispatchos/board").json()
        self.assertEqual(len(board["bookings"]), 2)

    def test_a_customer_cannot_quote_dispatch_or_set_rates(self):
        cust = self.login("garrett-rider")
        bid = cust.post("/api/dispatchos/bookings",
                        json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        for method, path, body in (
                ("post", f"/api/dispatchos/bookings/{bid}/quote", {}),
                ("post", f"/api/dispatchos/bookings/{bid}/advance", {"to": "confirmed"}),
                ("post", f"/api/dispatchos/bookings/{bid}/message", {"kind": "reminder"}),
                ("put", "/api/dispatchos/rules", {"rules": {"base": 500}}),
                ("post", "/api/dispatchos/drivers", {"name": "someone"})):
            with self.subTest(path=path):
                r = getattr(cust, method)(path, json=body)
                self.assertEqual(r.status_code, 403, f"{path} let a customer through")

    def test_a_customer_cannot_read_another_customers_booking_by_id(self):
        bid = self.login("garrett-rider").post(
            "/api/dispatchos/bookings", json={"pickup": "A", "dropoff": "B"}
        ).json()["booking"]["id"]
        r = self.login("ben-rider").get(f"/api/dispatchos/bookings/{bid}")
        self.assertEqual(r.status_code, 403)


# ------------------------------------------------------------------ the lifecycle

class LifecycleTests(Base):

    def test_a_booking_walks_the_six_panels_of_the_preview(self):
        op = self.login("garrett")
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "Riverside Ave", "dropoff": "Regional airport",
                            "when_text": "Tuesday, 9:40 am", "passengers": 2,
                            "luggage": 2}).json()["booking"]["id"]
        self.assertEqual(store.get_booking(bid)["state"], "requested")
        op.post(f"/api/dispatchos/bookings/{bid}/quote", json={})
        self.assertEqual(store.get_booking(bid)["state"], "quoted")
        for to in ("confirmed", "dispatched", "completed", "reviewed"):
            r = op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": to})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(store.get_booking(bid)["state"], to)

    def test_out_of_order_transitions_are_refused(self):
        op = self.login("garrett")
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        # requested -> dispatched skips quote and confirm.
        r = op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": "dispatched"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(store.get_booking(bid)["state"], "requested")

    def test_a_finished_booking_cannot_be_moved_again(self):
        op = self.login("garrett")
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        op.post(f"/api/dispatchos/bookings/{bid}/quote", json={})
        for to in ("confirmed", "dispatched", "completed", "reviewed"):
            op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": to})
        r = op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": "completed"})
        self.assertEqual(r.status_code, 400)

    def test_pickup_and_dropoff_are_required(self):
        r = self.login("garrett").post("/api/dispatchos/bookings",
                                       json={"pickup": "", "dropoff": "B"})
        self.assertEqual(r.status_code, 400)

    def test_the_record_trail_is_append_only_and_records_every_step(self):
        op = self.login("garrett")
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        op.post(f"/api/dispatchos/bookings/{bid}/quote", json={})
        op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": "confirmed"})
        kinds = [e["kind"] for e in store.get_booking(bid)["events"]]
        self.assertEqual(kinds, ["requested", "quoted", "confirmed"])
        ats = [e["at"] for e in store.get_booking(bid)["events"]]
        self.assertEqual(ats, sorted(ats))


# ------------------------------------------------------------------ messages are never sent

class MessageTests(Base):

    def test_a_composed_message_is_never_marked_sent(self):
        """The preview tells the customer no live email is claimed. This is that promise."""
        op = self.login("garrett")
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        op.post(f"/api/dispatchos/bookings/{bid}/quote", json={})
        op.post(f"/api/dispatchos/bookings/{bid}/advance", json={"to": "confirmed"})
        r = op.post(f"/api/dispatchos/bookings/{bid}/message", json={"kind": "reminder"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["message"]["sent_at"])
        self.assertIn("not sent", r.json()["delivery"])
        for m in store.get_booking(bid)["messages"]:
            self.assertIsNone(m["sent_at"])

    def test_there_is_no_mail_sender_anywhere_in_the_package(self):
        """Structural, not behavioural: grep the package for a way to send.

        A test that only checks `sent_at is None` passes just as happily on a package that
        posts to an SMTP server and forgets to write the column.
        """
        pkg = pathlib.Path(dispatchos.__file__).parent
        banned = ("smtplib", "sendmail", "aiosmtp", "sendgrid", "mailgun", "ses.send_email")
        for f in pkg.glob("*.py"):
            body = f.read_text(encoding="utf-8")
            for word in banned:
                self.assertNotIn(word, body,
                                 f"{f.name} can send mail ({word}); the preview promises it cannot")


# ------------------------------------------------------------------ the quote engine

class QuoteTests(Base):

    def test_no_rules_means_no_figure_and_the_preview_s_own_dash(self):
        q = quotes.quote({"pickup": "A", "dropoff": "B", "passengers": 2, "luggage": 2})
        self.assertIsNone(q["estimate"])
        self.assertEqual(q["display"], "——")
        self.assertIn("not configured", q["basis"])

    def test_the_package_ships_no_rate_anywhere(self):
        """There must be no default tariff hiding in the code.

        `configured()` is the gate, so the assertion is that a *fresh* store produces no
        figure -- not that a particular constant is absent, which a rename would defeat.
        """
        self.assertFalse(quotes.configured(store.get_setting("rules")))
        self.assertFalse(quotes.configured({}))
        self.assertFalse(quotes.configured({"currency": "GBP", "surcharges": []}))
        self.assertFalse(quotes.configured(None))

    def test_the_same_trip_quotes_the_same_twice(self):
        """The preview's actual promise: "the same trip does not get two different answers
        on two different days"."""
        rules = {"currency": "GBP", "base": 250, "per_km": 120, "minimum": 500,
                 "surcharges": [{"when": "luggage_over", "value": 2, "add": 150}]}
        trip = {"pickup": "A", "dropoff": "B", "passengers": 2, "luggage": 3}
        a = quotes.quote(trip, rules, distance_km=12.5)
        b = quotes.quote(trip, rules, distance_km=12.5)
        self.assertEqual(a, b)

    def test_distance_is_never_invented(self):
        rules = {"base": 250, "per_km": 120}
        q = quotes.quote({"pickup": "A", "dropoff": "B"}, rules)
        self.assertEqual(q["estimate"], 250, "a distance charge appeared with no distance")
        self.assertTrue(any("not estimated" in (l.get("note") or "") for l in q["lines"]))

    def test_minimum_fare_and_surcharges_apply(self):
        rules = {"currency": "GBP", "base": 100, "minimum": 800,
                 "surcharges": [{"when": "passengers_over", "value": 4, "add": 400}]}
        q = quotes.quote({"pickup": "A", "dropoff": "B", "passengers": 6}, rules)
        self.assertEqual(q["estimate"], 800)
        self.assertIn("minimum", q["basis"])

    def test_money_is_integer_minor_units(self):
        self.assertEqual(quotes.money(1234, "GBP"), "12.34 GBP")
        self.assertEqual(quotes.money(5, ""), "0.05")

    def test_bad_rules_are_refused_rather_than_coerced(self):
        for bad in ({"base": -1}, {"base": 1.5}, {"currency": "POUNDS"},
                    {"surcharges": [{"when": "phase_of_moon", "value": 1, "add": 1}]}):
            with self.subTest(bad=bad):
                with self.assertRaises(quotes.RulesError):
                    quotes.validate_rules(bad)

    def test_an_operator_can_configure_rates_and_then_a_quote_has_a_figure(self):
        op = self.login("garrett")
        r = op.put("/api/dispatchos/rules",
                   json={"rules": {"currency": "GBP", "base": 500, "minimum": 500}})
        self.assertEqual(r.status_code, 200, r.text)
        bid = op.post("/api/dispatchos/bookings",
                      json={"pickup": "A", "dropoff": "B"}).json()["booking"]["id"]
        b = op.post(f"/api/dispatchos/bookings/{bid}/quote", json={}).json()["booking"]
        self.assertEqual(b["quote"]["display"], "5.00 GBP")


# ------------------------------------------------------------------ SyMon AI

class AiTests(Base):

    def test_with_no_model_wired_the_answer_is_labelled_local(self):
        op = self.login("garrett")
        op.post("/api/dispatchos/bookings", json={"pickup": "A", "dropoff": "B"})
        out = op.post("/api/dispatchos/ask", json={"question": "how many jobs?"}).json()
        self.assertFalse(out["model"], "an answer with no model must not claim to be one")
        self.assertIn("reason", out)

    def test_a_wired_model_answers_and_is_labelled_as_the_model(self):
        ai.set_ask_model(lambda prompt: "The next job is the airport run.")
        op = self.login("garrett")
        op.post("/api/dispatchos/bookings", json={"pickup": "A", "dropoff": "B"})
        out = op.post("/api/dispatchos/ask", json={"question": "what next?"}).json()
        self.assertTrue(out["model"])
        self.assertEqual(out["answer"], "The next job is the airport run.")

    def test_the_board_is_actually_in_the_prompt(self):
        """Otherwise it is a generic chatbot, which is precisely what the preview says it
        is not."""
        seen = {}

        def spy(prompt):
            seen["p"] = prompt
            return "ok"

        ai.set_ask_model(spy)
        op = self.login("garrett")
        op.post("/api/dispatchos/bookings",
                json={"pickup": "Riverside Ave", "dropoff": "Regional airport"})
        op.post("/api/dispatchos/ask", json={"question": "what next?"})
        self.assertIn("Riverside Ave", seen["p"])
        self.assertIn("Regional airport", seen["p"])

    def test_contact_details_never_reach_the_prompt(self):
        seen = {}
        ai.set_ask_model(lambda p: seen.setdefault("p", p) and "ok" or "ok")
        op = self.login("garrett")
        op.post("/api/dispatchos/bookings",
                json={"pickup": "A", "dropoff": "B", "rider": "Sample Rider",
                      "contact": "07700-900123"})
        op.post("/api/dispatchos/ask", json={"question": "anything"})
        self.assertNotIn("07700-900123", seen["p"],
                         "a rider's phone number went into a model prompt")

    def test_a_failing_model_never_leaks_its_message_to_the_surface(self):
        """Copied from guide_ask_model: the real error can name a socket path."""
        def boom(prompt):
            raise RuntimeError("connect /run/symoneural/llama-9001.sock failed")

        ai.set_ask_model(boom)
        op = self.login("garrett")
        out = op.post("/api/dispatchos/ask", json={"question": "hello"}).json()
        self.assertFalse(out["model"])
        blob = (out.get("answer", "") + " " + out.get("reason", ""))
        self.assertNotIn("llama-9001.sock", blob)
        self.assertNotIn("/run/symoneural", blob)
        self.assertIn("RuntimeError", blob, "the exception class is the only detail kept")

    def test_the_ask_route_does_not_block_the_event_loop(self):
        """The deadlock the end-to-end smoke run found, and the unit tests could not.

        The real injected callable is `guide_ask_model`, which does
        `asyncio.run_coroutine_threadsafe(...).result(timeout=45)` -- it schedules work on the
        API's event loop and then BLOCKS waiting for it. Called directly from inside an
        `async def` route, the loop is blocked by the very call that needs it to make
        progress, so nothing runs until the 45-second timeout expires and every other request
        on the box queues behind it. Live, that wedged /api/dispatchos/ask for 30+ seconds.

        Every other test here injects a plain synchronous stub, which cannot reproduce this:
        a stub that just returns a string is perfectly happy on a blocked loop. So this stub
        **This assertion is structural, and the reason is worth stating rather than hiding.**
        The obvious behavioural version -- inject a stub that itself waits on the running
        loop, and watch it hang -- cannot be written against `TestClient`: it drives the app
        through an anyio portal that stands up and tears down a loop around requests, so a
        `run_coroutine_threadsafe` handle from one request is already dead in the next. The
        test fails for that reason rather than for the reason it claims to test, which is
        worse than not having it. Reproducing it honestly needs a real server on a real port
        with a long-lived loop.

        So: this checks the one line that matters is present, and the REAL proof lives in
        `SMOKE.md`, which records the live round trip against the running API -- the run that
        found the bug in the first place.
        """
        src = pathlib.Path(dispatchos.router.__file__).read_text(encoding="utf-8")
        self.assertRegex(
            src, r"await\s+asyncio\.to_thread\(\s*ai\.ask",
            "the /ask route calls ai.ask directly again. The injected callable is "
            "guide_ask_model, which blocks waiting on THIS event loop -- calling it from "
            "inside the coroutine deadlocks the whole API until its 45s timeout.")
        self.assertIn("import asyncio", src)

    def test_the_module_cannot_start_a_model(self):
        """Structural. The rule is `guide_ask_model`'s: it never starts the model."""
        src = pathlib.Path(ai.__file__).read_text(encoding="utf-8")
        for word in ("subprocess", "Popen", "gpu-governor", "llama-server", "socket"):
            self.assertNotIn(word + "(", src)
        self.assertNotIn("import subprocess", src)

    def test_the_prompt_is_bounded_by_job_count(self):
        op = self.login("garrett")
        for i in range(20):
            op.post("/api/dispatchos/bookings",
                    json={"pickup": f"P{i}", "dropoff": f"D{i}"})
        seen = {}
        ai.set_ask_model(lambda p: seen.setdefault("p", p) and "ok" or "ok")
        op.post("/api/dispatchos/ask", json={"question": "anything"})
        self.assertIn("further jobs not listed", seen["p"])
        self.assertLess(seen["p"].count("\n- "), 15)


# ------------------------------------------------------------------ scope boundaries

class ScopeTests(Base):

    def test_the_deferred_column_was_not_quietly_built(self):
        """The preview promises Donnie these are deliberate omissions.

        Asserted against the schema rather than the UI: a revenue column with no page is
        still the thing the document says does not exist.
        """
        import sqlite3
        con = sqlite3.connect(store.db_path())
        sql = " ".join(r[0] or "" for r in
                       con.execute("SELECT sql FROM sqlite_master").fetchall()).lower()
        con.close()
        for word in ("revenue", "invoice", "payment", "billing", "card", "tariff"):
            self.assertNotIn(word, sql,
                             f"the schema has {word!r}, which the preview lists as deferred")

    def test_the_page_shows_the_previews_own_dash_not_a_zero(self):
        html = self.c.get("/demo/dispatchos").text
        self.assertIn("——", html)
        self.assertNotIn("0.00", html)

    def test_the_page_does_not_load_the_maintenance_banner(self):
        """#107's banner must never reach the customer surface."""
        html = self.c.get("/demo/dispatchos").text
        self.assertNotIn("ui.js", html)
        self.assertNotIn("maint", html)

    def test_the_page_is_noindex(self):
        html = self.c.get("/demo/dispatchos").text
        self.assertIn("noindex", html)


class StatusTests(Base):

    def test_the_row_validates_against_the_real_Unit_model(self):
        """This test exists because its absence took /api/status down.

        The first version of `status()` returned `"sub": "transport dispatch"`. `Unit.sub` is
        `list[SubUnit] | None`, so pydantic raised on every call to `build_status()` -- and
        `build_status()` is what the rack websocket and every visitor's status poll run. The
        surface itself was fine; the ROW killed the page.

        Asserting on `status()["state"]` could never have caught it, because the state was
        correct. The only thing that catches a shape error is constructing the real model, so
        that is what this does -- importing `Unit` from `api` rather than restating its fields
        here, since a local copy of the schema would drift and pass while production failed.
        """
        import importlib
        api = importlib.import_module("api")
        for want in ("1", "0"):
            os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = want
            with self.subTest(enabled=want):
                # Raises pydantic.ValidationError on any wrong key, type or literal.
                unit = api.Unit(**dispatchos.status())
                self.assertEqual(unit.id, "dispatchos")
                self.assertIn(unit.state, ("ready", "busy", "queued", "offline"))
                self.assertEqual(unit.bus, "cpu")

    def test_the_rack_row_reads_its_switch(self):
        os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "1"
        self.assertEqual(dispatchos.status()["state"], "ready")
        os.environ["SYMONEURAL_DISPATCHOS_ENABLED"] = "0"
        self.assertEqual(dispatchos.status()["state"], "offline")
        self.assertIn("SYMONEURAL_DISPATCHOS_ENABLED", dispatchos.status()["detail"])


if __name__ == "__main__":
    unittest.main()
