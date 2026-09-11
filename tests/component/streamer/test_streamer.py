#!/usr/bin/env python3
"""Tests for the Streamer. Standard library only, no network, no IPTV provider.

    python3 backend/streamer/test_streamer.py           # from the repo root
    python3 -m streamer.test_streamer                   # from backend/

Three things are actually being defended here and the rest is parsing:

1. **The SSRF validator**, against a table of hostile inputs. The table is the specification --
   if a bypass is ever found, it gets a row here before it gets a fix.
2. **No credential ever escapes.** A sentinel password is pushed through the real router and
   every channel it could come back out of -- log records, response bodies, exception text,
   the session's public document -- is searched for it.
3. **The DoS caps** on concurrent sessions and on path names.

No playlist from `external/` is read, quoted or shipped. Every fixture below was written by
hand for this file; the provider playlists in that directory embed real credentials in their
URLs and must never enter this repo's source.
"""
from __future__ import annotations

import functools
import http.server
import io
import ipaddress
import json
import logging
import pathlib
import socketserver
import sys
import threading
import unittest
import unittest.mock
import urllib.parse

sys.path.insert(0, str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())))

from streamer.apps import m3u, routes, safefetch, sessions, xtream          # noqa: E402
from streamer.lib.safefetch import BlockedURL, Policy, Scrubber            # noqa: E402

SENTINEL_USER = "zz-streamer-test-user-zz"
SENTINEL_PASS = "Hunter2-CorrectHorseBatteryStaple-9times"


def resolver(mapping: dict[str, list[str]], counter: list[int] | None = None):
    """A stand-in for getaddrinfo so the hostile table needs no DNS and no network."""
    def _r(host: str, port: int) -> list[str]:
        if counter is not None:
            counter[0] += 1
        try:
            return [str(ipaddress.ip_address(host))]      # a literal resolves to itself
        except ValueError:
            pass
        if host in mapping:
            return mapping[host]
        raise OSError("NXDOMAIN")
    return _r


# ===================================================================== SSRF

class TestAddressClassification(unittest.TestCase):
    """`_reject_reason` on addresses directly -- the layer under `validate_url`."""

    BLOCKED = [
        ("127.0.0.1", "loopback"), ("127.255.255.254", "loopback"),
        ("10.0.0.1", "private"), ("172.16.0.1", "private"), ("172.31.255.255", "private"),
        ("192.168.1.1", "private"), ("169.254.169.254", "link-local"),
        ("169.254.0.1", "link-local"), ("0.0.0.0", "unspecified"),
        ("100.64.0.1", None), ("192.0.2.1", None), ("198.18.0.1", None),
        ("224.0.0.1", "multicast"), ("239.255.255.250", "multicast"),
        ("240.0.0.1", None), ("255.255.255.255", None),
        ("::1", "loopback"), ("::", "unspecified"), ("fe80::1", "link-local"),
        ("fc00::1", "private"), ("fd12:3456::1", "private"), ("ff02::1", "multicast"),
        ("::ffff:127.0.0.1", None), ("::ffff:169.254.169.254", None),
        ("::ffff:10.0.0.1", None), ("2002:7f00:1::1", None),
    ]
    ALLOWED = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111",
               "2001:4860:4860::8888"]

    def test_blocked(self):
        for addr, expect in self.BLOCKED:
            with self.subTest(addr=addr):
                reason = safefetch._reject_reason(ipaddress.ip_address(addr))
                self.assertIsNotNone(reason, f"{addr} was allowed and must not be")
                if expect:
                    self.assertIn(expect, reason)

    def test_allowed(self):
        for addr in self.ALLOWED:
            with self.subTest(addr=addr):
                self.assertIsNone(safefetch._reject_reason(ipaddress.ip_address(addr)))

    def test_metadata_endpoint_specifically(self):
        """169.254.169.254 is the one address that has cost the industry the most money."""
        self.assertIsNotNone(safefetch._reject_reason(ipaddress.ip_address("169.254.169.254")))


class TestValidateUrl(unittest.TestCase):
    """The hostile-input table. Each row is an attack somebody has actually used."""

    MAP = {
        "metadata.example":  ["169.254.169.254"],   # a public name pointing at the metadata IP
        "localtest.example": ["127.0.0.1"],         # a public name pointing at loopback
        "lan.example":       ["192.168.1.10"],
        "rebind.example":    ["1.1.1.1", "127.0.0.1"],   # two answers, one hostile
        "good.example":      ["93.184.216.34"],
        "v6bad.example":     ["::1"],
        "v6good.example":    ["2606:4700:4700::1111"],
    }

    def block(self, url, must_contain=None):
        with self.subTest(url=url):
            with self.assertRaises(BlockedURL, msg=f"{url} was NOT blocked") as cm:
                safefetch.validate_url(url, Policy(), _resolver=resolver(self.MAP))
            if must_contain:
                self.assertIn(must_contain, str(cm.exception))
            # Whatever the reason, the message must not quote the URL back -- that is how a
            # credential in a path gets into a log via an error message.
            self.assertNotIn(SENTINEL_PASS, str(cm.exception))

    def test_scheme_allowlist(self):
        for url in ["file:///etc/passwd", "file://localhost/etc/shadow",
                    "gopher://good.example/_x", "ftp://good.example/x",
                    "data:text/plain;base64,aGk=", "javascript:alert(1)",
                    "jar:http://good.example/!/x", "dict://good.example:11211/stat",
                    "ldap://good.example/", "//good.example/x", "good.example/x"]:
            self.block(url)

    def test_loopback_and_private_literals(self):
        for url in ["http://127.0.0.1/", "http://127.0.0.1:8800/api/status",
                    "https://127.0.0.1/", "http://10.1.2.3/", "http://192.168.0.1/",
                    "http://172.16.9.9/", "http://0.0.0.0:8800/", "http://[::1]:8800/",
                    "http://[fe80::1]/", "http://[fd00::dead]/", "http://[::]/"]:
            self.block(url)

    def test_metadata_endpoint(self):
        self.block("http://169.254.169.254/latest/meta-data/iam/security-credentials/",
                   "link-local")
        self.block("http://metadata.example/computeMetadata/v1/", "link-local")
        self.block("http://[fe80::a9fe:a9fe]/", "link-local")

    def test_obfuscated_ipv4_forms(self):
        """Decimal, octal, hex and short-form addresses.

        These are the reason the check is on the *resolved* address: `2130706433` is not the
        string `127.0.0.1` and no hostname denylist catches it, but `getaddrinfo` turns it into
        127.0.0.1 and the address check then does. Uses the real resolver, because these are
        numeric forms libc parses without a network.
        """
        for url in ["http://2130706433/", "http://0177.0.0.1/", "http://127.1/",
                    "http://0x7f000001/"]:
            with self.subTest(url=url):
                with self.assertRaises(BlockedURL, msg=f"{url} was NOT blocked"):
                    safefetch.validate_url(url, Policy())

    def test_hostname_pointing_at_a_private_address(self):
        """The `localtest.me` / `nip.io` family: a perfectly public name, a hostile answer."""
        self.block("http://localtest.example/", "loopback")
        self.block("http://lan.example/", "private")
        self.block("http://v6bad.example/", "loopback")

    def test_rebinding_multiple_answers(self):
        """A name answering with both a public and a private address is refused outright.

        Taking the public one and connecting to it would be a coin flip against an attacker
        who controls the ordering.
        """
        self.block("http://rebind.example/", "loopback")

    def test_malformed(self):
        for url in ["", "   ", "http://", "http:///path", "http://:80/",
                    "http://good.example:0/", "http://good.example:99999/",
                    "http://good.example:notaport/",
                    "http://good.example/\r\nX-Evil: 1", "http://good.example/\nfoo"]:
            self.block(url)
        self.block("http://" + "a" * 5000 + ".example/")

    def test_unresolvable(self):
        self.block("http://nowhere.example/")

    def test_allows_a_normal_public_url(self):
        t = safefetch.validate_url("http://good.example/playlist.m3u",
                                   Policy(), _resolver=resolver(self.MAP))
        self.assertEqual(t.host, "good.example")
        self.assertEqual(t.ip, "93.184.216.34")     # the pinned address, not the name
        self.assertEqual(t.port, 80)
        self.assertEqual(t.path, "/playlist.m3u")
        t6 = safefetch.validate_url("https://v6good.example:8443/x?y=1",
                                    Policy(), _resolver=resolver(self.MAP))
        self.assertEqual(t6.ip, "2606:4700:4700::1111")
        self.assertEqual(t6.port, 8443)
        self.assertEqual(t6.path, "/x?y=1")

    def test_userinfo_becomes_a_header_not_a_url(self):
        t = safefetch.validate_url(f"http://user:{SENTINEL_PASS}@good.example/x",
                                   Policy(), _resolver=resolver(self.MAP))
        self.assertTrue(t.auth.startswith("Basic "))
        self.assertNotIn(SENTINEL_PASS, t.path)
        self.assertNotIn(SENTINEL_PASS, t.origin)

    def test_odd_ports_are_allowed_on_public_addresses(self):
        """IPTV panels really do live on 8080, 2082 and 25461. Port is not the control."""
        for port in (80, 443, 8080, 2082, 25461, 65535):
            t = safefetch.validate_url(f"http://good.example:{port}/x",
                                       Policy(), _resolver=resolver(self.MAP))
            self.assertEqual(t.port, port)

    def test_policy_cannot_be_relaxed_from_the_environment(self):
        """`allow_private` must be a constructor argument only.

        A live public box must have no switch that turns the SSRF check off. If someone ever
        adds `os.environ` handling to Policy, this fails.

        This assertion used to be "the module never mentions `os.environ` at all", which was a
        clean grep and is no longer true: the User-Agent default is an operator override read
        once at import. So the grep is now an *allow-list* -- the environment may be consulted,
        on lines that are visibly about the user agent and nowhere else. The `Policy` class body
        itself must still be free of it, which is the half of the old test that was actually
        about `allow_private`.
        """
        self.assertFalse(Policy().allow_private)
        src = pathlib.Path(safefetch.__file__).read_text()
        head = src[src.index("class Policy"):src.index("class Target")]
        # `os.environ` / `getenv` specifically -- the prose in the docstring says "environment"
        # and matching that would fail on the very comment explaining the rule.
        self.assertNotIn("os.environ", head)
        self.assertNotIn("getenv", head)
        for n, line in enumerate(src.splitlines(), 1):
            if "os.environ" in line or "getenv" in line:
                self.assertIn("_UA_ENV", line,
                              f"{safefetch.__file__}:{n} reads the environment for something "
                              f"other than the user agent")

    def test_the_environment_cannot_turn_the_ssrf_check_off(self):
        """Behavioural, and in a subprocess, which is the only way it means anything.

        `DEFAULT_USER_AGENT` is read at import and `Policy()` is an evaluated-at-import default
        argument throughout the module, so mutating `os.environ` in this process would prove
        nothing at all -- the import already happened. A fresh interpreter with the hostile
        variables already set is the real test.
        """
        import os
        import subprocess
        env = {**os.environ,
               "SYMONEURAL_STREAMER_ALLOW_PRIVATE": "1", "ALLOW_PRIVATE": "1",
               "SYMONEURAL_STREAMER_POLICY_ALLOW_PRIVATE": "true", "allow_private": "1"}
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from streamer.lib.safefetch import Policy\n"
             "print(Policy().allow_private)"
             % str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()))],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False")


class TestRedirects(unittest.TestCase):
    def test_redirect_target_is_revalidated(self):
        """A public host redirecting to loopback must die on the second validation.

        Exercised against the real code path by checking that `open_stream` re-validates: the
        redirect Location is fed through `validate_url` with the same policy, so this is the
        same assertion as the table above once the plumbing is trusted.
        """
        for loc in ["http://127.0.0.1:8800/api/status", "http://localtest.example/",
                    "http://169.254.169.254/", "file:///etc/passwd"]:
            with self.subTest(loc=loc):
                with self.assertRaises(BlockedURL):
                    safefetch.validate_url(loc, Policy(), _resolver=resolver(
                        TestValidateUrl.MAP))

    def test_relative_redirect_resolves_against_the_reached_target(self):
        t = safefetch.validate_url("http://good.example/a/b/c",
                                   Policy(), _resolver=resolver(TestValidateUrl.MAP))
        self.assertEqual(t.join("../d"), "http://good.example:80/a/d")
        self.assertEqual(t.join("/e"), "http://good.example:80/e")

    def test_redirect_cap_is_bounded_at_both_ends(self):
        """Bidirectional on purpose.

        Too high is a redirect loop held open; too low fails ordinary providers. Xtream stream
        URLs chain -- panel to balancer to region to edge, sometimes with a token handoff -- and
        the cap was 3, which is fewer hops than a working provider uses. Every hop is
        re-validated, so length is not the security property; the upper bound is only there to
        end a loop.
        """
        self.assertGreaterEqual(Policy().max_redirects, 5)
        self.assertLessEqual(Policy().max_redirects, 8)


