"""The operator console must stay generated, local-only, and free of credentials.

Safety rules 1, 2 and 4 from OPERATOR-CONSOLE.md, as assertions rather than intentions.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
TOOL = ROOT / "tools" / "build_operator.py"
PAGE = ROOT / "run" / "operator.html"
sys.path.insert(0, str(ROOT / "backend"))


class TheConsoleIsGenerated(unittest.TestCase):

    def test_check_passes(self):
        r = subprocess.run([sys.executable, str(TOOL), "--check"],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, f"stale -- run build_operator.py\n{r.stdout}")

    def test_every_application_appears(self):
        """Either as the owner of a route, or in the explicit no-route list."""
        from registry.lib import appdocs
        text = PAGE.read_text()
        for a in appdocs.APPLICATIONS:
            with self.subTest(app=a.id):
                self.assertIn(a.id, text,
                              f"application {a.id!r} appears nowhere on the console -- a "
                              "missing row reads as 'fine', which is the vacuous-guard "
                              "failure in a user interface")


class TheConsoleIsNotPublic(unittest.TestCase):

    def test_the_page_is_not_in_the_site_directory(self):
        """`deploy.sh` publishes any .html under site/. An operator surface must not be
        there -- safety rule 1."""
        self.assertFalse((ROOT / "site" / "operator.html").exists(),
                         "operator.html is in site/, which deploy.sh publishes to the "
                         "public webroot")

    def test_it_is_written_to_run(self):
        self.assertIn('run" / "operator.html', TOOL.read_text().replace("ROOT / ", ""),
                      "the output path moved out of run/, which is the local-only precedent "
                      "progress.html established")


class TheConsoleHoldsNoCredential(unittest.TestCase):

    def test_no_token_value_reaches_the_page(self):
        """Safety rule 2: studio's token is the whole boundary in front of run_command.

        Compares against the live config by NAME and by shape, never printing a value: any
        64-hex run in the page would be a token-shaped string, and there is no legitimate
        reason for one to be there.
        """
        import re
        text = PAGE.read_text()
        hexruns = re.findall(r"\b[0-9a-f]{64}\b", text)
        self.assertEqual(hexruns, [],
                         "the console contains a 64-hex string, which is the shape of every "
                         "surface token on this box")

    def test_no_route_is_invocable(self):
        """Until the server-side invoke lands, the page must not fire anything."""
        text = PAGE.read_text().lower()
        for banned in ("<form", "<button", "onclick", "fetch(", "xmlhttprequest"):
            with self.subTest(construct=banned):
                self.assertNotIn(banned, text,
                                 f"the page contains {banned!r}: it can invoke routes from "
                                 "the browser, which is how a surface token would end up in "
                                 "client-side JavaScript")

    def test_nothing_enables_a_surface(self):
        """Safety rule 4: the miner arms, TRON settlement and licence state carry no switch."""
        self.assertIn("no switch", PAGE.read_text(),
                      "the page no longer states that the miner, settlement and licence "
                      "state are not switchable here")


if __name__ == "__main__":
    unittest.main()
