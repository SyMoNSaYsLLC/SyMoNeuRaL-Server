"""`ProjectStatus.md` claims a HEAD. Check that the claim is still true.

## Why this exists

This file has described a tree that no longer existed **twice**, and both times a human caught
it rather than a check:

* `5427f2a5` stood in the checkpoint while the tree advanced **fifteen** commits. An
  independent release red-team found it, not the document.
* It was re-pinned to `d79513b1` on 2026-09-03. By 2026-09-04 the tree was **nineteen**
  commits past that, and the file was still asserting the old one.

A second occurrence of an identical failure is not bad luck. `.claude/CLAUDE.md` says the
thing to be suspicious of on arrival is *"a figure with no commit SHA beside it"* -- but a SHA
beside a figure is worth nothing if the SHA itself has expired, and this document is the one
place in the repo whose whole job is to be current. Re-pinning by hand a third time would
produce the same paragraph again in a day.

## What this asserts, and what it deliberately does not

It asserts the pinned SHA is **an ancestor of, or equal to, HEAD**. That is the honest
property. It is NOT "the pin equals HEAD": requiring that would go red on the very next commit
and force an edit to this document in every unrelated change, which is how a check becomes
noise and then gets deleted. Ancestry catches the real defect -- a pin naming a commit that is
not in this history at all, or a document rewritten to claim a tree that never contained it --
while leaving normal drift to the staleness test below, which is advisory.

The staleness margin is a **warning with a number in it**, not a failure. Fifteen and nineteen
were both far past any reasonable margin; a handful of commits behind is ordinary and a suite
that goes red for it would be a suite people run with `-k` to skip.

## Why not a git hook

A hook runs on the machine that has one. This runs wherever the suite runs, which is the same
place every other guarantee in this repo is checked, and it is visible in the same output.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATUS = ROOT / "ProjectStatus.md"

#: Beyond this many commits behind HEAD, the checkpoint is reported as stale. Advisory: it
#: prints, it does not fail. Twenty is chosen because both real incidents (15 and 19) sit at or
#: under it and both were caught by people rather than tooling -- so the number is set where a
#: reader would already have wanted to be told, not where it would nag.
STALE_AFTER = 20


def _git(*args: str) -> str:
    return subprocess.run(("git", "-C", str(ROOT)) + args,
                          capture_output=True, text=True, check=False).stdout.strip()


def _in_a_git_checkout() -> bool:
    return (ROOT / ".git").exists() and bool(_git("rev-parse", "HEAD"))


class TheCheckpointNamesThisHistory(unittest.TestCase):
    """The pinned SHA must be a commit this tree actually contains."""

    def setUp(self) -> None:
        if not _in_a_git_checkout():
            self.skipTest("not a git checkout; nothing to compare the pin against")
        self.text = STATUS.read_text(encoding="utf-8")

    def _pin(self) -> str:
        m = re.search(r"Accepted HEAD:\s*\*\*`([0-9a-f]{7,40})`\*\*", self.text)
        self.assertIsNotNone(
            m, "ProjectStatus.md no longer states `Accepted HEAD: **`<sha>`**`. Either the "
               "line moved -- in which case fix this pattern -- or the document stopped "
               "pinning a commit at all, which is the failure this file exists to prevent.")
        return m.group(1)                                     # type: ignore[union-attr]

    def test_the_pinned_sha_exists_in_this_repository(self):
        pin = self._pin()
        kind = _git("cat-file", "-t", pin)
        self.assertEqual(kind, "commit",
                         f"ProjectStatus.md pins {pin}, which is not a commit in this "
                         f"repository. A canonical current-state document naming a commit "
                         f"nobody has is worse than one naming an old commit.")

    def test_the_pinned_sha_is_an_ancestor_of_head(self):
        """The real assertion. Not equality -- see the module docstring."""
        pin = self._pin()
        head = _git("rev-parse", "HEAD")
        if not head:
            self.skipTest("no HEAD to compare against")
        ok = subprocess.run(("git", "-C", str(ROOT), "merge-base",
                             "--is-ancestor", pin, "HEAD"),
                            capture_output=True, check=False).returncode == 0
        self.assertTrue(
            ok,
            f"ProjectStatus.md pins {pin}, which is NOT an ancestor of HEAD ({head[:8]}). "
            f"The document is describing a tree this branch does not contain -- a rebase, a "
            f"reset, or a checkpoint copied from somewhere else. Re-read the file against the "
            f"working tree and re-pin it; do not just swap the SHA.")

    def test_how_far_behind_is_reported_rather_than_enforced(self):
        """Advisory. Prints a number; never fails.

        Deliberately not an assertion. A test that goes red because someone committed twice
        since the last documentation pass is a test people learn to skip, and a skipped guard
        protects nothing. What it does is put the distance in the suite output, where the next
        person reads it -- which is exactly what nobody had on 2026-09-03.
        """
        pin = self._pin()
        behind = _git("rev-list", "--count", f"{pin}..HEAD")
        if not behind.isdigit():
            self.skipTest(f"cannot count commits since {pin}")
        n = int(behind)
        if n > STALE_AFTER:
            print(f"\n  ProjectStatus.md checkpoint is {n} commits behind HEAD "
                  f"(pin {pin}). It has twice described a tree that no longer existed; "
                  f"re-read it against the working tree before relying on it.")
        self.assertGreaterEqual(n, 0)


class TheCheckCanActuallyFail(unittest.TestCase):
    """A guard nobody has watched fail is not evidence of anything.

    `.claude/CLAUDE.md`: *"break it on purpose and watch a test fail, then fix it. A test that
    passes before and after your change tested nothing."* The ancestry test above would pass
    just as happily against a pattern that matches nothing, so prove the mechanism bites.
    """

    def setUp(self) -> None:
        if not _in_a_git_checkout():
            self.skipTest("not a git checkout")

    def test_a_sha_that_is_not_an_ancestor_is_detected(self):
        # The empty-tree object is a real, well-known SHA that is a valid object in every git
        # repository and is never a commit -- so it exercises both the "is it a commit" and the
        # "is it an ancestor" paths without inventing a fake hash that git would simply reject.
        empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        self.assertNotEqual(_git("cat-file", "-t", empty_tree), "commit",
                            "the empty-tree object must not read as a commit")
        ok = subprocess.run(("git", "-C", str(ROOT), "merge-base",
                             "--is-ancestor", empty_tree, "HEAD"),
                            capture_output=True, check=False).returncode == 0
        self.assertFalse(ok, "if this passes, --is-ancestor is not discriminating and the "
                             "test above proves nothing")

    def test_the_pattern_matches_the_real_document(self):
        """Guards the other direction: a regex that matched nothing would make every
        assertion above vacuous, which is how a green check hides a missing one."""
        text = STATUS.read_text(encoding="utf-8")
        self.assertRegex(text, r"Accepted HEAD:\s*\*\*`[0-9a-f]{7,40}`\*\*")


if __name__ == "__main__":
    unittest.main()
