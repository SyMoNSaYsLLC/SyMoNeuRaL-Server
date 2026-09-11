"""Tests for the programme guide. No network, no panel, no credentials.

A local HTTP server plays the panel, exactly as `test_streamer.py` does, because the thing under
test is a protocol client and mocking `safefetch.fetch` would test the mock. `Policy(
allow_private=True)` is the only reason a loopback fetch is permitted, and it is a constructor
argument by design -- see `safefetch.Policy`.

Every test here exists because of a way a guide can be confidently wrong rather than absent: a
time in the wrong zone, a base64 title decoded when it should not have been, a "now" plucked from
whichever row came first. A guide that renders the wrong programme is worse than an empty one.
"""
from __future__ import annotations

import base64
import json
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from streamer.lib import epg
from .lib.safefetch import Policy
from .lib.xtream import XtreamCreds

B64 = lambda s: base64.b64encode(s.encode()).decode()          # noqa: E731 - readability here

#: 2026-08-17 12:00:00 UTC. A fixed clock, so every assertion about now/next is arithmetic
#: rather than a race against the wall.
T0 = 1786968000


class _Panel(BaseHTTPRequestHandler):
    """A scripted Xtream panel. `CASE` selects the shape of the reply."""
    CASE = "normal"
    HITS: list[str] = []

    def log_message(self, *a):                                  # silence
        pass

    def do_GET(self):                                            # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        _Panel.HITS.append(self.path)
        if self.path.startswith("/xmltv.php"):
            return self._xmltv()
        action = (q.get("action") or [""])[0]
        if action != "get_short_epg":
            return self._send(404, b"{}")
        sid = (q.get("stream_id") or [""])[0]
        c = _Panel.CASE
        if c == "empty":
            return self._json({"epg_listings": []})
        if c == "missing_key":
            return self._json({})
        if c == "not_json":
            return self._send(200, b"<html>login failed for user u pass p</html>")
        if c == "plain_titles":
            return self._json({"epg_listings": [
                {"title": "News", "description": "Headlines",
                 "start_timestamp": str(T0 - 600), "stop_timestamp": str(T0 + 1800)}]})
        if c == "no_clock":
            return self._json({"epg_listings": [
                {"title": B64("Undateable"), "description": "",
                 "start": "2026-08-17 12:00:00", "end": "2026-08-17 13:00:00"},
                {"title": B64("Datable"), "description": "",
                 "start_timestamp": str(T0), "stop_timestamp": str(T0 + 3600)}]})
        if c == "unordered":
            return self._json({"epg_listings": [
                {"title": B64("Third"), "start_timestamp": str(T0 + 7200),
                 "stop_timestamp": str(T0 + 10800), "description": ""},
                {"title": B64("First"), "start_timestamp": str(T0 - 1800),
                 "stop_timestamp": str(T0 + 1800), "description": ""},
                {"title": B64("Second"), "start_timestamp": str(T0 + 1800),
                 "stop_timestamp": str(T0 + 7200), "description": ""}]})
        if c == "millis":
            return self._json({"epg_listings": [
                {"title": B64("Millisecond Panel"), "description": "",
                 "start_timestamp": str((T0 - 600) * 1000),
                 "stop_timestamp": str((T0 + 1800) * 1000)}]})
        if c == "reversed":
            return self._json({"epg_listings": [
                {"title": B64("Backwards"), "description": "",
                 "start_timestamp": str(T0 + 1800), "stop_timestamp": str(T0 - 1800)}]})
        if c == "gap":
            # Now, then a hole, then something much later. `next` must be the later one, and
            # `programmes[1]` is not a safe answer in general.
            return self._json({"epg_listings": [
                {"title": B64("On Now"), "start_timestamp": str(T0 - 600),
                 "stop_timestamp": str(T0 + 600), "description": ""},
                {"title": B64("After The Gap"), "start_timestamp": str(T0 + 9000),
                 "stop_timestamp": str(T0 + 12600), "description": ""}]})
        # normal: one running, one following, with base64 text and an id echoed back
        return self._json({"epg_listings": [
            {"title": B64(f"Now on {sid}"), "description": B64("A description"),
             "start_timestamp": str(T0 - 900), "stop_timestamp": str(T0 + 900)},
            {"title": B64("Coming Up"), "description": B64(""),
             "start_timestamp": str(T0 + 900), "stop_timestamp": str(T0 + 4500)}]})

    def _xmltv(self):
        c = _Panel.CASE
        if c == "xmltv_no_offset":
            body = ('<?xml version="1.0"?><tv>'
                    '<programme start="20260817120000" stop="20260817130000" channel="a.tv">'
                    '<title>No Offset</title></programme></tv>')
        elif c == "xmltv_truncated":
            body = ('<?xml version="1.0"?><tv>'
                    '<programme start="20260817120000 +0000" stop="20260817130000 +0000" '
                    'channel="a.tv"><title>Kept</title><desc>Body</desc></programme>'
                    '<programme start="20260817130000 +0000" stop="2026081714')
        elif c == "xmltv_junk":
            body = "not xml at all"
        else:
            body = ('<?xml version="1.0"?><tv>'
                    '<programme start="20260817120000 +0000" stop="20260817130000 +0000" '
                    'channel="a.tv"><title>UTC Noon</title><desc>D1</desc></programme>'
                    '<programme start="20260817140000 +0200" stop="20260817150000 +0200" '
                    'channel="b.tv"><title>Berlin Two</title></programme>'
                    '<programme start="20260817130000 +0000" stop="20260817140000 +0000" '
                    'channel="a.tv"><title>UTC One</title></programme>'
                    '<programme start="20260817150000 +0000" stop="20260817160000 +0000" '
                    'channel="c.tv"><title>Unwanted</title></programme></tv>')
        return self._send(200, body.encode())

    def _json(self, obj):
        return self._send(200, json.dumps(obj).encode())

    def _send(self, code, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class EpgTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Panel)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.creds = XtreamCreds(server=f"http://127.0.0.1:{cls.port}",
                                username="u", password="p")
        cls.policy = Policy(allow_private=True)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        _Panel.CASE = "normal"
        _Panel.HITS = []

    def case(self, name):
        _Panel.CASE = name