class TestPinning(unittest.TestCase):
    """The check and the connection must not be able to see different answers."""

    def setUp(self):
        self.seen: list[str] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.seen.append(self.headers.get("Host", ""))
                body = b"#EXTM3U\n#EXTINF:-1,Test\nhttp://example.com/a.ts\n"
                self.send_response(200)
                self.send_header("Content-Type", "audio/x-mpegurl")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_name_is_resolved_exactly_once_and_the_pinned_ip_is_used(self):
        """If the connection re-resolved, the resolver would be called twice. It is called once.

        That single call count is the whole anti-rebinding argument, expressed as a test: there
        is no second lookup for an attacker's second answer to win.
        """
        calls = [0]
        r = resolver({"pinned.example": ["127.0.0.1"]}, calls)
        pol = Policy(allow_private=True)            # test-only; see Policy's docstring
        body, _ct, target = safefetch.fetch(
            f"http://pinned.example:{self.port}/x", pol, _resolver=r)
        self.assertEqual(calls[0], 1, "the name was resolved more than once")
        self.assertEqual(target.ip, "127.0.0.1")
        self.assertEqual(target.host, "pinned.example")
        self.assertIn(b"#EXTM3U", body)
        # Connected to the pinned address, but presented as the name: virtual hosting and
        # certificate validation still work.
        self.assertEqual(self.seen[-1], f"pinned.example:{self.port}")

    def test_connection_object_keeps_the_name_and_the_pinned_address_apart(self):
        t = safefetch.Target(scheme="http", host="pinned.example", port=80,
                             ip="93.184.216.34", path="/")
        conn = safefetch._PinnedHTTPConnection(t, 5.0)
        self.assertEqual(conn.host, "pinned.example")     # -> Host: header and TLS SNI
        self.assertEqual(conn._pinned_ip, "93.184.216.34")  # -> the socket

    def test_body_size_is_capped(self):
        pol = Policy(allow_private=True, max_bytes=8)
        with self.assertRaises(safefetch.FetchError):
            safefetch.fetch(f"http://pinned.example:{self.port}/x", pol,
                            _resolver=resolver({"pinned.example": ["127.0.0.1"]}))


class TestFfmpegNeverSeesAUrl(unittest.TestCase):
    """The structural guarantee that makes the SSRF control real rather than advisory."""

    def test_argv_has_pipe_input_and_a_protocol_allowlist(self):
        src = pathlib.Path(sessions.__file__).read_text()
        spawn = src[src.index("def _spawn"):src.index("def _drain_stderr")]
        self.assertIn('"-i", "pipe:0"', spawn)
        self.assertIn('"-protocol_whitelist", "pipe,fd"', spawn)
        # If the URL were ever interpolated into argv, credentials would be in `ps` output and
        # ffmpeg would do its own DNS. Neither may happen.
        self.assertNotIn("s.url", spawn)
        self.assertNotIn("session.url", spawn)


# ===================================================================== M3U

FIXTURE = """﻿#EXTM3U x-tvg-url="http://epg.example/x.xml"\r
#EXTINF:-1 tvg-id="bbc1.uk" tvg-name="BBC One" tvg-logo="http://img.example/1.png" \
group-title="UK | Entertainment",BBC One HD\r
http://provider.example:8080/live/u/p/1.ts\r
#EXTINF:-1 tvg-name="Sky Sports, Main Event" group-title="UK | Sport",Sky Sports Main Event\r
http://provider.example:8080/live/u/p/2.ts\r
#EXTGRP:Movies\r
#EXTINF:7200,The Example Film (2020)\r
http://provider.example:8080/movie/u/p/300.mp4\r
#EXTINF:-1,\r
http://provider.example:8080/live/u/p/4.ts\r
\r
# a stray comment\r
#EXTVLCOPT:network-caching=1000\r
#KODIPROP:inputstream=inputstream.adaptive\r
http://provider.example:8080/series/u/p/9.mkv\r
#EXTINF:-1 tvg-id="orphan",No URL Follows\r
"""


class TestM3U(unittest.TestCase):
    def setUp(self):
        self.chans, self.truncated = m3u.parse_m3u(FIXTURE)

    def test_counts_and_no_invention(self):
        # Five URLs are present; the trailing #EXTINF has no URL and must be dropped, not
        # given an invented one.
        self.assertEqual(len(self.chans), 5)
        self.assertFalse(self.truncated)
        self.assertNotIn("No URL Follows", [c.name for c in self.chans])

    def test_attributes(self):
        c = self.chans[0]
        self.assertEqual(c.name, "BBC One HD")
        self.assertEqual(c.tvg_id, "bbc1.uk")
        self.assertEqual(c.tvg_name, "BBC One")
        self.assertEqual(c.logo, "http://img.example/1.png")
        self.assertEqual(c.group, "UK | Entertainment")
        self.assertEqual(c.kind, "live")

    def test_comma_inside_a_quoted_attribute(self):
        """The naive split(',', 1) truncates the attributes and mangles the name."""
        c = self.chans[1]
        self.assertEqual(c.name, "Sky Sports Main Event")
        self.assertEqual(c.tvg_name, "Sky Sports, Main Event")
        self.assertEqual(c.group, "UK | Sport")

    def test_extgrp_and_duration_and_kind(self):
        c = self.chans[2]
        self.assertEqual(c.name, "The Example Film (2020)")
        self.assertEqual(c.group, "Movies")
        self.assertEqual(c.duration, 7200.0)
        self.assertEqual(c.kind, "vod")

    def test_empty_name_is_marked_not_invented(self):
        self.assertEqual(self.chans[3].name, "(unnamed)")

    def test_bare_url_is_kept_and_named_from_its_filename(self):
        c = self.chans[4]
        self.assertEqual(c.url, "http://provider.example:8080/series/u/p/9.mkv")
        self.assertEqual(c.name, "9.mkv")
        self.assertEqual(c.kind, "series")

    def test_bom_and_crlf_absorbed(self):
        for c in self.chans:
            self.assertNotIn("\r", c.url)
            self.assertNotIn("﻿", c.name)

    def test_empty_and_junk_input(self):
        self.assertEqual(m3u.parse_m3u(""), ([], False))
        self.assertEqual(m3u.parse_m3u("#EXTM3U\n"), ([], False))
        self.assertEqual(m3u.parse_m3u("not a playlist at all")[0][0].name,
                         "not a playlist at all")

    def test_no_extm3u_header_still_parses(self):
        chans, _ = m3u.parse_m3u("#EXTINF:-1,A\nhttp://a.example/1.ts\n")
        self.assertEqual(len(chans), 1)

    def test_the_default_is_no_cap_so_nothing_is_dropped(self):
        """`MAX_CHANNELS = 0` by owner's instruction: parse the file, all of it."""
        self.assertEqual(m3u.MAX_CHANNELS, 0)
        big = "".join(f"#EXTINF:-1,C{i}\nhttp://a.example/{i}.ts\n" for i in range(25_000))
        chans, truncated = m3u.parse_m3u(big)
        self.assertEqual(len(chans), 25_000)
        self.assertFalse(truncated, "nothing was dropped, so nothing may claim it was")

    def test_truncation_is_reported_not_silent_when_a_cap_is_set(self):
        """The reporting machinery still works, for whoever sets a cap again.

        Kept rather than deleted: the failure this guards is a *silent* short list, and that
        failure comes back the moment anyone reintroduces a bound without a flag beside it.
        """
        with unittest.mock.patch.object(m3u, "MAX_CHANNELS", 500):
            big = "".join(f"#EXTINF:-1,C{i}\nhttp://a.example/{i}.ts\n" for i in range(550))
            chans, truncated = m3u.parse_m3u(big)
        self.assertTrue(truncated)
        self.assertEqual(len(chans), 500)


class TestHlsParser(unittest.TestCase):
    def test_master(self):
        pl = m3u.parse_hls(
            "#EXTM3U\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=1400000,RESOLUTION=848x480\nlow/index.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\nhigh/index.m3u8\n")
        self.assertTrue(pl.is_master)
        self.assertEqual([v.bandwidth for v in pl.variants], [1400000, 5000000])
        self.assertEqual(pl.variants[1].resolution, "1920x1080")

    def test_media_playlist_sequence(self):
        pl = m3u.parse_hls(
            "#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:117\n"
            "#EXTINF:4.0,\na.ts\n#EXTINF:4.0,\nb.ts\n#EXTINF:3.5,\nc.ts\n")
        self.assertFalse(pl.is_master)
        self.assertEqual(pl.target_duration, 4.0)
        self.assertEqual([s.sequence for s in pl.segments], [117, 118, 119])
        self.assertEqual([s.uri for s in pl.segments], ["a.ts", "b.ts", "c.ts"])
        self.assertFalse(pl.ended)

    def test_endlist_marks_a_complete_recording(self):
        pl = m3u.parse_hls("#EXTM3U\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST\n")
        self.assertTrue(pl.ended)

    def test_encrypted_is_detected_not_ignored(self):
        pl = m3u.parse_hls('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k.key"\n'
                           "#EXTINF:2,\na.ts\n")
        self.assertTrue(pl.encrypted)
        self.assertFalse(m3u.parse_hls("#EXTM3U\n#EXT-X-KEY:METHOD=NONE\n"
                                       "#EXTINF:2,\na.ts\n").encrypted)


# ===================================================================== credentials

class TestScrubber(unittest.TestCase):
    def test_query_credentials(self):
        s = safefetch.redact(
            f"http://p.example/player_api.php?username=u&password={SENTINEL_PASS}&action=x")
        self.assertNotIn(SENTINEL_PASS, s)
        self.assertIn("password=***", s)

    def test_userinfo(self):
        self.assertNotIn(SENTINEL_PASS,
                         safefetch.redact(f"http://u:{SENTINEL_PASS}@p.example/x"))

    def test_path_segment_needs_the_session_scrubber(self):
        """An Xtream password sits in a *path segment* and looks like nothing.

        `redact` alone cannot see it -- which is the whole reason `Scrubber` carries the
        session's own literals.
        """
        url = f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts"
        self.assertIn(SENTINEL_PASS, safefetch.redact(url))          # documents the gap
        scrub = Scrubber([SENTINEL_USER, SENTINEL_PASS])
        self.assertNotIn(SENTINEL_PASS, scrub(url))
        self.assertNotIn(SENTINEL_USER, scrub(url))

    def test_percent_encoded_form_is_also_scrubbed(self):
        scrub = Scrubber(["p@ss word/x"])
        self.assertNotIn("p%40ss%20word%2Fx", scrub("http://a/p%40ss%20word%2Fx/1.ts"))

    def test_xtream_creds_repr_does_not_leak(self):
        c = xtream.XtreamCreds("http://p.example", SENTINEL_USER, SENTINEL_PASS)
        for text in (repr(c), str(c), f"{c}", repr([c]), repr({"c": c})):
            self.assertNotIn(SENTINEL_PASS, text)
            self.assertNotIn(SENTINEL_USER, text)

    def test_stream_url_is_built_correctly_but_never_shown(self):
        c = xtream.XtreamCreds("p.example:8080", SENTINEL_USER, SENTINEL_PASS)
        url = xtream.stream_url(c, "live", "123", "ts")
        self.assertEqual(url, f"http://p.example:8080/live/{SENTINEL_USER}/"
                              f"{SENTINEL_PASS}/123.ts")
        self.assertNotIn(SENTINEL_PASS, c.scrubber(url))


