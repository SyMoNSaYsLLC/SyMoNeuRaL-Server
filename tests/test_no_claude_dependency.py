# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""The repository must not depend on `.claude`. Enforced, so it stays true.

The provider-specific authority was retired on 2026-09-08: the rules moved to
`docs/authority/PROJECT-AUTHORITY.md`, the handoff to `docs/HANDOFF.md`, the deny rules to
`docs/authority/TOOL-POLICY.json`, and the seven `.claude` paths were untracked. The
physical directory survives only until the owner's retirement backup is taken.

A claim like "there are no dependencies left" decays the moment somebody adds one, so this
asserts it rather than recording it.

## What counts as a dependency, and what does not

**Counts:** first-party code or tests that RESOLVE a path under `.claude` at runtime --
`Path(...) / ".claude"`, `open(".claude/...")`, `$ROOT/.claude/...` in a shell script.

**Does not count, and the distinction is the whole test:**

  * `archive/vendor-sdks/anthropics/**` -- the vendored Anthropic SDK. It legitimately addresses
    `~/.claude` because that is the product it wraps. Rewriting somebody else's SDK to stop
    naming its own product would be vandalism, and the task forbids modifying vendor trees.
  * `scripts/lib/archive-guard.sh` -- its `.claude/` entry is a PROTECTION rule. The guard
    must keep refusing to put that directory in a tarball for exactly as long as the
    directory exists. Deleting the rule because the tracking changed is how a directory
    full of settings ends up in an archive.
  * Prose. A docstring citing `.claude/HANDOVER.md` as historical context is inert. ~128
    such citations remain and are recorded as work, not swept -- the last blanket sweep of
    that kind silently edited an assertion.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest


def _find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())

#: Third-party and protection-rule exemptions. Short on purpose: a long exempt list is how
#: a guard stops guarding. Each entry has its reason in the module docstring.
EXEMPT_PREFIXES = (
    "archive/vendor-sdks/",                     # somebody else's SDK, addressing its own product
    "scripts/lib/archive-guard.sh",        # a protection rule, not a dependency
    "backend/test_no_claude_dependency.py",
    "backend/test_archive_guard.py",  # tests that the protection rule works
    "docs/",                               # documentation and historical record
    # The home-disposition table. It names `.claude` because its job is to record what
    # HAPPENS to `.claude` at the reset -- it stats the path to report a size and a mode and
    # then says "purged post-exit by the finalizer". A table that could not name the
    # directory could not classify it, and an unclassified directory is destroyed by the
    # reset without anyone having decided that. This is the same reasoning that exempts
    # scripts/lib/archive-guard.sh: a rule ABOUT the path is not a dependency ON it.
    "restore/lib/home.py",
)

#: A path under .claude being RESOLVED, not merely mentioned. Requires the quote or a
#: shell variable, which is what separates code from prose.
RESOLVES = re.compile(
    r"""(?:Path|PurePath|os\.path\.join|open|read_text|write_text|is_file|exists|glob)"""
    r"""[^\n]{0,80}?["'][^"'\n]*\.claude"""
    r"""|["']\.claude["']"""
    r"""|\$\{?(?:ROOT|HOME|HERE|REPO)\}?/\.claude""",
)

COMMENT = re.compile(r"^\s*(#|//)")
SUFFIXES = (".py", ".sh", ".bash", ".service", ".json", ".toml", ".yaml", ".yml", ".mk")


def _code_only(text: str) -> str:
    """Strip whole-line comments. Docstring prose survives, which the quote rule handles."""
    return "\n".join("" if COMMENT.match(l) else l for l in text.splitlines())


def _tracked():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True, timeout=180)
    for rel in out.stdout.split("\0"):
        if not rel or not rel.endswith(SUFFIXES):
            continue
        if any(rel.startswith(p) for p in EXEMPT_PREFIXES):
            continue
        p = ROOT / rel
        if p.is_file():
            yield rel, p


class NoFirstPartySourceResolvesADotClaudePath(unittest.TestCase):

    def test_the_scan_reads_something(self):
        """An empty walk would make the assertion below vacuously true."""
        self.assertGreater(len(list(_tracked())), 200,
                           "the tracked-file walk returned almost nothing; the scan is "
                           "broken and proves nothing")

    def test_no_active_source_resolves_a_dot_claude_path(self):
        offenders = {}
        for rel, path in _tracked():
            try:
                code = _code_only(path.read_text(errors="replace"))
            except OSError:
                continue
            hits = sorted({m.group(0).strip()[:90] for m in RESOLVES.finditer(code)})
            if hits:
                offenders[rel] = hits
        self.assertEqual(
            {}, offenders,
            "these resolve a path under .claude at runtime. The authority moved to "
            "docs/authority/PROJECT-AUTHORITY.md and docs/HANDOFF.md on 2026-09-08, and "
            "the directory is retired -- point at the neutral path instead")

    def test_the_detector_would_catch_a_real_dependency(self):
        """A guard nobody has proved can fire is not a guard.

        Three shapes it must see: a pathlib join, a bare string constant, and a shell
        variable expansion.
        """
        for snippet in ('AUTH = Path(ROOT) / ".claude" / "CLAUDE.md"',
                        'cfg = open(".claude/settings.json")',
                        'source "$ROOT/.claude/rules.sh"',
                        'if (root / ".claude").exists():'):
            with self.subTest(snippet=snippet[:40]):
                self.assertTrue(RESOLVES.search(snippet), "the detector is blind to this")

    def test_prose_is_not_treated_as_a_dependency(self):
        """The false positive that would force an exemption list to grow."""
        for snippet in ("# see .claude/HANDOVER.md section 5",
                        "the rules used to live in .claude and moved on 2026-09-08",
                        "*Migrated from `.claude/CLAUDE.md`.*"):
            with self.subTest(snippet=snippet[:40]):
                self.assertIsNone(RESOLVES.search(_code_only(snippet)))


class TheNeutralAuthorityExistsToPointAt(unittest.TestCase):
    """The dependency can only be zero if there is somewhere else to point."""

    def test_the_neutral_paths_are_present_and_tracked(self):
        for rel in ("docs/authority/PROJECT-AUTHORITY.md",
                    "docs/authority/TOOL-POLICY.json",
                    "docs/HANDOFF.md",
                    "ProjectStatus.md"):
            with self.subTest(rel=rel):
                self.assertTrue((ROOT / rel).is_file(), f"{rel} is missing")
                tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--error-unmatch", rel],
                                         capture_output=True).returncode == 0
                self.assertTrue(tracked, f"{rel} exists but is not tracked")

    def test_the_retired_paths_are_untracked(self):
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", ".claude"],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual("", out,
                         f"these .claude paths are still tracked:\n{out}")

    def test_the_root_pointer_names_the_neutral_authority(self):
        t = (ROOT / "CLAUDE.md").read_text()
        self.assertIn("docs/authority/PROJECT-AUTHORITY.md", t)
        self.assertNotIn("@.claude/CLAUDE.md", t,
                         "the root file still imports the retired path")


if __name__ == "__main__":
    unittest.main()