class TestShortEpg(EpgTestBase):
    def test_a_normal_channel_comes_back_decoded_and_on_the_clock(self):
        progs, dropped = epg.short_epg(self.creds, "7", 4, self.policy)
        self.assertEqual(dropped, 0)
        self.assertEqual([p.title for p in progs], ["Now on 7", "Coming Up"])
        self.assertEqual(progs[0].desc, "A description")
        self.assertEqual(progs[0].start, T0 - 900)
        self.assertEqual(progs[0].seconds, 1800)

    def test_the_stream_id_and_limit_actually_reach_the_panel(self):
        epg.short_epg(self.creds, "42", 3, self.policy)
        hit = _Panel.HITS[-1]
        self.assertIn("stream_id=42", hit)
        self.assertIn("limit=3", hit)

    def test_limit_is_clamped_not_trusted(self):
        epg.short_epg(self.creds, "1", 9999, self.policy)
        self.assertIn(f"limit={epg.MAX_LIMIT}", _Panel.HITS[-1])
        epg.short_epg(self.creds, "1", 0, self.policy)
        self.assertIn(f"limit={epg.DEFAULT_LIMIT}", _Panel.HITS[-1])

    def test_a_channel_with_no_guide_is_empty_not_invented(self):
        for case in ("empty", "missing_key"):
            with self.subTest(case=case):
                self.case(case)
                progs, dropped = epg.short_epg(self.creds, "1", 4, self.policy)
                self.assertEqual(progs, [])
                self.assertEqual(dropped, 0)

    def test_a_plain_text_title_is_not_mangled_by_a_base64_decoder(self):
        """"News" is valid base64. Insisting on the documented encoding corrupts it."""
        self.case("plain_titles")
        progs, _ = epg.short_epg(self.creds, "1", 4, self.policy)
        self.assertEqual([p.title for p in progs], ["News"])
        self.assertEqual(progs[0].desc, "Headlines")

    def test_a_row_with_no_usable_timestamps_is_dropped_and_counted(self):
        self.case("no_clock")
        progs, dropped = epg.short_epg(self.creds, "1", 4, self.policy)
        self.assertEqual([p.title for p in progs], ["Datable"])
        self.assertEqual(dropped, 1, "the undateable row must be reported, not silently lost")

    def test_rows_are_sorted_by_start_whatever_order_the_panel_used(self):
        self.case("unordered")
        progs, _ = epg.short_epg(self.creds, "1", 4, self.policy)
        self.assertEqual([p.title for p in progs], ["First", "Second", "Third"])

    def test_a_millisecond_timestamp_is_converted_not_rejected(self):
        self.case("millis")
        progs, dropped = epg.short_epg(self.creds, "1", 4, self.policy)
        self.assertEqual(dropped, 0)
        self.assertEqual(progs[0].start, T0 - 600)

    def test_a_backwards_row_is_repaired_rather_than_emitted_as_negative(self):
        self.case("reversed")
        progs, _ = epg.short_epg(self.creds, "1", 4, self.policy)
        self.assertEqual(progs[0].start, T0 - 1800)
        self.assertEqual(progs[0].stop, T0 + 1800)
        self.assertGreaterEqual(progs[0].seconds, 0)

    def test_an_html_error_page_never_leaks_the_credential_it_echoed(self):
        self.case("not_json")
        with self.assertRaises(epg.EpgError) as ctx:
            epg.short_epg(self.creds, "1", 4, self.policy)
        msg = str(ctx.exception)
        self.assertNotIn("pass p", msg)
        self.assertNotIn("user u", msg)

    def test_an_empty_stream_id_is_refused_before_a_request_is_made(self):
        with self.assertRaises(epg.EpgError):
            epg.short_epg(self.creds, "   ", 4, self.policy)
        self.assertEqual(_Panel.HITS, [], "nothing should have been asked of the panel")