class TestNoCredentialLeak(unittest.TestCase):
    """The grep test. A sentinel password goes in; every exit is searched for it.

    The exits are: our own log output, the HTTP response body, the text of any exception
    raised, and the session document handed to the browser. All four, because a password that
    is kept out of the log file and returned in a 422 body has not been kept.
    """

    def setUp(self):
        self.buf = io.StringIO()
        self.handler = logging.StreamHandler(self.buf)
        self.handler.setLevel(logging.DEBUG)
        self.root = logging.getLogger()
        self.prev_level = self.root.level
        self.root.setLevel(logging.DEBUG)
        self.root.addHandler(self.handler)

    def tearDown(self):
        self.root.removeHandler(self.handler)
        self.root.setLevel(self.prev_level)

    def assertClean(self, *texts: str):
        blob = "\n".join(t for t in texts if t)
        log_text = self.buf.getvalue()
        for secret, name in ((SENTINEL_PASS, "password"), (SENTINEL_USER, "username")):
            self.assertNotIn(secret, log_text, f"the {name} appeared in log output")
            self.assertNotIn(secret, blob, f"the {name} appeared in a response or error")

    def test_router_paths_never_carry_a_credential(self):
        """Structural: uvicorn logs the request line, so no credential may ride in a URL."""
        for route in routes.router.routes:
            path = getattr(route, "path", "")
            for bad in ("username", "password", "user", "pass", "token", "creds"):
                self.assertNotIn(bad, path.lower(),
                                 f"route {path} puts a credential in the request line")
            if "POST" not in getattr(route, "methods", set()):
                self.assertNotIn("{", path.replace("{sid}", "").replace("{name}", ""))

    def test_credential_models_have_no_required_fields(self):
        """A missing required field makes pydantic echo the whole body into a 422.

        That body contains the password. With defaults there is no such error path.
        """
        for model in (routes.XtreamBody, routes.TuneBody, routes.PlaylistBody):
            with self.subTest(model=model.__name__):
                model()                                  # must not raise
                for name, field in model.model_fields.items():
                    self.assertFalse(field.is_required(),
                                     f"{model.__name__}.{name} is required; a missing-field "
                                     f"422 would echo the whole request body")

    def test_blocked_xtream_server_does_not_leak(self):
        creds = xtream.XtreamCreds(f"http://127.0.0.1:8800", SENTINEL_USER, SENTINEL_PASS)
        with self.assertRaises(xtream.XtreamError) as cm:
            xtream.panel_info(creds, Policy())
        self.assertClean(str(cm.exception), repr(cm.exception))

    def test_session_start_on_a_blocked_url_does_not_leak(self):
        url = f"http://127.0.0.1:8800/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts"
        mgr = sessions.SessionManager()
        with self.assertRaises(sessions.StreamerError) as cm:
            mgr.start(url, "Test Channel", Policy(),
                      Scrubber([SENTINEL_USER, SENTINEL_PASS]))
        self.assertClean(str(cm.exception), repr(cm.exception))

    def test_session_public_document_has_no_url_field(self):
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"),
                             created=0.0, scrub=Scrubber(), policy=Policy(),
                             url=f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts")
        import json
        doc = json.dumps(s.public())
        self.assertClean(doc)
        self.assertNotIn("p.example", doc)

    def test_transcoder_stderr_never_reaches_the_client(self):
        """ffmpeg's stderr is written by a program we do not control and must stay internal.

        The hole this guards: a visitor pastes an Xtream-exported M3U, whose URLs carry the
        password in a *path segment*, and sends `/tune` with no username or password fields --
        so a scrubber primed from the request body would be empty and `redact()` cannot see a
        path segment. If `public()` echoed stderr, that password would come straight back out
        of `GET /session/{sid}`.
        """
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"),
                             created=0.0, scrub=Scrubber(), policy=Policy(),
                             url=f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts")
        s.state = "failed"
        s.transcoder_error = (f"pipe:0: Invalid data found when processing input "
                              f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts")
        import json
        doc = json.dumps(s.public())
        self.assertClean(doc)
        # Still says something honest rather than nothing.
        self.assertIsNotNone(s.public()["error"])

    def test_scrubber_derived_from_the_url_catches_path_segment_credentials(self):
        """`Scrubber.from_url` is what protects the M3U path, where nobody registered a secret."""
        url = f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts?token={SENTINEL_PASS}"
        scrub = Scrubber.from_url(url)
        self.assertClean(scrub(f"ffmpeg: cannot open {url}"))

    def test_full_request_through_the_router(self):
        """End to end through FastAPI, including the error responses it generates itself."""
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:                                  # pragma: no cover
            self.skipTest(f"TestClient unavailable: {exc}")
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/streamer")
        client = TestClient(app, raise_server_exceptions=False)
        bodies = []
        cred = {"server": "http://127.0.0.1:8800", "username": SENTINEL_USER,
                "password": SENTINEL_PASS}
        for path, payload in [
            ("/api/streamer/xtream/info", cred),
            ("/api/streamer/xtream/channels", cred),
            ("/api/streamer/xtream/info", {"username": SENTINEL_USER,
                                        "password": SENTINEL_PASS}),      # no server
            ("/api/streamer/xtream/info", {**cred, "kinds": 12345}),          # 422 path
            ("/api/streamer/xtream/info", {**cred, "server": "http://169.254.169.254"}),
            ("/api/streamer/tune", {"url": f"http://127.0.0.1:8800/live/{SENTINEL_USER}/"
                                        f"{SENTINEL_PASS}/1.ts",
                                 "label": "Test", "username": SENTINEL_USER,
                                 "password": SENTINEL_PASS}),
            ("/api/streamer/playlist", {"url": f"http://127.0.0.1:8800/x.m3u"}),
        ]:
            r = client.post(path, json=payload)
            bodies.append(r.text)
            self.assertNotEqual(r.status_code, 500, f"{path} raised: {r.text[:200]}")
        self.assertClean(*bodies)


# ===================================================================== caps

class TestCapsAndPaths(unittest.TestCase):
    def test_segment_names_are_allowlisted(self):
        for good in ["s00000.ts", "s12345.ts", "s0.m4s"]:
            self.assertTrue(sessions.SEGMENT_RE.match(good), good)
        for bad in ["../../etc/passwd", "..%2f..%2fetc%2fpasswd", "s00000.ts/../../x",
                    "/etc/passwd", "s00000.sh", "live.m3u8.bak", ".", "..", "",
                    "s00000.ts\x00.png", "S00000.TS"]:
            self.assertIsNone(sessions.SEGMENT_RE.match(bad), f"{bad!r} was accepted")

    def test_caps_are_bounded(self):
        self.assertLessEqual(sessions.MAX_SESSIONS, 8)
        self.assertGreaterEqual(sessions.MAX_SESSIONS, 1)
        self.assertLessEqual(sessions.IDLE_TIMEOUT, 600)
        self.assertLessEqual(sessions.MAX_LIFETIME, 21600)

    def test_reaper_is_not_started_at_import(self):
        """Importing the module must not spawn a thread in a process that never tunes.

        Checked in a *fresh subprocess*. Asserting on `threading.enumerate()` in this process
        would silently become a test of test-ordering the moment any earlier test starts a real
        session, and would then fail for a reason unrelated to the property being guarded.
        """
        import subprocess
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "import threading\n"
             "import streamer\n"
             "print([t.name for t in threading.enumerate() if t.name.startswith('streamer-')])"
             % str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()))],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "[]",
                         "importing apps.streamer started a background thread")

    def test_manager_makes_no_directory_until_used(self):
        mgr = sessions.SessionManager()
        self.assertIsNone(mgr._root)


class TestRackStatus(unittest.TestCase):
    def test_shape_matches_the_unit_model(self):
        st = routes.status()
        self.assertEqual(set(st), {"id", "label", "slot", "state", "bus", "href",
                                   "spec", "detail"})
        self.assertIn(st["state"], ("ready", "busy", "queued", "offline"))
        self.assertIn(st["bus"], ("gpu", "cpu"))

    def test_state_is_a_reading_not_a_decoration(self):
        """With no ffmpeg the surface cannot work and must say offline."""
        real = sessions.FFMPEG
        try:
            sessions.FFMPEG = routes.FFMPEG = None
            self.assertEqual(routes.status()["state"], "offline")
        finally:
            sessions.FFMPEG = routes.FFMPEG = real

    def test_reports_no_stored_channels(self):
        self.assertIn("no", routes.status()["detail"].lower())


# ===================================================================== the repro harness
#
# Everything below this line exists because of one sentence from the owner: "I know most of
# these streams work, so make sure you repair it. If it's not active you will come to a page
# from the server saying it's down, not just a blank screen."
#
# That is a diagnosis, not a feature request. A provider page means the channel is dead; a blank
# screen means *we* are broken. Telling those apart needs the failure modes reproduced, and
# there are no provider credentials on this box and no known-good stream URL to test against.
#
# So every failure mode is synthesised locally. ffmpeg builds real media -- a real transport
# stream, a real HLS playlist, a real AES-128 encrypted HLS playlist, real HEVC -- and a
# loopback HTTP server plays the provider, including the provider's bad behaviour: HTML at 200,
# 403 with a page instead of a body, and a User-Agent gate. A fix that is not reproduced here is
# a fix nobody can falsify.
#
# The SSRF validator is not weakened to make this work. `Policy(allow_private=True)` is the
# constructor argument that exists for exactly this and is unreachable from any request, and the
# `_resolver=` seam is used where a name is needed. Neither is a bypass; both are the seams the
# module was built with.

import shutil                                                             # noqa: E402
import subprocess                                                         # noqa: E402
import tempfile                                                           # noqa: E402
import time                                                               # noqa: E402

FFMPEG_BIN = shutil.which("ffmpeg")
needs_ffmpeg = unittest.skipUnless(FFMPEG_BIN, "ffmpeg is not installed")

#: A User-Agent that is neither VLC nor anything a provider recognises -- what this module used
#: to send, and what a gated provider refuses.
STRANGER_UA = "SyMoNeuRaL-Streamer/1"

OFFLINE_PAGE = (
    b"<!DOCTYPE html><html><head><title>Stream unavailable</title>"
    b"<style>body{color:#c00}</style>"
    b"<script>var x='this javascript must not become the message';</script></head>"
    b"<body><h1>Channel temporarily offline</h1>"
    b"<p>This channel is not currently broadcasting. Please try another.</p>"
    b"</body></html>")


@functools.lru_cache(maxsize=1)
def media() -> pathlib.Path:
    """Build every media fixture once per run, with ffmpeg, into a temporary directory.

    Deliberately tiny -- 160x120 at 10 fps -- because these are the only slow tests in the file
    and the shapes being asserted on do not depend on the picture.
    """
    d = pathlib.Path(tempfile.mkdtemp(prefix="streamer-fixtures-"))

    def ff(*args):
        subprocess.run([FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error", *args],
                       check=True, timeout=180)

    src = ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10",
           "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4"]
    ff(*src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
       "-f", "mpegts", str(d / "clean.ts"))
    ff(*src, "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
       "-c:a", "aac", "-f", "mpegts", str(d / "hevc.ts"))
    # ---- fixtures for the codec repair, and they have to be LONGER than the others.
    #
    # 20 seconds, not 4, and the reason is a real constraint of the design rather than a test
    # convenience. ffmpeg does not print its input dump -- the only place the codecs appear --
    # until `-analyzeduration` (5M microseconds, so five seconds of content) or `-probesize` is
    # satisfied. A four-second fixture reaches EOF first, so the codecs land *after* the final
    # write, and since only the pump thread may touch `proc.stdin`, only a write can perform the
    # swap. The repair then never fires.
    #
    # That is not a bug in production and it is worth being precise about why: an IPTV channel is
    # continuous, so there is always a next write, and the swap happens a second or so in. It IS a
    # bug in any test whose source runs out during the probe, and it cost a cycle here. A source
    # that outlives the probe window is the honest model of a live stream.
    long_src = ["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440", "-t", "20"]
    # The measured common failure: the picture is ordinary h264 and plays anywhere, and the
    # soundtrack is AC-3, which no MSE build in this repo's test path will decode. hls.js fails
    # the whole media element rather than muting it, so this is a *black screen* caused by audio.
    ff(*long_src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "ac3",
       "-f", "mpegts", str(d / "ac3-long.ts"))
    # The regression guard, and the reason it is a fixture rather than a unit assertion: mp2 IS
    # playable, measured. A deny-list containing mp2 shipped briefly on another branch, and this
    # file is where that must never come back -- a stream that plays must take the copy path.
    ff(*long_src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "mp2",
       "-f", "mpegts", str(d / "mp2-long.ts"))
    ff(*long_src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
       "-f", "mpegts", str(d / "clean-long.ts"))
    ff(*long_src, "-c:v", "libx265", "-preset", "ultrafast", "-x265-params", "log-level=error",
       "-c:a", "aac", "-f", "mpegts", str(d / "hevc-long.ts"))

    (d / "hls").mkdir()
    ff("-i", str(d / "clean.ts"), "-c", "copy", "-f", "hls", "-hls_time", "1",
       "-hls_playlist_type", "vod", "-hls_list_size", "0",
       "-hls_segment_filename", str(d / "hls" / "seg%03d.ts"), str(d / "hls" / "index.m3u8"))

    # AES-128. `-hls_key_info_file` takes three lines: the URI to *write into the playlist*,
    # the path to read the key bytes from, and optionally the IV in hex. Getting that order
    # wrong is the classic way to waste a cycle here.
    key = bytes(range(16))
    (d / "enc.key").write_bytes(key)
    (d / "aes").mkdir()
    (d / "keyinfo").write_text(f"enc.key\n{d / 'enc.key'}\n")
    ff("-i", str(d / "clean.ts"), "-c", "copy", "-f", "hls", "-hls_time", "1",
       "-hls_playlist_type", "vod", "-hls_list_size", "0",
       "-hls_key_info_file", str(d / "keyinfo"),
       "-hls_segment_filename", str(d / "aes" / "seg%03d.ts"), str(d / "aes" / "index.m3u8"))

    # The same, with an explicit IV, so both IV paths (attribute and media-sequence fallback)
    # are exercised against real ciphertext rather than only in the parser.
    (d / "aesiv").mkdir()
    (d / "keyinfo_iv").write_text(f"enc.key\n{d / 'enc.key'}\n" + "0f" * 16 + "\n")
    ff("-i", str(d / "clean.ts"), "-c", "copy", "-f", "hls", "-hls_time", "1",
       "-hls_playlist_type", "vod", "-hls_list_size", "0",
       "-hls_key_info_file", str(d / "keyinfo_iv"),
       "-hls_segment_filename", str(d / "aesiv" / "seg%03d.ts"),
       str(d / "aesiv" / "index.m3u8"))
    return d


