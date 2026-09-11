"""A README that exists on disk and not in git is a README a clone does not get.

Three times in this tree, and none of them reported by anything else:

    `build/` unanchored matched tools/build/ and made all 32 generators untracked
    `/run/` excluded the DIRECTORY, so run/README.md could not be re-included at all
    `/models/*` did the same to models/llm/README.md

`git status` is clean in every case, `ls` shows the file, and only `git check-ignore -v`
says why. The owner found the first by asking why a directory had no README -- it had one.

## The rule git enforces and people forget

**A file cannot be re-included when a parent DIRECTORY is excluded.** `/run/` followed by
`!/run/README.md` does nothing at all. Exclude the contents -- `/run/*` -- and the exception
works.

## Why `.pytest_cache` is exempt and nothing else is

pytest writes that README itself, into a directory that is correctly ignored. It is not ours
and a clone should not get it. Every other exemption should be argued in this list rather
than added to a pattern, because a pattern is how the three above happened.
"""
from __future__ import annotations

import pathlib
import subprocess
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents
            if (_p / "backend" / "server.py").is_file())

#: Written by a third-party tool into a directory we deliberately ignore. Not ours to ship.
EXEMPT = {".pytest_cache/README.md"}

SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__"}


def _tracked() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


class EveryReadmeIsInGit(unittest.TestCase):
    def test_no_readme_is_silently_ignored(self):
        tracked, missing = _tracked(), []
        for p in ROOT.rglob("README.md"):
            if SKIP_PARTS & set(p.parts):
                continue
            rel = str(p.relative_to(ROOT))
            if rel in EXEMPT or rel in tracked:
                continue
            why = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-v", rel],
                                 capture_output=True, text=True).stdout.strip()
            missing.append(f"{rel}  <-  {why or 'never added'}")
        self.assertEqual(missing, [],
                         "README(s) on disk but not in git -- a clone does not get these:\n  "
                         + "\n  ".join(missing))

    def test_the_exemption_list_stays_true(self):
        """An exemption for a file that is now tracked is an exemption nobody needs."""
        tracked = _tracked()
        for rel in sorted(EXEMPT):
            with self.subTest(path=rel):
                self.assertNotIn(rel, tracked,
                                 f"{rel} is tracked now -- take it out of EXEMPT")

    def test_the_walk_found_readmes(self):
        """Non-vacuous: an empty walk would make both checks above pass over nothing."""
        found = sum(1 for p in ROOT.rglob("README.md") if not SKIP_PARTS & set(p.parts))
        self.assertGreater(found, 100, "the walk found almost no READMEs; it is broken")


if __name__ == "__main__":
    unittest.main()