class TestNowNext(EpgTestBase):
    def test_now_is_the_running_programme_and_next_is_what_follows_it(self):
        progs, _ = epg.short_epg(self.creds, "7", 4, self.policy)
        nn = epg.now_next(progs, at=T0)
        self.assertEqual(nn["now"]["title"], "Now on 7")
        self.assertEqual(nn["next"]["title"], "Coming Up")

    def test_next_skips_a_gap_instead_of_taking_the_second_row(self):
        self.case("gap")
        progs, _ = epg.short_epg(self.creds, "1", 4, self.policy)
        nn = epg.now_next(progs, at=T0)
        self.assertEqual(nn["now"]["title"], "On Now")
        self.assertEqual(nn["next"]["title"], "After The Gap")

    def test_a_time_outside_every_window_reports_no_now_at_all(self):
        progs, _ = epg.short_epg(self.creds, "7", 4, self.policy)
        nn = epg.now_next(progs, at=T0 - 86400)
        self.assertIsNone(nn["now"], "a cell with no data must not borrow the first row")
        self.assertEqual(nn["next"]["title"], "Now on 7")

    def test_progress_is_a_fraction_of_the_programme_actually_running(self):
        progs, _ = epg.short_epg(self.creds, "7", 4, self.policy)
        nn = epg.now_next(progs, at=T0)          # 900 s into an 1800 s programme
        self.assertAlmostEqual(nn["progress"], 0.5, places=3)

    def test_progress_is_absent_when_nothing_is_running(self):
        nn = epg.now_next([], at=T0)
        self.assertNotIn("progress", nn)
        self.assertIsNone(nn["now"])
        self.assertIsNone(nn["next"])


class TestXmltv(EpgTestBase):
    def test_the_document_is_keyed_by_the_channel_id_the_rows_carry(self):
        guide, meta = epg.xmltv_epg(self.creds, self.policy)
        self.assertEqual(set(guide), {"a.tv", "b.tv", "c.tv"})
        self.assertEqual(meta["channels"], 3)
        self.assertEqual(meta["programmes_seen"], 4)
        self.assertEqual(meta["programmes_kept"], 4)
        self.assertFalse(meta["truncated"])

    def test_an_offset_is_applied_rather_than_ignored(self):
        """14:00 +0200 is 12:00 UTC. Dropping the offset renders the guide two hours out."""
        guide, _ = epg.xmltv_epg(self.creds, self.policy)
        self.assertEqual(guide["b.tv"][0].start, 1786968000)
        self.assertEqual(guide["a.tv"][0].start, 1786968000)

    def test_rows_per_channel_are_sorted(self):
        guide, _ = epg.xmltv_epg(self.creds, self.policy)
        self.assertEqual([p.title for p in guide["a.tv"]], ["UTC Noon", "UTC One"])

    def test_a_wanted_set_filters_during_the_parse(self):
        guide, meta = epg.xmltv_epg(self.creds, self.policy, wanted={"a.tv"})
        self.assertEqual(set(guide), {"a.tv"})
        self.assertEqual(meta["programmes_seen"], 4, "it still saw them all")
        self.assertEqual(meta["programmes_kept"], 2, "and kept only what was asked for")

    def test_a_per_channel_cap_is_reported_not_silent(self):
        guide, meta = epg.xmltv_epg(self.creds, self.policy, max_per_channel=1)
        self.assertEqual(len(guide["a.tv"]), 1)
        self.assertEqual(meta["dropped_over_cap"], 1)

    def test_a_timestamp_with_no_offset_is_refused_rather_than_assumed_local(self):
        """The row is dropped and counted -- it is not placed on the clock by guesswork.

        The first version of this test expected an exception. That was the wrong shape: the
        document IS valid XMLTV, so failing the whole request would throw away every other
        channel over one provider's sloppy row. What must not happen is the row being kept at
        the server's local time, and what must not happen either is the channel appearing with
        an empty list, which would read as "this channel has no programmes on".
        """
        self.case("xmltv_no_offset")
        guide, meta = epg.xmltv_epg(self.creds, self.policy)
        self.assertEqual(guide, {})
        self.assertEqual(meta["programmes_seen"], 1)
        self.assertEqual(meta["programmes_kept"], 0)
        self.assertEqual(meta["dropped_no_clock"], 1)

    def test_a_truncated_document_keeps_what_parsed_and_says_it_was_cut(self):
        self.case("xmltv_truncated")
        guide, meta = epg.xmltv_epg(self.creds, self.policy)
        self.assertEqual([p.title for p in guide["a.tv"]], ["Kept"])
        self.assertTrue(meta["truncated"], "a cut document must not look complete")

    def test_a_document_that_is_not_xml_at_all_is_an_error(self):
        self.case("xmltv_junk")
        with self.assertRaises(epg.EpgError):
            epg.xmltv_epg(self.creds, self.policy)

    def test_the_credential_is_in_the_query_this_time_and_that_is_the_protocol(self):
        """`xmltv.php` has no other form of authentication. Assert it is at least URL-encoded.

        This is the one place the password legitimately reaches a query string, and it is an
        OUTBOUND request to the visitor's own provider -- not a route this box serves, which is
        what the rule in `routes.py` is about. Kept as a test so the distinction stays deliberate.
        """
        epg.xmltv_epg(self.creds, self.policy)
        hit = _Panel.HITS[-1]
        self.assertTrue(hit.startswith("/xmltv.php?"))
        self.assertIn("username=u", hit)
        self.assertIn("password=p", hit)