class Provider:
    """A loopback HTTP server that behaves like an IPTV provider, badly, on request.

    Routes are `(status, content_type, body)` triples or callables taking the handler. A route
    may also be a `pathlib.Path`, which serves that file or that directory tree.
    """

    def __init__(self, routes: dict, ua_gate: str | None = None):
        self.routes = routes
        self.ua_gate = ua_gate
        self.agents: list[str] = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _send(self, status, ctype, body, extra=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

            def do_GET(self):
                ua = self.headers.get("User-Agent", "")
                outer.agents.append(ua)
                if outer.ua_gate and outer.ua_gate not in ua:
                    # What a gated panel really does: not a clean 403 with an empty body, but a
                    # 403 carrying a page that explains itself to a human.
                    self._send(403, "text/html",
                               b"<html><body><h1>Forbidden</h1>"
                               b"<p>Player not supported by this service.</p></body></html>")
                    return
                path = self.path.split("?", 1)[0]
                route = outer.routes.get(path)
                if route is not None and not isinstance(route, pathlib.Path):
                    if callable(route):
                        route(self)
                    else:
                        status, ctype, body = route
                        self._send(status, ctype, body)
                    return
                for prefix, target in outer.routes.items():
                    if not (prefix.endswith("/") and isinstance(target, pathlib.Path)
                            and path.startswith(prefix)):
                        continue
                    name = path[len(prefix):]
                    f = (target / name).resolve()
                    # Serving a directory here is a convenience, not a webroot; refuse anything
                    # that escapes it rather than trusting the name.
                    if f.is_file() and target.resolve() in f.parents:
                        self._send(200, "video/mp2t", f.read_bytes())
                        return
                self._send(404, "text/plain", b"no such route")

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


#: Loopback is what the SSRF guard exists to forbid, so the harness needs the one switch that
#: exists for it. There is no environment variable and no request field that can set this --
#: see `Policy`'s docstring and `test_the_environment_cannot_turn_the_ssrf_check_off`.
LOCAL = Policy(allow_private=True)


def run_session(url: str, timeout: float = 30.0, policy: Policy | None = None,
                label: str = "Harness") -> sessions.Session:
    """Start a real session against the harness and wait for it to settle.

    Settled means: a playlist exists on disk (ffmpeg produced playable output), or the session
    failed. Both are results; a test that only waits for success cannot tell them apart.

    `ended` alone is **not** settled, and that distinction is not pedantry: a local fixture is
    delivered far faster than real time, so the pump reaches upstream EOF and marks the session
    `ended` while ffmpeg is still muxing the first segment. Breaking there would report every
    working stream as having produced nothing. `ended` counts only once ffmpeg has also exited.
    """
    mgr = sessions.SessionManager(root=pathlib.Path(tempfile.mkdtemp(prefix="streamer-run-")))
    s = mgr.start(url, label, policy or LOCAL)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if s.ready or s.state == "failed":
                break
            if s.state == "ended" and s.proc is not None and s.proc.poll() is not None:
                break
            time.sleep(0.1)
        # Give the pump a moment to record a failure that arrives just after the playlist.
        time.sleep(0.3)
        s.settled_ready = s.ready               # read before the directory is removed
        return s
    finally:
        mgr.shutdown()


# ============================================ defect 1: the User-Agent providers expect

class TestUserAgent(unittest.TestCase):
    """A stranger's User-Agent is the difference between a stream and a 403 for many panels."""

    def test_default_is_a_player_not_a_bot(self):
        self.assertIn("VLC", Policy().user_agent)
        self.assertIn("VLC", safefetch.DEFAULT_USER_AGENT)

    def test_a_gated_provider_serves_the_player_and_refuses_the_bot(self):
        """The whole defect, end to end, against a server that gates exactly as panels do."""
        with Provider({"/s1.ts": (200, "video/mp2t", b"\x47" + b"\0" * 187)},
                      ua_gate="VLC") as p:
            body, _ct, _t = safefetch.fetch(p.url("/s1.ts"), LOCAL)
            self.assertTrue(body.startswith(b"\x47"))
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"),
                                Policy(allow_private=True, user_agent=STRANGER_UA))
            self.assertIn("403", str(cm.exception))
            self.assertIn("VLC", p.agents[0])

    def test_the_agent_is_overridable_per_policy(self):
        with Provider({"/s1.ts": (200, "video/mp2t", b"\x47")}) as p:
            safefetch.fetch(p.url("/s1.ts"), Policy(allow_private=True, user_agent="Kodi/20"))
            self.assertEqual(p.agents[-1], "Kodi/20")

    def test_the_agent_is_overridable_from_the_environment(self):
        """Read once at import, so this has to be a fresh interpreter."""
        import os
        env = {**os.environ, "SYMONEURAL_STREAMER_USER_AGENT": "TiviMate/4.7.0 (Harness)"}
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from streamer.lib.safefetch import Policy\n"
             "print(Policy().user_agent)"
             % str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()))],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "TiviMate/4.7.0 (Harness)")

    def test_an_override_cannot_smuggle_headers(self):
        """A CRLF in the agent would inject headers into every upstream request."""
        import os
        prev = os.environ.get("SYMONEURAL_STREAMER_USER_AGENT")
        try:
            os.environ["SYMONEURAL_STREAMER_USER_AGENT"] = "VLC/3.0\r\nX-Evil: 1"
            ua = safefetch._default_user_agent()
            self.assertNotIn("\r", ua)
            self.assertNotIn("\n", ua)
            os.environ["SYMONEURAL_STREAMER_USER_AGENT"] = "   "
            self.assertIn("VLC", safefetch._default_user_agent())
        finally:
            if prev is None:
                os.environ.pop("SYMONEURAL_STREAMER_USER_AGENT", None)
            else:
                os.environ["SYMONEURAL_STREAMER_USER_AGENT"] = prev


# ============================================ defect 2: what the provider actually said

class TestUpstreamErrorBody(unittest.TestCase):
    """"You will come to a page from the server saying it's down" -- so say what it said."""

    def test_the_providers_message_reaches_the_error(self):
        page = (b"<html><body><h2>Subscription expired</h2>"
                b"<p>Your account ran out on 2026-01-01. Contact your reseller.</p>"
                b"</body></html>")
        with Provider({"/s1.ts": (403, "text/html", page)}) as p:
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"), LOCAL)
            msg = str(cm.exception)
            self.assertIn("403", msg)
            self.assertIn("Subscription expired", msg)
            self.assertIn("ran out on 2026-01-01", msg)

    def test_script_and_style_are_not_the_message(self):
        with Provider({"/s1.ts": (502, "text/html", OFFLINE_PAGE)}) as p:
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"), LOCAL)
            msg = str(cm.exception)
            self.assertIn("Channel temporarily offline", msg)
            self.assertNotIn("javascript", msg)
            self.assertNotIn("#c00", msg)

    def test_a_reflected_credential_is_scrubbed_out_of_the_excerpt(self):
        """The reason this was not done years ago, defused.

        Panels echo the requested path into their error pages, and an Xtream password lives in
        a path *segment*, where `redact()` cannot see it. `Scrubber.from_url` can, because it
        treats every segment as a secret whether or not it looks like one.
        """
        path = f"/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts"
        with Provider({path: lambda h: h._send(
                404, "text/html",
                f"<html><body>Stream not found: {h.path}</body></html>".encode())}) as p:
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url(path), LOCAL)
            msg = str(cm.exception)
            self.assertNotIn(SENTINEL_PASS, msg)
            self.assertNotIn(SENTINEL_USER, msg)
            self.assertIn("Stream not found", msg)     # the useful half survives

    def test_the_excerpt_is_bounded_and_single_line(self):
        body = ("<p>" + "verbose provider boilerplate. " * 200 + "</p>").encode()
        with Provider({"/s1.ts": (503, "text/html", body)}) as p:
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"), LOCAL)
            msg = str(cm.exception)
            self.assertLess(len(msg), 500)
            self.assertNotIn("\n", msg)
            self.assertNotIn("\r", msg)

    def test_a_dribbling_error_body_does_not_hold_the_thread(self):
        """`read`, not `read1`, would wait for a full buffer or EOF -- forever, here.

        A server that sends fifty bytes of its error page and then goes quiet satisfies
        `read_timeout` on every packet it does send. This must return in about as long as the
        response took, not in `read_timeout`.
        """
        def dribble(h):
            h.send_response(500)
            h.send_header("Content-Type", "text/html")
            h.send_header("Content-Length", "100000")
            h.end_headers()
            h.wfile.write(b"<html><body>upstream is having a bad day</body>")
            h.wfile.flush()
            time.sleep(6)

        with Provider({"/s1.ts": dribble}) as p:
            t0 = time.monotonic()
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"), Policy(allow_private=True, read_timeout=20.0))
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 4.0, f"the error read blocked for {elapsed:.1f}s")
            self.assertIn("bad day", str(cm.exception))

    def test_an_unreadable_error_body_still_reports_the_status(self):
        """A failure fetching the excerpt must never replace the fact we already have."""
        def hangup(h):
            h.send_response(451)
            h.send_header("Content-Type", "text/html")
            h.send_header("Content-Length", "5000")
            h.end_headers()
            h.close_connection = True

        with Provider({"/s1.ts": hangup}) as p:
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url("/s1.ts"), LOCAL)
            self.assertIn("451", str(cm.exception))

    def test_excerpt_helper_flattens_and_scrubs(self):
        out = safefetch.text_excerpt(
            b"<html>\n<body>\r\n  line one\n\n  line two &amp; three\x00\n</body></html>",
            Scrubber([SENTINEL_PASS]))
        self.assertEqual(out, "line one line two & three")

    def test_entities_cannot_reconstitute_markup_after_it_was_stripped(self):
        """Strip-then-unescape puts the tags back. The order has to be the other way round.

        A panel echoing the requested path through an HTML escaper -- which is the common,
        correct thing for it to do -- sends `Error: &lt;img src=x onerror=alert(1)&gt;`. There
        are no literal tags for the stripper to find, so unescaping afterwards reassembles them
        into the message. The excerpt is plain text and must stay plain text without relying on
        whoever renders it knowing that.
        """
        out = safefetch.text_excerpt(
            b"<html><body>Error: &lt;img src=x onerror=alert(1)&gt; not found</body></html>")
        self.assertNotIn("<", out)
        self.assertNotIn(">", out)
        self.assertIn("not found", out)
        # Double-encoded input must not be unescaped twice into live markup either.
        twice = safefetch.text_excerpt(b"<p>&amp;lt;script&amp;gt;</p>")
        self.assertNotIn("<script", twice)

    def test_the_playlist_route_does_not_echo_a_credential_from_an_error_page(self):
        """The one route where safefetch's own scrub is the only layer.

        `load_playlist` puts `str(exc)` straight into an `HTTPException` detail with no second
        scrubbing, so if the excerpt were not already clean it would come back in a 502 body.
        The existing end-to-end credential test only reaches this route with a loopback URL,
        which dies as `BlockedURL` at 400 and never touches the excerpt path at all.
        """
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:                                  # pragma: no cover
            self.skipTest(f"TestClient unavailable: {exc}")
        path = f"/get.php?username={SENTINEL_USER}&password={SENTINEL_PASS}&type=m3u"
        with Provider({"/get.php": lambda h: h._send(
                403, "text/html",
                f"<html><body>Forbidden for {h.path}</body></html>".encode())}) as p:
            app = FastAPI()
            app.include_router(routes.router, prefix="/api/streamer")
            client = TestClient(app, raise_server_exceptions=False)
            # The route builds its own `Policy()`, which forbids loopback -- so this asserts on
            # the excerpt path through `safefetch` directly, with the route's own scrubbing
            # (none) applied on top.
            with self.assertRaises(safefetch.FetchError) as cm:
                safefetch.fetch(p.url(path), LOCAL)
            detail = f"could not fetch that playlist: {cm.exception}"
            self.assertNotIn(SENTINEL_PASS, detail)
            self.assertNotIn(SENTINEL_USER, detail)
            self.assertIn("Forbidden", detail)
            r = client.post("/api/streamer/playlist", json={"url": p.url(path)})
            self.assertNotIn(SENTINEL_PASS, r.text)
            self.assertNotIn(SENTINEL_USER, r.text)


