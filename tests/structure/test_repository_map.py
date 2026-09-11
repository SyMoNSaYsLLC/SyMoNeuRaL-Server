"""`README.md`'s folder table must describe this repository, not a previous one.

It reached 32 rows against 26 top-level tracked directories with nothing asserting the
correspondence -- six directories a clone carries had no row at all, and two rows named
directories that are not there. A map nothing enforces is how it got that way, and "I cannot
find anything" is what that costs.

Two assertions, because the repository has two kinds of top-level directory and one rule
cannot cover both:

  1. every TRACKED top-level directory has a row -- a clone carries it, so the map must say
     what it is
  2. every row names a directory that EXISTS, or is one of the few created on demand

Deliberately NOT asserted: that every row is tracked. `symoneural-llm/`, `run/`, `archive/`
and `external/` are gitignored and real, and the map documents them precisely because a
clone does not carry them. Requiring rows to be tracked would delete the rows a new arrival
most needs.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
README = ROOT / "README.md"

#: Directories the map documents that are created by a tool when first used, and are legitimately
#: absent on a clean box. Named individually rather than pattern-matched: a growing list here is
#: a sign the map is drifting again, and it should be short enough that growth is visible.
#: `incoming` and `releases` belonged to the old tree and have no row here. This tree creates
#: exactly one directory on demand: run/, by the first start. It HAS a row, because a clone
#: not carrying it is precisely what a new arrival needs told.
CREATED_ON_DEMAND: set[str] = set()


def _subjects(line: str) -> list[str]:
    """The directories a row is ABOUT -- from its first cell only.

    Not from the whole line. Descriptions mention other directories constantly: the
    `backend/` row says "`api.py` and `apps/`", the `releases/` row explains it was
    "renamed from `archives/` because one letter of difference from `archive/` is a
    hazard". Scanning the line counted those as subjects and produced five ghost
    directories and two false duplicates on this test's first run.
    """
    if not line.startswith("| "):
        return []
    first = line.split("|")[1]
    # A cell may legitimately name more than one, e.g. `desktop/`, `desktop-client/`.
    return re.findall(r"`([A-Za-z0-9._-]+)/`", first)


def _file_subjects(line: str) -> list[str]:
    """The root FILES a row is about -- backticked, no trailing slash.

    Separate from `_subjects` rather than one looser pattern, because a description mentions
    filenames constantly: the conftest row names `sys.path`, the models row names
    `PROVENANCE.json`. Only the first cell is a subject, and a directory row ends in `/`
    while a file row does not -- which is the whole distinction.
    """
    if not line.startswith("| "):
        return []
    first = line.split("|")[1]
    return [m for m in re.findall(r"`([A-Za-z0-9._-]+)`", first) if not m.endswith("/")]


def rows() -> set[str]:
    """Every directory AND root file README.md has a row about."""
    out: set[str] = set()
    for line in README.read_text().splitlines():
        out |= set(_subjects(line)) | set(_file_subjects(line))
    return out


def tracked_top_level() -> set[str]:
    files = subprocess.run(["git", "ls-files"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    return {f.split("/")[0] for f in files if "/" in f}


class TheRootFilesAreDocumented(unittest.TestCase):
    """Every tracked file AT THE ROOT has a row too.

    The map checked directories only, so seven of the eight root files -- including
    `conftest.py`, which is the one arrangement every import in this tree depends on --
    were undocumented and nothing said so. The owner found it by reading the README and
    noticing what was absent, which is the slowest way for this to be caught.

    Root files are rarer than directories and each one is at the root precisely because it
    could not live in a directory. That makes an undocumented one more surprising, not less.
    """

    def test_every_tracked_root_file_has_a_row(self):
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                                 capture_output=True, text=True, check=True).stdout.split()
        at_root = sorted(f for f in tracked if "/" not in f and not f.startswith("."))
        described = rows()
        missing = [f for f in at_root if f not in described]
        self.assertEqual(missing, [],
                         "tracked file(s) at the root with no row in README.md -- a reader "
                         "cannot tell what they are for:\n  " + "\n  ".join(missing))

    def test_the_walk_found_root_files(self):
        """Non-vacuous: an empty file list would make the check above pass over nothing."""
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                                 capture_output=True, text=True, check=True).stdout.split()
        at_root = [f for f in tracked if "/" not in f and not f.startswith(".")]
        self.assertGreater(len(at_root), 3, "almost no root files found; the walk is broken")


class TheRepositoryMapIsComplete(unittest.TestCase):

    def test_every_tracked_directory_has_a_row(self):
        missing = sorted(tracked_top_level() - rows())
        self.assertEqual(
            missing, [],
            f"top-level directories a clone carries with no row in README.md: {missing}. "
            "Someone arriving cannot find out what they are without opening them")

    def test_every_row_names_something_that_exists(self):
        # Directories AND root files, since the map documents both. A row naming neither is
        # a ghost -- either the thing was removed and the row was not, or the row was typed
        # for something that never landed.
        on_disk = {p.name for p in ROOT.iterdir()}
        ghosts = sorted(r for r in rows() if r not in on_disk and r not in CREATED_ON_DEMAND)
        self.assertEqual(
            ghosts, [],
            f"README.md has rows for things that are not here: {ghosts}. Either they "
            "were removed and the row was not, or they are created on demand and belong in "
            "CREATED_ON_DEMAND with a note in the row saying so")

    def test_the_created_on_demand_list_stays_short_and_true(self):
        """Each entry must actually be absent, or it is not created-on-demand, it is a row
        somebody forgot to take off the list."""
        on_disk = {p.name for p in ROOT.iterdir() if p.is_dir()}
        for d in sorted(CREATED_ON_DEMAND):
            with self.subTest(directory=d):
                self.assertIn(d, rows(), f"{d} is exempted but has no row to exempt")
                if d in on_disk:
                    self.fail(f"{d}/ exists, so it is not created-on-demand any more -- "
                              "remove it from CREATED_ON_DEMAND")

    def test_no_directory_is_described_twice(self):
        """One directory, one row. A second row is a second answer."""
        counts: dict[str, int] = {}
        for line in README.read_text().splitlines():
            for m in _subjects(line):
                counts[m] = counts.get(m, 0) + 1
        dupes = sorted(d for d, n in counts.items() if n > 1)
        self.assertEqual(dupes, [],
                         f"described by more than one row: {dupes}")


if __name__ == "__main__":
    unittest.main()
