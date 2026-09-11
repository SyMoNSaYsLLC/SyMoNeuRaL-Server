"""The rack search provider: what it matches, what it opens, what it refuses.

The handlers are exercised directly with a fake opener, so these need neither a
desktop session nor a browser.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
HERE = ROOT / "frontend" / "desktop-search"
sys.path.insert(0, str(HERE))

import gnomeshell  # noqa: E402
import krunner  # noqa: E402
import rack  # noqa: E402


class Opened(list):
    """Stands in for xdg-open and records what would have been launched."""

    def __call__(self, url):
        self.append(url)


class TheRackIsReadFromDisk(unittest.TestCase):
    def test_every_roster_row_resolves_to_a_url(self):
        surfaces = rack.surfaces()
        self.assertGreaterEqual(len(surfaces), 12)
        for s in surfaces:
            self.assertTrue(s.url.startswith("http://127.0.0.1:"), s.url)

    def test_the_port_comes_from_the_port_table(self):
        """Not hardcoded here: PORTS.tsv is the record, this is a reader."""
        self.assertEqual(rack.ports()["symoneural-api"],
                         rack.surfaces()[0].port)

    def test_searching_an_id_finds_that_surface_first(self):
        self.assertEqual(rack.search("chat")[0].id, "chat")

    def test_searching_a_bus_finds_every_surface_on_it(self):
        self.assertEqual({s.id for s in rack.search("gpu", limit=99)},
                         {s.id for s in rack.surfaces() if s.bus == "gpu"})

    def test_every_term_must_match(self):
        """Two terms narrow; they do not widen."""
        self.assertEqual([s.id for s in rack.search("gpu studio")], ["studio"])

    def test_an_empty_query_matches_nothing(self):
        """Otherwise the launcher shows all twelve rows for a stray space."""
        self.assertEqual(rack.search("   "), [])


class TheKRunnerInterface(unittest.TestCase):
    def setUp(self):
        self.opened = Opened()
        self.runner = krunner.Runner(self.opened)

    def test_a_match_carries_the_label_and_the_bus(self):
        (matches,) = self.runner.Match("chat").unpack()
        self.assertEqual(len(matches), 1)
        _id, label, _icon, _type, _rel, props = matches[0]
        self.assertEqual(label, "SyMoNeuRaL Chat")
        self.assertIn("gpu", props["subtext"])

    def test_an_exact_id_outranks_a_mere_substring(self):
        (matches,) = self.runner.Match("chat").unpack()
        self.assertEqual(matches[0][3], krunner.EXACT_MATCH)
        (loose,) = self.runner.Match("gpu").unpack()
        self.assertEqual(loose[0][3], krunner.POSSIBLE_MATCH)

    def test_running_a_match_opens_that_surface(self):
        self.runner.Run("studio", "")
        self.assertEqual(self.opened, ["http://127.0.0.1:8800/studio"])

    def test_running_an_unknown_id_opens_nothing(self):
        """The roster can change between Match and Run. Stale must open nothing."""
        self.runner.Run("no-such-surface", "")
        self.assertEqual(self.opened, [])


class TheGnomeInterface(unittest.TestCase):
    def setUp(self):
        self.opened = Opened()
        self.provider = gnomeshell.Provider(self.opened)

    def test_it_returns_surface_ids(self):
        (ids,) = self.provider.GetInitialResultSet(["chat"]).unpack()
        self.assertEqual(ids, ["chat"])

    def test_one_meta_per_requested_id_even_when_unknown(self):
        """GNOME Shell requires exactly one meta per id, in order, always."""
        (metas,) = self.provider.GetResultMetas(["chat", "nope"]).unpack()
        self.assertEqual([m["id"] for m in metas], ["chat", "nope"])
        self.assertEqual(metas[0]["name"], "SyMoNeuRaL Chat")

    def test_activating_a_result_opens_that_surface(self):
        self.provider.ActivateResult("miner", [], 0)
        self.assertEqual(self.opened, ["http://127.0.0.1:8800/miner.html"])


class NoCredentialCreepsIn(unittest.TestCase):
    def test_nothing_here_asks_for_a_token(self):
        """Standing owner rule: no activation token gates his own surfaces."""
        banned = ("token", "api_key", "apikey", "bearer", "authorization")
        for path in sorted(HERE.glob("*.py")) + sorted(HERE.glob("*.sh")):
            text = path.read_text().lower()
            for word in banned:
                self.assertNotIn(word, text, f"{path.name} mentions {word!r}")


if __name__ == "__main__":
    unittest.main()