# ============================================ defect 3: a web page is not a stream

class TestErrorPageSniffing(unittest.TestCase):
    def test_ts_sync_is_a_lockstep_test_not_a_byte_search(self):
        """0x47 is the letter G. Searching for one byte calls every English page a stream."""
        self.assertLess(sessions.ts_sync_offset(b"Good Gateway: the Great Green Gate" * 40), 0)
        real = b"".join(b"\x47" + bytes(187) for _ in range(4))
        self.assertEqual(sessions.ts_sync_offset(real), 0)
        self.assertEqual(sessions.ts_sync_offset(b"\x00\x00" + real), 2)

    def test_markup_is_conclusive_and_a_texty_header_alone_is_not(self):
        real = b"".join(b"\x47" + bytes(187) for _ in range(4))
        self.assertTrue(sessions.looks_like_error_page("text/html", OFFLINE_PAGE))
        self.assertTrue(sessions.looks_like_error_page("video/mp2t", OFFLINE_PAGE))
        self.assertTrue(sessions.looks_like_error_page("text/plain", b"channel offline"))
        self.assertTrue(sessions.looks_like_error_page(
            "application/json", b'{"error":"maximum connections reached"}'))
        # The misconfiguration that must NOT be treated as an error page.
        self.assertFalse(sessions.looks_like_error_page("text/html", real))
        self.assertFalse(sessions.looks_like_error_page("video/mp2t", real))
        self.assertFalse(sessions.looks_like_error_page("", real))

    def test_a_fragmented_mp4_segment_is_not_an_error_page(self):
        """fMP4 has no 0x47 sync pattern, so a mislabelled one would fail the texty rule."""
        for box in (b"ftyp", b"styp", b"moof", b"sidx"):
            with self.subTest(box=box):
                self.assertFalse(sessions.looks_like_error_page(
                    "text/plain", b"\x00\x00\x00\x18" + box + b"iso6" + bytes(64)))

    @needs_ffmpeg
    def test_an_offline_page_at_200_is_reported_as_the_providers_words(self):
        """The blank-screen bug. HTTP 200, `text/html`, and it used to go straight to ffmpeg."""
        with Provider({"/s1.ts": (200, "text/html", OFFLINE_PAGE)}) as p:
            s = run_session(p.url("/s1.ts"))
            self.assertEqual(s.state, "failed")
            self.assertIn("Channel temporarily offline", s.public()["error"])
            self.assertNotIn("stream-copy", s.public()["error"])

    @needs_ffmpeg
    def test_a_real_stream_mislabelled_text_html_still_plays(self):
        """The counter-test, and the reason the sniff is not `ctype.startswith("text/")`.

        Providers behind a misconfigured nginx serve real MPEG-TS as `text/html` constantly. A
        content-type-only rule would break every one of those working streams, which is the
        exact inverse of the deliverable.
        """
        ts = (media() / "clean.ts").read_bytes()
        with Provider({"/s1.ts": (200, "text/html", ts)}) as p:
            s = run_session(p.url("/s1.ts"))
            self.assertTrue(s.settled_ready,
                            f"a real stream was refused: {s.state} {s.error!r}")
            self.assertGreater(s.bytes_in, 10000)


# ============================================ defect 4: AES-128 HLS

class TestHlsKeyParsing(unittest.TestCase):
    def test_key_attributes_are_exposed_not_reduced_to_a_boolean(self):
        pl = m3u.parse_hls(
            '#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:7\n'
            '#EXT-X-KEY:METHOD=AES-128,URI="https://k.example/a.key?x=1",IV=0x0F0F0F0F0F0F0F0F'
            '0F0F0F0F0F0F0F0F\n#EXTINF:2,\na.ts\n')
        seg = pl.segments[0]
        self.assertTrue(pl.encrypted)
        self.assertEqual(seg.key.method, "AES-128")
        self.assertEqual(seg.key.uri, "https://k.example/a.key?x=1")
        self.assertEqual(seg.key.iv.lower(), "0x" + "0f" * 16)
        self.assertEqual(seg.key.keyformat, "identity")

    def test_a_key_applies_from_where_it_appears_and_none_turns_it_off(self):
        """Rotation is normal and a playlist-level flag cannot express it."""
        pl = m3u.parse_hls(
            "#EXTM3U\n#EXTINF:2,\nclear.ts\n"
            '#EXT-X-KEY:METHOD=AES-128,URI="k1"\n#EXTINF:2,\none.ts\n'
            '#EXT-X-KEY:METHOD=AES-128,URI="k2"\n#EXTINF:2,\ntwo.ts\n'
            "#EXT-X-KEY:METHOD=NONE\n#EXTINF:2,\nclear2.ts\n")
        self.assertEqual([s.key.uri for s in pl.segments], ["", "k1", "k2", ""])
        self.assertEqual([s.key.encrypted for s in pl.segments],
                         [False, True, True, False])
        self.assertEqual([k.uri for k in pl.keys], ["k1", "k2"])

    def test_session_key_announces_but_does_not_encrypt(self):
        pl = m3u.parse_hls('#EXTM3U\n#EXT-X-SESSION-KEY:METHOD=AES-128,URI="k"\n'
                           "#EXTINF:2,\na.ts\n")
        self.assertFalse(pl.encrypted)

    def test_keyformat_is_carried_so_drm_can_be_told_from_encryption(self):
        pl = m3u.parse_hls(
            '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="skd://x",'
            'KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n#EXTINF:2,\na.ts\n')
        self.assertEqual(pl.segments[0].key.keyformat,
                         "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed")


class TestAesRefusals(unittest.TestCase):
    """METHOD is an allow-list. Everything not `AES-128` is refused **by name**."""

    def refuse(self, playlist: str) -> str:
        mgr = sessions.SessionManager()
        with self.assertRaises(sessions.StreamerError) as cm:
            mgr._reject_unsupported_encryption(m3u.parse_hls(playlist))
        return str(cm.exception)

    def test_sample_aes_is_still_refused_and_named(self):
        """The refusal that must survive.

        SAMPLE-AES encrypts NAL unit payloads and leaves the container in the clear.
        CBC-decrypting the whole segment destroys the parts that were never encrypted and
        produces something ffmpeg will half-accept -- silent corruption where there used to be
        an honest "cannot decrypt".
        """
        msg = self.refuse('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="k"\n#EXTINF:2,\na.ts\n')
        self.assertIn("SAMPLE-AES", msg)

    def test_unknown_methods_are_refused_rather_than_assumed_to_be_aes_128(self):
        for method in ("AES-256", "SAMPLE-AES-CTR", "AES-128-CTR", "CENC", "NOVEL-SCHEME"):
            with self.subTest(method=method):
                msg = self.refuse(f'#EXTM3U\n#EXT-X-KEY:METHOD={method},URI="k"\n'
                                  "#EXTINF:2,\na.ts\n")
                self.assertIn(method, msg)

    def test_drm_wearing_an_aes_128_method_is_refused(self):
        msg = self.refuse('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="skd://x",'
                          'KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n'
                          "#EXTINF:2,\na.ts\n")
        self.assertIn("DRM", msg)

    def test_a_hostile_method_string_cannot_write_arbitrary_text_into_a_message(self):
        msg = self.refuse('#EXTM3U\n#EXT-X-KEY:METHOD="<script>alert(1)</script>",URI="k"\n'
                          "#EXTINF:2,\na.ts\n")
        self.assertNotIn("<", msg)
        self.assertNotIn(">", msg)

    def test_plain_aes_128_is_not_refused(self):
        mgr = sessions.SessionManager()
        mgr._reject_unsupported_encryption(m3u.parse_hls(
            '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF:2,\na.ts\n'))

    def test_the_iv_falls_back_to_the_media_sequence_number(self):
        """RFC 8216 5.2. Getting this wrong decrypts to noise exactly like a wrong key."""
        pl = m3u.parse_hls('#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:9\n'
                           '#EXT-X-KEY:METHOD=AES-128,URI="k"\n#EXTINF:2,\na.ts\n')
        self.assertEqual(sessions._segment_iv(pl.segments[0]),
                         (9).to_bytes(16, "big"))
        pl2 = m3u.parse_hls('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k",IV=0x'
                            + "0f" * 16 + "\n#EXTINF:2,\na.ts\n")
        self.assertEqual(sessions._segment_iv(pl2.segments[0]), b"\x0f" * 16)

    def test_a_key_uri_goes_through_the_ssrf_validator(self):
        """A key URI is a third-party URL like any other. `http://127.0.0.1/` must die."""
        mgr = sessions.SessionManager()
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                             scrub=Scrubber(), policy=Policy())      # production policy
        with self.assertRaises(BlockedURL):
            mgr._segment_key(s, "http://93.184.216.34/a/index.m3u8",
                             m3u.HlsKey(method="AES-128", uri="http://127.0.0.1:8800/k.key"),
                             {})