class TestDecoding(unittest.TestCase):
    """`_maybe_b64` and `_epoch` in isolation: the two places a guide goes quietly wrong."""

    def test_base64_of_real_text_is_decoded(self):
        self.assertEqual(epg._maybe_b64(B64("Match of the Day")), "Match of the Day")

    def test_text_with_a_space_is_never_treated_as_base64(self):
        self.assertEqual(epg._maybe_b64("Match of the Day"), "Match of the Day")

    def test_a_length_that_cannot_be_base64_is_left_alone(self):
        self.assertEqual(epg._maybe_b64("News1"), "News1")

    def test_base64_that_decodes_to_binary_is_left_as_the_original(self):
        self.assertEqual(epg._maybe_b64("News"), "News")

    def test_empty_and_none_are_empty(self):
        self.assertEqual(epg._maybe_b64(None), "")
        self.assertEqual(epg._maybe_b64(""), "")

    def test_epoch_accepts_the_three_shapes_panels_actually_send(self):
        self.assertEqual(epg._epoch("1786968000"), 1786968000)
        self.assertEqual(epg._epoch(1786968000), 1786968000)
        self.assertEqual(epg._epoch("1786968000.0"), 1786968000)

    def test_epoch_rejects_what_is_not_a_time(self):
        for v in (None, "", "   ", "not a time", 0, -5, True, False):
            with self.subTest(v=v):
                self.assertIsNone(epg._epoch(v))

    def test_xmltv_time_needs_its_offset(self):
        self.assertIsNone(epg._xmltv_epoch("20260817120000"))
        self.assertEqual(epg._xmltv_epoch("20260817120000 +0000"), 1786968000)
        self.assertEqual(epg._xmltv_epoch("20260817120000 -0500"), 1786968000 + 5 * 3600)
        self.assertIsNone(epg._xmltv_epoch(""))
        self.assertIsNone(epg._xmltv_epoch(None))

    def test_a_process_timezone_cannot_move_the_guide(self):
        """The conversion is arithmetic on UTC, so TZ is not part of the answer.

        `time.localtime` would be, which is why it is not used. A server whose TZ is wrong -- or
        simply different from the visitor's -- must not shift every programme on the page.
        """
        import os
        old = os.environ.get("TZ")
        try:
            for tz in ("UTC", "America/Chicago", "Asia/Tokyo"):
                os.environ["TZ"] = tz
                if hasattr(__import__("time"), "tzset"):
                    __import__("time").tzset()
                self.assertEqual(epg._xmltv_epoch("20260817120000 +0000"), 1786968000)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            if hasattr(__import__("time"), "tzset"):
                __import__("time").tzset()


if __name__ == "__main__":                                      # pragma: no cover
    unittest.main(verbosity=2)
