"""The roster's `implementation` column, and the parser's ability to find the file.

Both of these were broken and neither broke anything visible, which is the point
of the file: nothing in the running product reads the implementation column, and
nothing had called the parser since the restructure, so two defects sat in a
file whose whole job is to be the one true list of surfaces.

Kept separate from `test_roster.py` because that module imports
`test_status_rack`, which does not resolve, so everything in it fails at
collection. These tests would never have run beside it.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
sys.path.insert(0, str(ROOT / "backend"))

from registry.lib import roster  # noqa: E402


class TheParserCanFindItsOwnFile(unittest.TestCase):
    """`ROSTER` was `Path(__file__).parent / "ROSTER.md"`, which was correct while
    this module sat beside the file and wrong the moment the restructure moved it
    into `lib/`. Every caller raised FileNotFoundError -- the rack builder, the
    docs index, the bootcamp scout -- and nobody noticed, because nobody ran it.
    """

    def test_the_roster_file_resolves(self):
        self.assertTrue(roster.ROSTER.is_file(), roster.ROSTER)

    def test_it_resolves_from_a_different_working_directory(self):
        """A path that only works from the repository root is a path that breaks
        under systemd, which starts units with its own cwd."""
        import subprocess
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); "
             "from registry.lib import roster; print(len(roster.rows()))"
             % str(ROOT / "backend")],
            cwd="/", capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertGreaterEqual(int(out.stdout.strip()), 12)

    def test_it_parses_every_row(self):
        self.assertGreaterEqual(len(roster.rows()), 12)


class TheImplementationColumnResolves(unittest.TestCase):
    """Every `implementation` path must exist on disk.

    Nothing in the running product reads this column, which is exactly why it
    rotted: ten of twelve rows still said `backend/apps/<name>` long after the
    restructure moved every component to `backend/<name>`. A column nobody reads
    is a column that is wrong, so this is the thing that reads it.
    """

    def setUp(self):
        self.rows = roster.rows()

    def test_every_row_names_something_that_exists(self):
        missing = [(r["id"], r["implementation"]) for r in self.rows
                   if not (ROOT / r["implementation"]).exists()]
        self.assertEqual(missing, [], f"roster points at paths that are gone: {missing}")

    def test_no_row_points_into_the_old_apps_tree(self):
        """Refused by name as well as by existence: the existence check alone
        would pass again the day somebody recreates `backend/apps/` for an
        unrelated reason, and these rows would silently be wrong once more."""
        stale = [r["id"] for r in self.rows
                 if r["implementation"].startswith("backend/apps/")]
        self.assertEqual(stale, [], f"rows still point into backend/apps/: {stale}")

    def test_every_implementation_is_python(self):
        """A surface is served by Python here. A row naming a directory or a
        shell script is a row somebody guessed at rather than checked."""
        for r in self.rows:
            self.assertTrue(r["implementation"].endswith(".py"),
                            f"{r['id']}: {r['implementation']} is not a .py file")


if __name__ == "__main__":
    unittest.main()
