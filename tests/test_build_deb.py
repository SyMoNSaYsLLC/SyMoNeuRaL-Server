"""scripts/build-deb.sh's leak guard, made to fire for the first time.

Audit item 8: the guard at scripts/build-deb.sh:82-92 is real code whose failure arm had
never once executed -- in a healthy checkout EXCLUDE_RE removes every protected path from
the manifest before the copy, so the guard can only fire after a future edit breaks that
regex. Which is exactly the event it exists for, and exactly what nothing had ever staged.

Every test here builds the package inside a sandbox repository shaped like this one -- a
tracked `backend/server.py`, a tracked `backend/remix/.env` carrying values that are fake
by construction, a fake corpus -- and runs the build script against that sandbox. The script
locates its repo root relative to its own path (`build-deb.sh:20`), so "run against the
sandbox" means copying the script text into `<sandbox>/scripts/build-deb.sh`; the copy is
untracked there and never enters its own payload.

Three behavioural tests and one structural one:

  * unmodified, the build succeeds and `dpkg-deb -c` shows no protected path in the payload
    (and does show the ordinary files, so the check is not vacuously passing on an empty box);
  * with EXCLUDE_RE's remix clause removed -- the regression the guard exists for -- the
    build exits 1, names the path on stderr, and produces no .deb;
  * with EXCLUDE_RE weakened AND the guard deleted, the build succeeds and the fake secret
    is demonstrably inside the .deb. That is the mutation check, kept in the suite
    permanently: measured proof that the exit 1 above comes from the guard lines and from
    nothing else in the script.
  * the structural test pins the real script to the exact strings the sandbox surgery
    targets, so the surgery cannot silently start editing text that no longer exists while
    the tests above keep passing against a stale idea of the script.

Nothing here touches the real repository's payload, and no fake value is ever printed --
assertions read the tar listing (paths), never file contents.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-deb.sh"

# The strings the surgical tests operate on. If any drifts in the real script, the surgery
# helpers refuse loudly (assertIn below) instead of testing a script that no longer exists.
# Kept as module constants so the structural test and the surgery share one spelling.
#
# The guard moved. It was an inline `leaked=0` loop in this script; it is now the shared
# function in `scripts/lib/archive-guard.sh`, because build-deb.sh was one of three
# packaging paths and the only one that had a check at all. These tests still assert the
# same behaviour through the same script -- what changed is which two lines the surgery cuts
# to remove the guard, and where the protected-path list is pinned (see the structural test).
REMIX_CLAUSE = r"|backend/remix/\.env$"
GUARD_FIRST_LINE = '. "$ROOT/scripts/lib/archive-guard.sh"'
GUARD_LAST_LINE = '|| { echo "refusing to build" >&2; exit 1; }'
GUARD_LIB = ROOT / "scripts" / "lib" / "archive-guard.sh"


def make_sandbox(tmp: Path) -> Path:
    """A minimal repo the build script accepts, with every protected shape present.

    The values in the fake .env are fake by construction (this literal is their only
    source) and no test prints them; the leak assertions read archive paths only.
    """
    sandbox = tmp / "repo"
    for rel, text in {
        "backend/server.py": "# sandbox stub -- the root check at build-deb.sh:21 wants me\n",
        "backend/demo.py": "# ordinary production source\n",
        "backend/test_demo.py": "# test source must not ship\n",
        "backend/demo/tests/test_nested.py": "# nested test source must not ship\n",
        "archive/vendor-sdks/sdk/example.py": "# adopted reference source must not ship\n",
        "deploy/bento/service.py": "# alternate non-live serving path\n",
        "desktop-client/src-tauri/Cargo.toml": "# separate deliverable\n",
        "yocto/oematch/pyproject.toml": "# separate package\n",
        "garbo/review.md": "# review residue\n",
        "incoming/example/PROVENANCE.md": "# import staging\n",
        "tests/frontend.mjs": "// browser test source\n",
        "PROJECT-TASKS.md": "# work ledger\n",
        "backend/remix/.env": (
            "SPOTIFY_CLIENT_SECRET=fake-sandbox-value-for-the-leak-guard-test\n"
            "DJ_TOKEN=fake-sandbox-value-for-the-leak-guard-test\n"),
        "training/corpus.jsonl": '{"fake": "sandbox corpus line, not the real one"}\n',
        "training/build_dataset.py": "# sandbox stub\n",
        "README.md": "sandbox\n",
        "bin/symoneural-cli": "#!/usr/bin/env python3\n",
        "scripts/noop.sh": "#!/bin/sh\n",
    }.items():
        path = sandbox / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    # The REAL guard library, copied in rather than stubbed: build-deb.sh sources it by
    # path, and a stub here would mean these tests assert against a guard that is not the
    # one that ships. Tracked in the sandbox, exactly as it is tracked in this repo.
    lib = sandbox / "scripts" / "lib" / "archive-guard.sh"
    lib.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(GUARD_LIB, lib)
    git = ["git", "-C", str(sandbox), "-c", "user.name=sandbox",
           "-c", "user.email=sandbox@invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(sandbox)], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", "sandbox"], check=True)
    return sandbox


def run_build(tmp: Path, script_text: str, *extra_args: str
              ) -> tuple[subprocess.CompletedProcess, Path]:
    """Drop `script_text` into the sandbox as its build-deb.sh and run it.

    TMPDIR is pointed inside the test's own directory so the script's `mktemp -d` stage
    never lands in the shared /tmp, and `-o` keeps the built .deb out of ~/Downloads.
    """
    sandbox = make_sandbox(tmp)
    script = sandbox / "scripts" / "build-deb.sh"
    script.write_text(script_text)
    script.chmod(0o755)
    out = tmp / "out"
    stage = tmp / "stage"
    out.mkdir()
    stage.mkdir()
    proc = subprocess.run(["bash", str(script), *extra_args, "-o", str(out)],
                          capture_output=True, text=True, env={
                              "PATH": "/usr/bin:/bin:/usr/sbin", "TMPDIR": str(stage),
                              "HOME": str(tmp)})  # set -u: the script reads $HOME at :24
    return proc, out


def payload_listing(out: Path) -> str:
    """The tar listing of the one built .deb -- paths only, never contents."""
    debs = sorted(out.glob("symoneural_*.deb"))
    assert len(debs) == 1, f"expected exactly one .deb in {out}, found {len(debs)}"
    return subprocess.run(["dpkg-deb", "-c", str(debs[0])],
                          capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class BuildDebLeakGuardTests(unittest.TestCase):

    def setUp(self):
        self.real = SCRIPT.read_text()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    # -- surgery helpers -----------------------------------------------------------------
    # Each asserts its target exists exactly once before cutting, so a drift in the real
    # script fails here with a message, not downstream with a green test of nothing.

    def without_remix_exclusion(self, text: str) -> str:
        self.assertEqual(text.count(REMIX_CLAUSE), 1,
                         "EXCLUDE_RE's remix clause moved or changed spelling; "
                         "re-point REMIX_CLAUSE at it")
        return text.replace(REMIX_CLAUSE, "")

    def without_guard(self, text: str) -> str:
        start = text.index(GUARD_FIRST_LINE)
        end = text.index(GUARD_LAST_LINE) + len(GUARD_LAST_LINE)
        self.assertLess(start, end)
        return text[:start] + text[end:]

    # -- behaviour -----------------------------------------------------------------------

    def test_a_clean_build_keeps_every_protected_path_out(self):
        """The regex and the guard cooperating: exit 0, and no protected path shipped."""
        proc, out = run_build(self.tmp, self.real)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        listing = payload_listing(out)
        self.assertIn("opt/symoneural/backend/server.py", listing,
                      "payload is empty -- the leak checks below would pass vacuously")
        self.assertIn("opt/symoneural/backend/demo.py", listing)
        for leak in ("remix/.env", "corpus.jsonl", "build_dataset.py"):
            self.assertNotIn(leak, listing, f"{leak} shipped in a clean build")
        for nonprod in ("archive/vendor-sdks/", "test_demo.py", "/tests/", "deploy/bento/",
                        "desktop-client/", "yocto/", "garbo/", "incoming/",
                        "PROJECT-TASKS.md"):
            self.assertNotIn(nonprod, listing, f"non-production path {nonprod} shipped")

    def test_list_mode_previews_the_same_production_boundary_without_building(self):
        proc, out = run_build(self.tmp, self.real, "--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("backend/server.py", proc.stdout)
        self.assertIn("backend/demo.py", proc.stdout)
        self.assertNotIn("archive/vendor-sdks/", proc.stdout)
        self.assertNotIn("test_demo.py", proc.stdout)
        self.assertEqual(list(out.glob("*.deb")), [])

    def test_the_guard_fires_when_the_exclusion_regex_regresses(self):
        """The event the guard exists for: EXCLUDE_RE loses its remix clause.

        This is the first time build-deb.sh:82-92 has ever executed its failure arm.
        Audit item 8's exact fix shape: exit 1, the path named, and no package built.
        """
        proc, out = run_build(self.tmp, self.without_remix_exclusion(self.real))
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("LEAK: backend/remix/.env", proc.stderr)
        self.assertIn("REFUSING", proc.stderr)
        self.assertIn("refusing to build", proc.stderr)
        self.assertEqual(list(out.glob("*.deb")), [], "a .deb was built despite the leak")

    def test_removing_the_guard_ships_the_secret(self):
        """The mutation check, kept in the suite permanently.

        With the regex weakened AND the guard deleted, the build must SUCCEED and the fake
        secret must be demonstrably inside the package. That is what proves the exit 1 in
        the test above is produced by the guard lines and by nothing else -- and it is the
        v1 .deb incident (build-deb.sh:65-67) reproduced on purpose, in a sandbox, with
        fake values.
        """
        mutated = self.without_guard(self.without_remix_exclusion(self.real))
        proc, out = run_build(self.tmp, mutated)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("opt/symoneural/backend/remix/.env", payload_listing(out),
                      "the secret did not ship, so something besides the guard blocks it "
                      "and the two tests above are not testing what they claim")

    # -- structure -----------------------------------------------------------------------

    def test_the_real_script_still_carries_what_the_surgery_targets(self):
        """Pins the real script to the three strings the tests above cut, so the surgery
        stays representative rather than silently editing text that no longer exists."""
        for needle in (REMIX_CLAUSE, GUARD_FIRST_LINE, GUARD_LAST_LINE):
            self.assertIn(needle, self.real,
                          f"build-deb.sh no longer contains {needle!r}")

    def test_the_protected_path_list_still_lives_in_the_shared_guard(self):
        """The other half of the old structural test.

        This list used to be spelled out inside build-deb.sh and was pinned there. It now
        lives in the shared library, so it is pinned there -- the assertion is unchanged in
        substance, it just follows the code. `training/project-history/` is the reason this
        test exists: it was added to the .deb's list when that directory landed, and a
        second copy of the list in another packaging path would not have been updated.
        """
        body = GUARD_LIB.read_text()
        for needle in ("training/corpus", "training/build_dataset",
                       "training/project-history/", "training/adapter",
                       r"\.claude/", "env"):
            self.assertIn(needle, body,
                          f"the shared guard no longer covers {needle!r}")

    def test_the_deb_asks_for_the_shareable_mode(self):
        """A .deb leaves the box, so `local-authorized` would be the wrong mode and would
        let the payload ship protected material as long as a manifest named it."""
        self.assertIn("archive_guard shareable", self.real)
        self.assertNotIn("archive_guard local-authorized", self.real)


if __name__ == "__main__":
    unittest.main()