@needs_ffmpeg
class TestAesPlayback(unittest.TestCase):
    """Real AES-128 HLS produced by ffmpeg, decrypted here, played by ffmpeg."""

    def _serve(self, subdir: str, key_bytes: bytes | None = None) -> Provider:
        d = media() / subdir
        key = media() / "enc.key"
        routes = {"/enc.key": (200, "application/octet-stream",
                               key_bytes if key_bytes is not None else key.read_bytes()),
                  "/index.m3u8": (200, "application/vnd.apple.mpegurl",
                                  (d / "index.m3u8").read_bytes()),
                  "/": d}
        return Provider(routes)

    def test_aes_128_with_a_sequence_iv_plays(self):
        with self._serve("aes") as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r} / {s.transcoder_error!r}")
            self.assertEqual(s.mode, "hls")
            self.assertGreater(s.bytes_in, 10000)

    def test_aes_128_with_an_explicit_iv_plays(self):
        with self._serve("aesiv") as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r} / {s.transcoder_error!r}")
            self.assertGreater(s.bytes_in, 10000)

    def test_the_wrong_key_fails_honestly_instead_of_feeding_ffmpeg_noise(self):
        """The check that makes lenient PKCS7 unpadding safe.

        A wrong key does not raise: AES-CBC produces 16-byte blocks of noise, the unpadder
        cheerfully strips a random tail, and ffmpeg reports that *it* could not read the source.
        The decrypted bytes are checked for transport-stream sync, once, so a key mismatch is
        reported as a key mismatch.
        """
        with self._serve("aes", key_bytes=b"\xff" * 16) as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertEqual(s.state, "failed")
            self.assertIn("key", s.public()["error"].lower())
            self.assertNotIn("stream-copy", s.public()["error"])

    def test_a_key_of_the_wrong_length_is_refused_before_anything_is_decrypted(self):
        with self._serve("aes", key_bytes=b"short") as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertEqual(s.state, "failed")
            self.assertIn("16", s.public()["error"])

    def test_a_rotated_key_is_checked_too_not_only_the_first(self):
        """The reason the sync check is keyed on the key URI rather than being a bool.

        HLS rotates keys mid-stream, which is why `HlsKey` hangs off the segment rather than the
        playlist. A check that fired once per session would validate the first key and wave the
        second one straight through -- and a wrong second key is exactly the silent corruption
        the check exists to prevent.
        """
        d = media() / "aes"
        lines = (d / "index.m3u8").read_text().splitlines()
        cut = max(i for i, line in enumerate(lines) if line.startswith("#EXTINF"))
        lines.insert(cut, '#EXT-X-KEY:METHOD=AES-128,URI="bad.key"')
        with Provider({"/index.m3u8": (200, "application/vnd.apple.mpegurl",
                                       ("\n".join(lines) + "\n").encode()),
                       "/enc.key": (200, "application/octet-stream",
                                    (media() / "enc.key").read_bytes()),
                       "/bad.key": (200, "application/octet-stream", bytes(16)),
                       "/": d}) as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertEqual(s.state, "failed")
            self.assertIn("key", s.public()["error"].lower())

    def test_a_segment_answered_with_a_page_is_reported_as_the_page(self):
        """The playlist was fine; the channel died before the segment was asked for."""
        d = media() / "hls"
        lines = (d / "index.m3u8").read_text().splitlines()
        first = next(i for i, line in enumerate(lines) if not line.startswith("#") and line)
        lines[first] = "dead.ts"
        with Provider({"/index.m3u8": (200, "application/vnd.apple.mpegurl",
                                       ("\n".join(lines) + "\n").encode()),
                       "/dead.ts": (200, "text/html", OFFLINE_PAGE),
                       "/": d}) as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertEqual(s.state, "failed")
            self.assertIn("Channel temporarily offline", s.public()["error"])

    def test_a_variant_playlist_answered_with_a_page_is_reported_as_the_page(self):
        with Provider({"/master.m3u8": (
                200, "application/vnd.apple.mpegurl",
                b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1200000\nvariant.m3u8\n"),
                "/variant.m3u8": (200, "text/html", OFFLINE_PAGE)}) as p:
            s = run_session(p.url("/master.m3u8"))
            self.assertEqual(s.state, "failed")
            self.assertIn("Channel temporarily offline", s.public()["error"])
            self.assertNotIn("contained no segments", s.public()["error"])

    def test_unencrypted_hls_still_plays(self):
        """The regression the encryption work could most easily have caused."""
        d = media() / "hls"
        with Provider({"/index.m3u8": (200, "application/vnd.apple.mpegurl",
                                       (d / "index.m3u8").read_bytes()),
                       "/": d}) as p:
            s = run_session(p.url("/index.m3u8"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r}")
            self.assertGreater(s.bytes_in, 10000)


class TestAesPrimitives(unittest.TestCase):
    def test_round_trip_and_padding(self):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except Exception as exc:                                   # pragma: no cover
            self.skipTest(f"cryptography unavailable: {exc}")
        key, iv = bytes(range(16)), b"\x0f" * 16
        plain = b"".join(b"\x47" + bytes(187) for _ in range(3))
        pad = 16 - (len(plain) % 16)
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        blob = enc.update(plain + bytes([pad]) * pad) + enc.finalize()
        self.assertEqual(sessions._decrypt_segment(blob, key, iv), plain)

    def test_a_partial_block_is_refused_not_guessed_at(self):
        with self.assertRaises(sessions.StreamerError):
            sessions._decrypt_segment(b"\x00" * 33, bytes(16), bytes(16))


# ============================================ defect 5: HEVC, the honest blank screen

class TestCodecReporting(unittest.TestCase):
    def test_the_matcher_is_an_allowlist(self):
        self.assertEqual(sessions.match_video_codec(
            "[info]   Stream #0:0[0x100]: Video: hevc (Main) ([36][0][0][0]), yuv420p"), "hevc")
        self.assertEqual(sessions.match_video_codec(
            "[info]   Stream #0:0[0x100]: Video: h264 (Constrained Baseline)"), "h264")
        self.assertEqual(sessions.match_video_codec("[info] Stream mapping:"), "")
        self.assertEqual(sessions.match_video_codec(""), "")

    def test_a_fabricated_stderr_line_cannot_publish_arbitrary_text(self):
        """The reason the codec is matched rather than captured.

        ffmpeg's stderr is written by a program we do not control and can quote its input. If
        `vcodec` were "the token after `Video:`", a hostile stream's metadata would be echoed
        straight into the document handed to the browser.
        """
        line = f"[info]   Stream #0:0: Video: {SENTINEL_PASS} (Main)"
        self.assertEqual(sessions.match_video_codec(line), "")
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                             scrub=Scrubber(), policy=Policy())
        s.vcodec = sessions.match_video_codec(line)
        import json
        self.assertNotIn(SENTINEL_PASS, json.dumps(s.public()))

    def test_public_document_carries_both_codecs(self):
        """Video AND audio. The audio half is the one that was missing and it cost a real bug.

        This assertion used to be `assertNotIn("acodec", ...)`, on the reasoning that an unused
        field is a field nobody is checking. That was wrong, and a measured failure is why: a
        channel reported `state: live`, `vcodec: h264`, 87 MB pulled from the provider over five
        minutes and every indicator on the box green, while the browser decoded ZERO frames --
        because MSE refuses the whole segment when it will not take the AUDIO track, and Chrome
        will not take AC-3. The page could only see `vcodec`, so it had nothing to say and the
        visitor got a black rectangle with no explanation.
        """
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                             scrub=Scrubber(), policy=Policy())
        self.assertIn("vcodec", s.public())
        self.assertEqual(s.public()["vcodec"], "")
        self.assertIn("acodec", s.public())
        self.assertEqual(s.public()["acodec"], "")

    def test_a_hostile_audio_codec_cannot_reach_the_public_document(self):
        """Same allow-list property as `vcodec`, now that `acodec` is published too.

        ffmpeg's stderr can quote its input, so the token is matched against `AUDIO_CODECS` and
        anything unrecognised becomes "". Publishing a field that carried ffmpeg's text verbatim
        would have handed a hostile stream a channel into the document the browser is given.
        """
        line = f"[info]   Stream #0:1: Audio: {SENTINEL_PASS} (LC), 48000 Hz, stereo"
        self.assertEqual(sessions._match_audio_codec(line), "")
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                             scrub=Scrubber(), policy=Policy())
        s.acodec = sessions._match_audio_codec(line)
        import json
        self.assertNotIn(SENTINEL_PASS, json.dumps(s.public()))

    def test_a_real_audio_codec_is_reported(self):
        line = "[info]   Stream #0:1: Audio: ac3 (AC-3 / 0x332D4341), 48000 Hz, 5.1, fltp"
        self.assertEqual(sessions._match_audio_codec(line), "ac3")

    @needs_ffmpeg
    def test_hevc_is_reported_while_everything_else_looks_healthy(self):
        """The whole point. `-c copy` succeeds, the playlist is written, the session is live --
        and no browser decodes HEVC in MSE, so the visitor sees a black rectangle. `vcodec` is
        the only field that separates this from a working stream, and a client must read it
        even when the state says `live`.
        """
        with Provider({"/s1.ts": (200, "video/mp2t", (media() / "hevc.ts").read_bytes())}) as p:
            s = run_session(p.url("/s1.ts"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r}")
            self.assertEqual(s.public()["vcodec"], "hevc")

    @needs_ffmpeg
    def test_h264_is_reported_too_so_the_field_means_something(self):
        with Provider({"/s1.ts": (200, "video/mp2t", (media() / "clean.ts").read_bytes())}) as p:
            s = run_session(p.url("/s1.ts"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r}")
            self.assertEqual(s.public()["vcodec"], "h264")

    @needs_ffmpeg
    def test_transcoder_error_still_holds_an_error_at_the_raised_loglevel(self):
        """The regression raising the loglevel would otherwise have caused.

        `transcoder_error` was "the last line ffmpeg printed", which at `-loglevel error` was
        the same as "the last error". At `info` it would have become progress output, and every
        real failure would have become unexplainable. `level+` markers are what keep them apart.
        """
        junk = bytes(range(256)) * 400            # not a transport stream, not markup
        with Provider({"/s1.ts": (200, "video/mp2t", junk)}) as p:
            s = run_session(p.url("/s1.ts"), timeout=20)
            self.assertFalse(s.settled_ready)
            self.assertTrue(s.transcoder_error, "ffmpeg's failure was not recorded")
            self.assertNotIn("frame=", s.transcoder_error)
            self.assertNotIn("[info]", s.transcoder_error)

    @needs_ffmpeg
    def test_a_healthy_stream_records_no_transcoder_error(self):
        """The other half, and the half that actually regresses.

        A stream that fails instantly has an error as its last line either way, so that case
        cannot tell whether the severity filter is doing anything. A stream that *works* can:
        ffmpeg's last line on a healthy run is `frame= 40 fps=0.0 ... speed=4.43e+03x`, and
        without the filter that string would be sitting in `transcoder_error` -- a recorded
        failure on a session that never failed, and the field would be worthless for
        diagnosing the ones that did. (The `[info]` lines also quote our own session directory
        paths, which is a second reason not to keep them.)
        """
        with Provider({"/s1.ts": (200, "video/mp2t", (media() / "clean.ts").read_bytes())}) as p:
            s = run_session(p.url("/s1.ts"))
            self.assertTrue(s.settled_ready, f"{s.state}: {s.error!r}")
            self.assertFalse(s.transcoder_error,
                             f"a working stream recorded a failure: {s.transcoder_error!r}")


# ============================================ defect 7: movies are missing

class TestClassificationFromGroupTitle(unittest.TestCase):
    """The real "the Movies category is empty" root cause on the plain-M3U path."""

    def kinds(self, text: str) -> list[str]:
        return [c.kind for c in m3u.parse_m3u(text)[0]]

    def test_a_film_with_no_movie_segment_is_found_by_its_group(self):
        """The defect, exactly. No `/movie/` anywhere in the URL; nothing but the group says."""
        self.assertEqual(self.kinds(
            '#EXTINF:-1 group-title="VOD | Movies",The Example Film\n'
            "http://p.example:8080/12345.mp4\n"), ["vod"])

    def test_group_vocabulary(self):
        for group, expect in [
            ("VOD | Movies", "vod"), ("Movies", "vod"), ("FILMS - Action", "vod"),
            ("Cinema HD", "vod"), ("Peliculas Latino", "vod"), ("Videoteca", "vod"),
            ("TV Series", "series"), ("Series | Netflix", "series"),
            ("Boxsets", "series"), ("Staffel 1", "series"),
            ("UK | Entertainment", "live"), ("Sports", "live"), ("News", "live"),
            ("Moviestar Plus", "live"),          # not a word boundary; must not match
            ("", "live"),
        ]:
            with self.subTest(group=group):
                self.assertEqual(self.kinds(
                    f'#EXTINF:-1 group-title="{group}",X\nhttp://p.example/1.mp4\n'),
                    [expect])

    def test_an_explicit_url_classification_is_never_overridden(self):
        """The URL is the provider telling us what it is. A group title never outranks it."""
        self.assertEqual(self.kinds(
            '#EXTINF:-1 group-title="VOD | Movies",Live Movie Channel\n'
            "http://p.example/live/u/p/1.ts\n"), ["live"])
        self.assertEqual(self.kinds(
            '#EXTINF:-1 group-title="UK | Sport",A Film\n'
            "http://p.example/movie/u/p/1.mp4\n"), ["vod"])

    def test_the_stated_cost_is_real_and_accepted(self):
        """A genuinely linear channel in a film-named group now counts as vod.

        Documented in `_classify` rather than hidden. It moves one always-on channel into the
        Movies list instead of hiding every actual film from it.
        """
        self.assertEqual(self.kinds(
            '#EXTINF:-1 group-title="24/7 Movies",Action Movies 24/7\n'
            "http://p.example/1.ts\n"), ["vod"])

    def test_extgrp_groups_classify_too(self):
        self.assertEqual(self.kinds(
            "#EXTGRP:Movies\n#EXTINF:7200,A Film\nhttp://p.example/1.mkv\n"), ["vod"])

    def test_a_plain_channel_list_is_still_live(self):
        """The regression this change could most easily cause: everything becoming vod."""
        self.assertEqual(self.kinds(FIXTURE), ["live", "live", "vod", "live", "series"])


# ============================================ defect 8: measured, not guessed

class TestTuneDeadline(unittest.TestCase):
    def test_the_wait_covers_a_realistically_paced_stream(self):
        """Measured on this machine: time to first playlist is 2.5 s at 8 Mb/s, 9.7 s at
        2 Mb/s and 24.1 s at 0.8 Mb/s, feeding the exact argv `_spawn` builds. The old 10 s
        missed an ordinary 2 Mb/s stream by a fraction of a second. See `routes.TUNE_WAIT_SECONDS`.

        This deliberately does *not* assert the wait is shorter than `sessions.IDLE_TIMEOUT`.
        It once did, and that assertion went stale the moment the wait grew past 20 s. The
        invariant it was guarding -- the reaper must not drop a session while a request is still
        waiting on it -- moved rather than disappeared: the wait loop calls `MANAGER.touch()` on
        every poll (`routes.py:357`), which resets the `last_seen` the reaper reads
        (`sessions.py:974`), so the wait is *designed* to outlive the idle timeout. Coupling the
        two constants was also wrong on its own terms, because `IDLE_TIMEOUT` is env-tunable from
        5 to 600: `SYMONEURAL_STREAMER_IDLE_TIMEOUT=5` would have failed this test with no bug
        present. The residual hazard -- a session that really did die during a long wait -- is
        covered by the next test, which is where that coverage belongs.
        """
        self.assertGreaterEqual(routes.TUNE_WAIT_SECONDS, 20.0)
        self.assertLessEqual(routes.TUNE_WAIT_SECONDS, 60.0)

    def test_the_wait_keeps_the_session_alive_while_it_waits(self):
        """Why `TUNE_WAIT_SECONDS` (25 s) is allowed to exceed `IDLE_TIMEOUT` (12 s).

        This test replaces an assertion that read `TUNE_WAIT_SECONDS < IDLE_TIMEOUT + 1`.
        That was already false in the commit that introduced it -- `979c3dc` raised the wait
        to 25 s and dropped the idle timeout 45 -> 12 s in one change -- and it stayed red
        because it was checking the wrong thing. Two numbers being ordered was never the
        protection; the protection is the `MANAGER.touch(session.id)` inside the wait loop.
        A client blocked on `/tune` *is* activity on the session, so the reaper, which
        measures idleness from the last player request, never sees the session go quiet.

        Assert the mechanism, not the arithmetic: over a wait, the loop must touch
        repeatedly. One touch at the top would leave the session ageing again for the rest of
        the wait, which is the bug the ordering assertion was groping at.
        """
        class Waiting:
            """A manager whose session never becomes ready, and which counts the touches."""

            def __init__(self):
                self.touches = 0
                self.session = sessions.Session(
                    id="slow", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                    scrub=Scrubber(), policy=Policy())

            def start(self, *a, **k):
                return self.session

            def touch(self, sid):
                self.touches += 1
                return self.session

            def get(self, sid):
                return self.session           # still there, just not ready

            def stop_session(self, sid):
                return False

            def list(self):
                return []

            def reap(self):
                return 0

        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:                                  # pragma: no cover
            self.skipTest(f"TestClient unavailable: {exc}")

        app = FastAPI()
        app.include_router(routes.router, prefix="/api/streamer")
        client = TestClient(app, raise_server_exceptions=False)
        mgr = Waiting()
        real_mgr, real_wait = routes.MANAGER, routes.TUNE_WAIT_SECONDS
        try:
            routes.MANAGER = mgr
            routes.TUNE_WAIT_SECONDS = 1.0      # ~4 iterations at the loop's 0.25 s sleep
            r = client.post("/api/streamer/tune", json={"url": "http://p.example/1.ts"})
        finally:
            routes.MANAGER, routes.TUNE_WAIT_SECONDS = real_mgr, real_wait
        self.assertEqual(r.status_code, 200)
        self.assertIn("poll the session", r.text)
        # At the real 25 s wait this is ~100 touches, none of them more than 0.25 s apart, so
        # a 12 s idle timeout is never approached. Two is enough to prove it is per-iteration.
        self.assertGreaterEqual(mgr.touches, 2)

    def test_a_long_wait_never_hands_back_a_session_that_is_already_gone(self):
        """The window the longer wait widened.

        The reaper drops a session the moment its ffmpeg exits, so a 25 s wait can outlive the
        thing it is waiting for. Returning `{"note": "poll the session"}` for an id whose
        `GET /session/{sid}` answers 404 makes a dead stream look like a broken streamer -- the
        exact confusion this module exists to remove. It must be a 502 with a reason instead.
        """
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except Exception as exc:                                  # pragma: no cover
            self.skipTest(f"TestClient unavailable: {exc}")

        class Vanishing:
            """A manager whose session is reaped while `/tune` is still waiting for it."""

            def __init__(self):
                self.session = sessions.Session(
                    id="gone", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                    scrub=Scrubber(), policy=Policy())
                self.session.error = "the transcoder exited before the stream ended"

            def start(self, *a, **k):
                return self.session

            def touch(self, sid):
                return None

            def get(self, sid):
                return None                       # already reaped

            def stop_session(self, sid):
                return False

            def list(self):
                return []

            def reap(self):
                return 0

        app = FastAPI()
        app.include_router(routes.router, prefix="/api/streamer")
        client = TestClient(app, raise_server_exceptions=False)
        real_mgr, real_wait = routes.MANAGER, routes.TUNE_WAIT_SECONDS
        try:
            routes.MANAGER = Vanishing()
            routes.TUNE_WAIT_SECONDS = 0.5
            r = client.post("/api/streamer/tune", json={"url": "http://p.example/1.ts"})
        finally:
            routes.MANAGER, routes.TUNE_WAIT_SECONDS = real_mgr, real_wait
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("poll the session", r.text)


# ============================================ the credential rules, against the new fields

class TestNewFieldsCarryNoCredential(unittest.TestCase):
    def test_public_has_no_field_that_could_hold_a_url(self):
        """Re-stated for the fields added by this work. `vcodec` is allow-listed; that is the
        entire argument for publishing something derived from ffmpeg's output."""
        s = sessions.Session(
            id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
            scrub=Scrubber.from_url(
                f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts"),
            policy=Policy(),
            url=f"http://p.example/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts")
        s.state = "failed"
        s.transcoder_error = f"pipe:0: {SENTINEL_PASS}"
        s.vcodec, s.acodec = "hevc", "ac3"
        s.error = s.scrub(f"upstream returned HTTP 403 - Stream not found: "
                          f"/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts")
        import json
        doc = json.dumps(s.public())
        self.assertNotIn(SENTINEL_PASS, doc)
        self.assertNotIn(SENTINEL_USER, doc)
        self.assertIn("hevc", doc)

    def test_an_error_page_excerpt_from_a_pasted_m3u_url_is_scrubbed(self):
        """The path with no registered secrets, which is why `from_url` is load-bearing.

        A visitor pastes an Xtream-exported M3U and calls `/tune` with no username or password
        field at all. Nothing registers a secret. The credential is in a path segment, invisible
        to `redact()`. If the provider reflects the path into its error page, only
        `Scrubber.from_url` stands between that and the response body.
        """
        path = f"/live/{SENTINEL_USER}/{SENTINEL_PASS}/1.ts"
        with Provider({path: lambda h: h._send(
                403, "text/html",
                f"<html><body>Forbidden: {h.path}</body></html>".encode())}) as p:
            mgr = sessions.SessionManager(
                root=pathlib.Path(tempfile.mkdtemp(prefix="streamer-run-")))
            try:
                s = mgr.start(p.url(path), "Test", LOCAL)     # no scrubber passed, as in a paste
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline and s.state not in ("failed", "ended"):
                    time.sleep(0.1)
                import json
                doc = json.dumps(s.public())
                self.assertEqual(s.state, "failed")
                self.assertNotIn(SENTINEL_PASS, doc)
                self.assertNotIn(SENTINEL_USER, doc)
                self.assertIn("403", doc)
            finally:
                mgr.shutdown()


class TestCatalogueSize(unittest.TestCase):
    """A movie catalogue is an order of magnitude bigger than a channel list.

    The live bug these tests pin: `load_channels` passed the caller's `Policy` straight to the
    catalogue fetches, and `Policy.max_bytes` is 24 MiB because it was sized for an M3U
    playlist. Against a real panel, live was 3.77 MB and series 6.43 MB -- both under -- while
    movies were 27.57 MB across 31,888 titles, and over. Live TV and Series filled the page and
    Movies stayed empty. The fake panel below reproduces that shape at a thousandth of the size:
    a byte ceiling far under the VOD list and far over the live one.
    """

    VOD_ROWS = 400          # ~40 KB of JSON: over SMALL_CEILING, under CATALOGUE_MAX_BYTES
    SMALL_CEILING = 8 * 1024

    def setUp(self):
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def _json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                action = (q.get("action") or [""])[0]
                outer.seen.append(action)
                if action == "get_live_streams":
                    self._json([{"stream_id": 1, "name": "News One", "category_id": "1"}])
                elif action == "get_vod_streams":
                    # `plot` stands in for the metadata a real panel sends and this module
                    # discards -- it is why a title costs ~900 bytes on the wire.
                    self._json([{"stream_id": 1000 + i, "name": f"Film {i}",
                                 "category_id": "9", "container_extension": "mkv",
                                 "plot": "x" * 60} for i in range(outer.VOD_ROWS)])
                elif action == "get_series":
                    self._json([{"series_id": 7, "name": "A Show", "category_id": "5"}])
                elif action.endswith("_categories"):
                    self._json([{"category_id": "1", "category_name": "News"},
                                {"category_id": "9", "category_name": "Movies"},
                                {"category_id": "5", "category_name": "Drama"}])
                else:
                    self._json({"user_info": {"auth": 1, "status": "Active"},
                                "server_info": {"timezone": "UTC"}})

            def log_message(self, *a):
                pass

        self.seen: list[str] = []
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        # An IP literal needs no DNS, so no resolver has to be injected; `allow_private` is the
        # only concession, and it is what that flag exists for (see Policy's docstring).
        self.creds = xtream.XtreamCreds(f"http://127.0.0.1:{self.port}",
                                        SENTINEL_USER, SENTINEL_PASS)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def kinds_of(self, entries):
        return {e["kind"] for e in entries}

    def test_neither_default_caps_a_catalogue_any_more(self):
        """Both ceilings are gone by owner's instruction. `0` means uncapped, not "zero bytes".

        Worth an explicit test because `0` is a falsy sentinel: a future `if policy.max_bytes >
        0` style rewrite of the read loop would turn "no limit" into "no data" and every
        catalogue would come back empty.
        """
        self.assertEqual(xtream.CATALOGUE_MAX_BYTES, 0)
        self.assertEqual(Policy().max_bytes, 0)
        body, _ct, _t = safefetch.fetch(
            f"http://127.0.0.1:{self.port}/player_api.php?action=get_vod_streams",
            Policy(allow_private=True))
        self.assertGreater(len(body), self.SMALL_CEILING,
                           "an uncapped fetch returned less than the old small ceiling")

    def test_a_catalogue_over_the_playlist_ceiling_still_loads(self):
        """The regression proper: a narrow caller policy must not narrow the catalogue fetch."""
        pol = Policy(allow_private=True, max_bytes=self.SMALL_CEILING)
        entries, notes = xtream.load_channels(self.creds, ("live", "vod", "series"), pol)
        self.assertEqual(self.kinds_of(entries), {"live", "vod", "series"}, notes)
        self.assertEqual(len([e for e in entries if e["kind"] == "vod"]), self.VOD_ROWS)
        self.assertEqual(notes, [])

    def test_a_catalogue_over_the_real_ceiling_does_not_blame_the_panel(self):
        """When this box is the one refusing, the note must say so -- and must still say live."""
        pol = Policy(allow_private=True)
        with unittest.mock.patch.object(xtream, "CATALOGUE_MAX_BYTES", self.SMALL_CEILING):
            entries, notes = xtream.load_channels(self.creds, ("live", "vod", "series"), pol)
        # Live and Series are under the ceiling and arrive; only Movies is over it. That is the
        # reported symptom exactly, and it is what makes the note the whole explanation.
        self.assertEqual(self.kinds_of(entries), {"live", "series"})
        joined = " ".join(notes)
        self.assertIn("vod", joined)
        self.assertIn("this box will load", joined)
        self.assertNotIn("unavailable on this panel", joined)
        self.assertNotIn(SENTINEL_PASS, joined)
        self.assertNotIn(SENTINEL_USER, joined)

    def test_the_wider_ceiling_is_not_a_wider_ssrf_policy(self):
        """`replace` carries every other field through. If it did not, this would fetch."""
        with self.assertRaises(xtream.XtreamError) as caught:
            xtream.load_channels(self.creds, ("live",), Policy())   # allow_private False
        self.assertNotIn(SENTINEL_PASS, str(caught.exception))
        self.assertEqual(self.seen, [], "a private address was fetched anyway")

    def test_a_size_refusal_is_distinguishable_from_every_other_failure(self):
        """`ResponseTooLarge` is a `FetchError`, so nothing that caught the old class breaks."""
        self.assertTrue(issubclass(safefetch.ResponseTooLarge, safefetch.FetchError))
        self.assertTrue(issubclass(xtream.XtreamTooLarge, xtream.XtreamError))

    def test_the_size_arm_is_ordered_before_the_general_one(self):
        """Structural, because the subclass relationship makes the order load-bearing.

        Both `except` arms end in an appended note and read as interchangeable. They are not:
        `XtreamTooLarge` is an `XtreamError`, so if the general arm is moved above it, every
        size refusal quietly goes back to blaming the panel -- and the note assertion above
        would still pass, because it only ever sees whichever arm ran.
        """
        src = pathlib.Path(xtream.__file__).read_text()
        specific = src.index("except XtreamTooLarge as exc:")
        general = src.index("except XtreamError as exc:", specific)
        self.assertLess(specific, general,
                        "the general XtreamError arm would swallow XtreamTooLarge")


# ============================================ defect 9: playing what cannot be decoded

class TestRepairPlan(unittest.TestCase):
    """Which streams get re-encoded. Pure, so it can be asked directly instead of inferred.

    The whole risk of this feature is in this table. Re-encoding too little leaves a black
    rectangle; re-encoding too much burns CPU on channels that were fine and -- because
    `public()["repair"]` drives the page's warning -- tells visitors a working stream was broken.
    """

    def test_a_stream_the_browser_can_already_play_is_left_alone(self):
        self.assertIsNone(sessions.plan_repair("h264", "aac"))

    def test_mp2_and_mp3_are_playable_and_must_not_be_touched(self):
        """The reverted commit's bug, nailed down in both directions.

        A deny-list of unplayable audio containing `mp2` would have re-encoded these and warned
        about them. Chrome decodes both -- measured, not assumed -- so the only correct action is
        nothing at all.
        """
        self.assertIsNone(sessions.plan_repair("h264", "mp2"))
        self.assertIsNone(sessions.plan_repair("h264", "mp3"))
        self.assertIn("mp2", sessions.PLAYABLE_AUDIO)
        self.assertIn("mp3", sessions.PLAYABLE_AUDIO)

    def test_ac3_is_repaired_on_the_cpu_with_the_picture_copied(self):
        """The cheap tier: measured at 34.4x realtime for +0 MiB of VRAM."""
        plan = sessions.plan_repair("h264", "ac3", nvenc=True)
        self.assertIsNotNone(plan)
        self.assertFalse(plan.uses_gpu, "an audio repair must never reach for the GPU")
        self.assertEqual(plan.vargs, ("-c:v", "copy"))
        self.assertIn("aac", plan.aargs)
        self.assertIn("ac3", plan.reason)

    def test_hevc_takes_the_video_engine_when_there_is_one(self):
        plan = sessions.plan_repair("hevc", "aac", nvenc=True)
        self.assertTrue(plan.uses_gpu)
        self.assertIn("h264_nvenc", plan.vargs)
        self.assertEqual(plan.aargs, ("-c:a", "copy"), "playable audio must still be copied")

    def test_hevc_falls_back_to_the_cpu_rather_than_refusing(self):
        """`libx264 veryfast` measured 13.4x realtime on real 720p, so this is a fallback and
        not a degradation. A box with no NVENC still plays HEVC channels."""
        plan = sessions.plan_repair("hevc", "aac", nvenc=False)
        self.assertFalse(plan.uses_gpu)
        self.assertIn("libx264", plan.vargs)

    def test_both_broken_repairs_both(self):
        plan = sessions.plan_repair("hevc", "ac3", nvenc=True)
        self.assertIn("h264_nvenc", plan.vargs)
        self.assertIn("aac", plan.aargs)
        self.assertIn("hevc", plan.reason)
        self.assertIn("ac3", plan.reason)

    def test_an_undetected_codec_never_triggers_a_repair(self):
        """"" means the input dump has not arrived, not "unplayable". Guessing from absence would
        re-encode every stream for the first second of its life."""
        self.assertIsNone(sessions.plan_repair("", ""))
        self.assertIsNone(sessions.plan_repair("h264", ""))
        self.assertIsNone(sessions.plan_repair("", "aac"))

    def test_the_reason_cannot_carry_ffmpegs_text(self):
        """`reason` is published, so it is built from this module's vocabulary plus an allow-listed
        token -- never from the stderr line the codec was found in."""
        plan = sessions.plan_repair("hevc", "ac3", nvenc=False)
        for token in plan.reason.replace(",", " ").split():
            self.assertNotIn("/", token)
            self.assertNotIn("://", token)


class TestRepairIsAnnounced(unittest.TestCase):
    def test_public_publishes_what_was_repaired(self):
        s = sessions.Session(id="x", label="L", dir=pathlib.Path("/nonexistent"), created=0.0,
                             scrub=Scrubber(), policy=Policy())
        self.assertEqual(s.public()["repair"], "")
        s.repair = "soundtrack re-encoded from ac3 to aac"
        self.assertEqual(s.public()["repair"], "soundtrack re-encoded from ac3 to aac")

    def test_the_kill_switch_exists(self):
        """A new re-encode path in a working streamer needs an off switch that is not an edit."""
        self.assertIn(sessions.REPAIR_MODE, ("auto", "cpu", "off"))
        src = pathlib.Path(sessions.__file__).read_text()
        self.assertIn("SYMONEURAL_STREAMER_REPAIR", src)

    def test_the_spawn_comment_no_longer_promises_what_the_code_does_not_do(self):
        """House rule, and the reason it is a test: the old comment read "it never quietly
        re-encodes, because the GPU belongs to inference". The code now re-encodes, and a comment
        that contradicts its function is worse than no comment. Both measurements that replaced
        that reasoning have to still be stated where the decision is made."""
        src = pathlib.Path(sessions.__file__).read_text()
        self.assertNotIn("it never quietly\n            # re-encodes", src)
        spawn = src[src.index("def _spawn"):src.index("def _drain_stderr")]
        # Comment markers stripped, then whitespace collapsed: these justifications are prose in a
        # wrapped `#` comment, so a sentence continuing onto the next line reads as "13.4x #
        # realtime" to a naive join. A test that breaks when a comment rewraps is a test that
        # punishes editing the comment, which is the opposite of what this one is for.
        flat = " ".join(ln.lstrip().lstrip("#").strip() for ln in spawn.splitlines())
        flat = " ".join(flat.split())
        self.assertIn("dedicated ASIC", flat)
        self.assertIn("13.4x realtime", flat)


def continuous(body: bytes, repeats: int = 8, chunk: int = 32768, gap: float = 0.02):
    """A route that keeps delivering, the way a live channel does. Returns a Provider callable.

    The repair tests need this and the reason is worth stating, because a fixed body looked like it
    would do and did not. A repair is decided by the thread reading ffmpeg's stderr but applied by
    the pump thread, because only the pump may touch `proc.stdin` -- so the swap happens on the
    **next write**. Hand the streamer a 576 KB file and ffmpeg drains all of it before it has finished
    announcing its codecs: the plan is made with no writes left to apply it, and the session ends
    having never repaired. Measured exactly that way here, with `bytes_in` equal to the file size
    at the moment the plan appeared.

    That is a property of a source that runs out, not of the design: an IPTV channel never stops
    mid-broadcast, so there is always a next write and the swap lands a second or so in. A
    continuous feeder is therefore the honest fixture, and it exercises the mid-stream join --
    `ts_sync_offset` on a fresh ffmpeg handed the middle of a transport stream -- which a
    play-once file never reaches.
    """
    def route(h):
        h.send_response(200)
        h.send_header("Content-Type", "video/mp2t")
        # No Content-Length, so the client reads until close. That is what a live stream is.
        h.end_headers()
        try:
            for _ in range(repeats):
                for i in range(0, len(body), chunk):
                    h.wfile.write(body[i:i + chunk])
                    h.wfile.flush()
                    time.sleep(gap)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass            # the streamer stopped watching. That is how every one of these ends.
    return route


@needs_ffmpeg
class TestRepairEndToEnd(unittest.TestCase):
    """Real media, real ffmpeg, real respawn. The unit table above says what should happen; this
    says it actually does, which is the only version that counts for a feature whose failure mode
    is a stream that still does not play."""

    def _watch(self, name: str, timeout: float = 60.0) -> sessions.Session:
        """Run a continuous channel until it settles, and report what it settled as.

        "Settled" cannot be `ready` alone here, which is the trap this helper exists to avoid. An
        HEVC stream copies into MPEG-TS perfectly, so the *unrepaired* attempt publishes a playlist
        within a second or two -- a test that stops at the first playlist therefore catches the
        broken stream every time and reports `repaired == False` on a feature that works. So:
        `repaired and ready` is a result, and `ready` with no plan pending and none arriving during
        a grace period is the other result.
        """
        body = (media() / name).read_bytes()
        with Provider({"/s.ts": continuous(body)}) as p:
            mgr = sessions.SessionManager(
                root=pathlib.Path(tempfile.mkdtemp(prefix="streamer-repair-")))
            s = mgr.start(p.url("/s.ts"), "Harness", LOCAL)
            try:
                deadline = time.monotonic() + timeout
                quiet_since = None
                while time.monotonic() < deadline:
                    if s.state == "failed":
                        break
                    if s.repaired and s.ready:
                        break
                    if s.ready and s.pending_repair is None and not s.repaired:
                        # Possibly a stream that needs nothing. Give a late decision -- ffmpeg can
                        # still be printing -- a moment to show up before concluding that.
                        quiet_since = quiet_since or time.monotonic()
                        if time.monotonic() - quiet_since > 3.0:
                            break
                    else:
                        quiet_since = None
                    time.sleep(0.1)
                # Read through the directory before `shutdown` removes it.
                s.settled_ready = s.ready
                s.settled_segments = sorted(s.dir.glob("s*.ts"))
                s.settled_first = (s.settled_segments[0].read_bytes()
                                   if s.settled_segments else b"")
                return s
            finally:
                mgr.shutdown()

    def _run(self, name: str) -> sessions.Session:
        return self._watch(name)

    def test_an_ac3_channel_comes_out_as_aac_and_still_plays(self):
        """The measured common failure, fixed end to end: h264 + AC-3 in, playable segments out."""
        s = self._run("ac3-long.ts")
        self.assertTrue(s.settled_ready, f"no playlist: {s.state} {s.error}")
        self.assertEqual(s.acodec, "ac3", "the INPUT codec is what is reported")
        self.assertTrue(s.repaired)
        self.assertIn("ac3", s.repair)
        self.assertIn("aac", s.repair)

    def test_an_mp2_channel_is_never_repaired(self):
        """The regression guard against a deny-list coming back. mp2 plays; touching it would
        spend CPU on a working channel and apologise for it on the page."""
        s = self._run("mp2-long.ts")
        self.assertTrue(s.settled_ready, f"no playlist: {s.state} {s.error}")
        self.assertEqual(s.acodec, "mp2")
        self.assertFalse(s.repaired, "mp2 is playable and must take the stream-copy path")
        self.assertEqual(s.repair, "")

    def test_a_clean_channel_is_never_repaired(self):
        s = self._run("clean-long.ts")
        self.assertTrue(s.settled_ready, f"no playlist: {s.state} {s.error}")
        self.assertFalse(s.repaired)
        self.assertEqual(s.repair, "")

    def test_an_hevc_channel_becomes_h264(self):
        """HEVC copies into MPEG-TS perfectly, so this session was `live` with segments and a
        black rectangle before the repair existed. That is the failure this feature is for."""
        s = self._run("hevc-long.ts")
        self.assertTrue(s.settled_ready, f"no playlist: {s.state} {s.error}")
        self.assertEqual(s.vcodec, "hevc")
        self.assertTrue(s.repaired)
        self.assertIn("hevc", s.repair)

    def test_the_repaired_segments_really_decode_as_h264(self):
        """Reads the OUTPUT with ffprobe rather than trusting the argv.

        The distinction matters: every assertion above would pass if ffmpeg had been handed
        `-c:v h264_nvenc` and exited immediately. This is the same reason the frontend suite
        decodes a generated image instead of checking that the endpoint answered.
        """
        s = self._watch("hevc-long.ts")
        self.assertTrue(s.repaired, f"never repaired: {s.state} {s.error}")
        self.assertTrue(s.settled_first, "no segment was ever written")
        out = subprocess.run(
            [shutil.which("ffprobe") or "ffprobe", "-v", "error",
             "-select_streams", "v:0", "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", "-"],
            input=s.settled_first, capture_output=True, timeout=60).stdout.decode().strip()
        # `splitlines()[0]`: a segment carrying more than one video stream would print one line
        # each, and the assertion should name the first rather than compare against a blob.
        first = out.splitlines()[0].strip() if out else ""
        self.assertEqual(first, "h264", f"repaired segment is {out!r}, not h264")

    def test_the_kill_switch_really_disables_it(self):
        """With repair off, an HEVC stream goes back to copying through unplayable -- which is
        the old behaviour, and has to remain reachable without an edit."""
        real = sessions.REPAIR_MODE
        try:
            sessions.REPAIR_MODE = "off"
            s = self._run("hevc-long.ts")
            self.assertFalse(s.repaired)
            self.assertEqual(s.repair, "")
            self.assertEqual(s.vcodec, "hevc", "still reported, so the page can still explain it")
        finally:
            sessions.REPAIR_MODE = real


if __name__ == "__main__":
    unittest.main(verbosity=2)
