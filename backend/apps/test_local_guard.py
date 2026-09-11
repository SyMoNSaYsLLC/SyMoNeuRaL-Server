# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""`/local/*` must refuse anything that crossed a proxy, whatever the proxy calls itself.

`_require_local` has two conditions and the peer address is the real one. The forwarded
headers are the second, and its docstring rests the whole argument on them: *"Caddy sets
them on everything it proxies, so their presence means the request crossed the reverse proxy
even if the socket says loopback -- which is exactly what a future `handle /local*` block
would produce"*.

Measured 2026-09-08: the list was `x-forwarded-for`, `x-forwarded-host`, `x-real-ip`, and
all six probed `/local/*` routes accepted requests carrying `Forwarded`, `Via` or
`X-Forwarded-Proto`. The last is the one Caddy sets on everything it proxies -- the exact
header the argument depends on -- and `Forwarded` is RFC 7239, the standardised replacement
that a modern proxy may send instead of any X- spelling.

The peer check was never bypassed, so nothing was exposed. What was incomplete was the
belt, on the day the braces are relied on.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

def _find_root(start: pathlib.Path) -> pathlib.Path:
    """Walk up for the marker; never count parents. See symoneural-audit/README.md.

    Written this way after `bin/symoneural-audit` reported this very file. Two new test
    files opened with `parents[2]` and pushed the ratchet from 81 to 83 -- in the same
    session that built the ratchet and wrote the README recommending this function. Habit
    is stronger than intent, which is the argument for the check existing at all.
    """
    for cand in (start, *start.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "backend"))

import api                                                           # noqa: E402


class _Req:
    """The two things `_require_local` reads, and nothing else."""

    def __init__(self, peer: str, headers: dict | None = None):
        self.client = type("C", (), {"host": peer})()
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


class TheProxyHeaderListIsComplete(unittest.TestCase):

    #: Every header a conforming proxy may add. Each must be refused.
    MUST_REFUSE = (
        ("forwarded",         'for=203.0.113.9;proto=https'),   # RFC 7239
        ("Forwarded",         'for=203.0.113.9'),                # case must not matter
        ("x-forwarded-for",   "203.0.113.9"),
        ("x-forwarded-host",  "symoneural.com"),
        ("x-forwarded-proto", "https"),                          # Caddy sets this always
        ("x-forwarded-port",  "443"),
        ("x-real-ip",         "203.0.113.9"),
        ("via",               "1.1 caddy"),                      # RFC 9110
    )

    def test_a_loopback_request_with_no_proxy_header_is_allowed(self):
        """The control. Without this, a guard that refuses everything would pass below."""
        for peer in api.LOCAL_ONLY:
            with self.subTest(peer=peer):
                api._require_local(_Req(peer))          # must not raise

    def test_every_proxy_header_is_refused_even_from_loopback(self):
        for name, value in self.MUST_REFUSE:
            with self.subTest(header=name):
                with self.assertRaises(Exception) as caught:
                    api._require_local(_Req("127.0.0.1", {name: value}))
                self.assertEqual(404, getattr(caught.exception, "status_code", None),
                                 "404 rather than 403: a 403 confirms the route exists")

    def test_a_remote_peer_is_refused_with_no_headers_at_all(self):
        with self.assertRaises(Exception) as caught:
            api._require_local(_Req("203.0.113.9"))
        self.assertEqual(404, getattr(caught.exception, "status_code", None))

    def test_the_list_still_holds_the_three_it_started_with(self):
        """A completed list that dropped an original entry would be a regression.

        Cheap, and it is the shape of mistake a rewrite makes.
        """
        for original in ("x-forwarded-for", "x-forwarded-host", "x-real-ip"):
            self.assertIn(original, api._PROXY_HEADERS)


if __name__ == "__main__":
    unittest.main()
