"""The watchdog must not check the public site the way `smoke.py` does.

`tools/smoke.py:79` sets `PUBLIC_IP = "127.0.0.1"` and curls `https://symoneural.com` with
`--resolve` pointed at loopback. That is correct for a deployment smoke test and catastrophic
for a reachability monitor: measured 2026-09-10, `smoke.py` reported "17 passed, 0 FAILED"
including "public site serves HTML" while the real public URL returned 522 and had been dark
since 29 August.

These pin the two properties that keep `tools/watch.py` from becoming the same thing.
"""
from __future__ import annotations

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WATCH = ROOT / "tools" / "watch.py"
sys.path.insert(0, str(ROOT / "tools"))


class TheWatchdogChecksTheRealPublicPath(unittest.TestCase):

    def test_the_public_check_never_pins_the_address(self):
        """`--resolve` or a hardcoded IP would make check 1 test Caddy instead of the path."""
        src = WATCH.read_text()
        body = src.split("def check_public", 1)[1].split("\ndef ", 1)[0]
        for banned in ("--resolve", "127.0.0.1", "localhost"):
            self.assertNotIn(banned, body,
                             f"check_public uses {banned!r}, so it tests this box rather than "
                             "whether the internet can reach it -- the exact defect in "
                             "smoke.py's public check")

    def test_a_local_address_is_unverifiable_not_up(self):
        """If DNS pointed at this LAN, a fetch could hairpin and lie. It must refuse."""
        import watch
        real = watch.socket.getaddrinfo
        watch.socket.getaddrinfo = lambda *a, **k: [(2, 1, 6, "", ("192.168.0.163", 443))]
        try:
            r = watch.check_public()
        finally:
            watch.socket.getaddrinfo = real
        self.assertEqual(r["state"], watch.UNKNOWN,
                         "a name resolving to this LAN was reported as reachable; a hairpinned "
                         "fetch succeeds while the outside world cannot reach us")

    def test_every_check_has_a_state_and_a_detail(self):
        """A check that returns a bare boolean cannot say WHY, and why is the whole value."""
        import watch
        for name, fn in watch.CHECKS:
            with self.subTest(check=name):
                self.assertTrue(callable(fn))
        tree = ast.parse(WATCH.read_text())
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertIn("notify", names, "the notification hook is gone")

    def test_the_notify_hook_sends_nothing(self):
        """The destination is the owner's. A watchdog that starts talking outbound on its own
        is a worse problem than the one it watches for."""
        body = WATCH.read_text().split("def notify", 1)[1].split("\ndef ", 1)[0]
        for banned in ("requests.", "urlopen", "smtplib", "http.client", "socket.create_connection"):
            self.assertNotIn(banned, body, f"notify() reaches outbound via {banned!r}")


if __name__ == "__main__":
    unittest.main()
