"""The licence inventory: that it is current, and that its classifier is right.

This is the file that answers "what could get us sued", so the tests are about
the two ways it could lie: by being stale, and by misreading a licence.
"""

from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
TSV = ROOT / "ops" / "LICENSES.tsv"
MD = ROOT / "LICENSES.md"
INVENTORY = ROOT / "tools" / "audit" / "license_inventory.py"
RENDER = ROOT / "tools" / "build" / "build_licenses.py"


def load(path: Path):
    """Import a generator by path.

    Registered in sys.modules *before* exec: these modules use
    `from __future__ import annotations`, so @dataclass resolves its field types
    by looking its own module up there. Without the registration the lookup
    returns None and collection dies inside dataclasses with an AttributeError
    that says nothing about the real cause.
    """
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


inv = load(INVENTORY)


class TheClassifierReadsLicencesCorrectly(unittest.TestCase):
    def test_plain_copyleft_is_copyleft(self):
        for text in ("GPL-3.0", "GPLv2+", "AGPL-3.0-only",
                     "GNU General Public License v2 or later (GPLv2+)"):
            self.assertEqual(inv.classify(text), inv.COPYLEFT, text)

    def test_an_OR_with_a_permissive_branch_is_permissive(self):
        """SPDX OR is the licensee's choice. ittapi ships GPL-2.0-only OR
        BSD-3-Clause in the gateway tree; calling that copyleft would raise a
        blocking finding against a crate that obliges only attribution."""
        self.assertEqual(inv.classify("GPL-2.0-only OR BSD-3-Clause"),
                         inv.PERMISSIVE)
        self.assertEqual(inv.classify("MIT OR Apache-2.0"), inv.PERMISSIVE)

    def test_an_AND_is_not_a_choice(self):
        """Every branch of AND binds, so the strictest one decides."""
        self.assertEqual(inv.classify("MIT AND GPL-3.0"), inv.COPYLEFT)

    def test_weak_copyleft_is_not_reported_as_copyleft(self):
        for text in ("LGPL-2.1-only", "MPL-2.0", "MPL-2.0 AND MIT"):
            self.assertEqual(inv.classify(text), inv.WEAK_COPYLEFT, text)

    def test_permissive_is_permissive(self):
        for text in ("MIT", "BSD-3-Clause", "Apache-2.0",
                     "Apache-2.0 WITH LLVM-exception", "ISC"):
            self.assertEqual(inv.classify(text), inv.PERMISSIVE, text)

    def test_an_unreadable_licence_is_UNKNOWN_not_permissive(self):
        """Guessing permissive is the one wrong answer that hides a problem."""
        for text in ("", "UNKNOWN", "see LICENSE.txt", "Custom Terms v3"):
            self.assertEqual(inv.classify(text), inv.UNKNOWN, text)


class TheRecordIsCurrent(unittest.TestCase):
    def test_the_tsv_matches_the_disk(self):
        """Re-run the generator; if it would write something else, it is stale."""
        out = subprocess.run([sys.executable, str(INVENTORY), "--check"],
                             capture_output=True, text=True, timeout=600)
        self.assertEqual(out.returncode, 0, out.stderr or out.stdout)

    def test_the_markdown_matches_the_tsv(self):
        out = subprocess.run([sys.executable, str(RENDER), "--check"],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr or out.stdout)


class TheInventoryIsWellFormed(unittest.TestCase):
    def setUp(self):
        with TSV.open() as fh:
            self.rows = list(csv.DictReader(
                (l for l in fh if not l.startswith("#")), delimiter="\t"))

    def test_it_is_not_suspiciously_short(self):
        """A collector that silently returned nothing would publish a short,
        confident, wrong inventory."""
        self.assertGreater(len(self.rows), 500)

    def test_every_row_names_a_party_and_a_class(self):
        for r in self.rows:
            self.assertIn(r["party"], (inv.FIRST, inv.SECOND, inv.THIRD), r)
            self.assertIn(r["klass"], (inv.PERMISSIVE, inv.COPYLEFT,
                                       inv.WEAK_COPYLEFT, inv.PROPRIETARY,
                                       inv.UNKNOWN), r)

    def test_every_row_says_whether_it_leaves_this_box(self):
        """`carried` is what turns a licence into an obligation. A row without
        it cannot be reasoned about at all."""
        for r in self.rows:
            self.assertIn(r["carried"], ("shipped", "build-only", "host-only"), r)

    def test_our_own_code_is_present_and_ours(self):
        ours = [r for r in self.rows if r["party"] == inv.FIRST]
        self.assertTrue(ours)
        for r in ours:
            self.assertIn("SyMoNeuRaL", r["licence"])

    def test_the_comfyui_fork_is_recorded_as_copyleft(self):
        """The one item on the page that is a real decision. If this row ever
        stops saying copyleft, something reclassified GPL-3.0."""
        ui = [r for r in self.rows if r["component"] == "symoneural-ui"]
        self.assertEqual(len(ui), 1)
        self.assertEqual(ui[0]["klass"], inv.COPYLEFT)
        self.assertEqual(ui[0]["party"], inv.SECOND)

    def test_nothing_shipped_is_copyleft(self):
        """The whole safety argument is that the GPL component is not
        distributed. This fails the day that stops being true."""
        shipped = [r for r in self.rows
                   if r["carried"] == "shipped" and r["klass"] == inv.COPYLEFT]
        self.assertEqual(shipped, [], f"copyleft is being shipped: {shipped}")

    def test_the_operating_systems_packages_are_not_listed_as_ours(self):
        """nala, mpv and iotop live in system-python. Reporting them would put
        false GPL findings in front of the owner and bury the real one."""
        names = {r["component"].lower() for r in self.rows}
        for package in ("nala", "mpv", "iotop", "pyqt5", "python-apt"):
            self.assertNotIn(package, names)

    def test_the_dependencies_we_do_import_are_listed(self):
        names = {r["component"].lower() for r in self.rows}
        for package in ("fastapi", "pydantic", "uvicorn", "httpx", "numpy"):
            self.assertIn(package, names)


if __name__ == "__main__":
    unittest.main()
