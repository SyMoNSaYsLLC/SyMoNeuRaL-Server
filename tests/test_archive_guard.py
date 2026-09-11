"""The shared archive leak guard -- scripts/lib/archive-guard.sh.

The guard exists because `build-deb.sh` had a leak check and the other two packaging paths
(the repo tar.gz, the shareable allv3 archives) had none. A check that lives inside one
script protects one script. These tests pin the behaviour every archive path now inherits.

Note on assertion style: the guard reports findings BY PATH, and those paths are inside a
random `tempfile` directory. A short sentinel checked with `assertNotIn` against that output
would collide with the random directory name -- that is a measured ~1% flake, fixed
elsewhere in this repo at `670edb1`. Every sentinel below is long and distinctive on
purpose, and absence claims are made against output with the path component removed.
"""

import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
GUARD = REPO / "scripts" / "lib" / "archive-guard.sh"


def run_guard(mode, root, guard=None):
    """Invoke archive_guard in a fresh bash and return (rc, stderr)."""
    guard = guard or GUARD
    script = f'set -euo pipefail\nsource "{guard}"\narchive_guard {mode} "{root}" testarchive\n'
    p = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=120
    )
    return p.returncode, p.stderr


def make_tree(root, files):
    """files: {relative path: contents}. A path ending in '/' makes a directory."""
    for rel, body in files.items():
        target = pathlib.Path(root) / rel
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)


class ArchiveGuardExists(unittest.TestCase):
    def test_the_guard_library_is_present_and_sources_cleanly(self):
        self.assertTrue(GUARD.is_file(), f"{GUARD} missing")
        p = subprocess.run(
            ["bash", "-c", f'source "{GUARD}" && declare -F archive_guard'],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("archive_guard", p.stdout)

    def test_an_unknown_mode_is_an_error_not_a_pass(self):
        with tempfile.TemporaryDirectory() as td:
            rc, err = run_guard("whatever", td)
        self.assertEqual(rc, 2, err)

    def test_a_missing_root_is_an_error_not_a_pass(self):
        rc, err = run_guard("shareable", "/nonexistent-archive-root-for-test")
        self.assertEqual(rc, 2, err)


class ShareableModeRefuses(unittest.TestCase):
    """A shareable artifact leaves the box. Any protected item is fatal."""

    def _refuses(self, files, needle):
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, files)
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 1, f"expected refusal, got rc={rc}\n{err}")
        self.assertIn("REFUSING", err)
        self.assertIn(needle, err)

    def test_a_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {
                "README.md": "hello\n",
                "backend/server.py": "x = 1\n",
                "backend/miner.env.example": "VLLM_API_KEY=\n",
            })
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 0, err)
        self.assertIn("clean", err)

    def test_a_real_env_file_is_refused(self):
        self._refuses({"backend/remix/.env": "PLACEHOLDER=1\n"}, ".env")

    def test_an_env_variant_that_is_not_dot_env_is_still_refused(self):
        # `remix.env.pre-rotation-20260820` is exactly the shape of the vault file this
        # rotation produced. A path list that only knows `.env` would miss it.
        self._refuses({"remix.env.pre-rotation-20260820": "PLACEHOLDER=1\n"}, "remix.env")

    def test_the_corpus_is_refused(self):
        self._refuses({"training/corpus.jsonl": "{}\n"}, "corpus.jsonl")

    def test_the_dataset_builder_is_refused(self):
        self._refuses({"training/build_dataset.py": "pass\n"}, "build_dataset.py")

    def test_an_adapter_directory_is_refused(self):
        self._refuses({"training/adapter/adapter_config.json": "{}\n"}, "adapter")

    def test_a_suffixed_adapter_directory_is_refused(self):
        self._refuses({"training/adapter-qwen36/adapter_config.json": "{}\n"}, "adapter-qwen36")

    def test_the_claude_directory_is_refused(self):
        self._refuses({".claude/HANDOVER.md": "state\n"}, ".claude")

    def test_a_git_directory_is_refused(self):
        # The decisive one. backend/remix/.env was tracked from 9b5da84 until it was
        # untracked at d453c65, so history carries the pre-rotation values --  including
        # SPOTIFY_CLIENT_SECRET, which is provider-issued and was never rotated. A tarball
        # with .git in it is a tarball with a live credential in it.
        self._refuses({".git/config": "[core]\n", ".git/objects/": ""}, ".git")

    def test_a_dot_env_example_is_not_a_leak(self):
        # It documents which keys exist and carries no values. Refusing it would push
        # people to delete the documentation, which is the wrong direction.
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {"backend/studio/plugins/discovery/symoneural-discovery.env.example": "VLLM_API_KEY=\n"})
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 0, err)

    def test_there_is_no_override_flag(self):
        body = GUARD.read_text()
        for escape in ("ARCHIVE_GUARD_FORCE", "--force", "SKIP_GUARD", "IGNORE_LEAK"):
            self.assertNotIn(escape, body, f"an override named {escape} exists")


class ContentScanCatchesRenamedSecrets(unittest.TestCase):
    """A path list catches `.env`. Only a content scan catches a copy under any other name."""

    def test_a_file_assigning_a_secret_key_is_caught_whatever_it_is_called(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {"notes/scratch.txt": "VLLM_API_KEY=deadbeefdeadbeef\n"})
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 1, err)
        self.assertIn("scratch.txt", err)
        self.assertIn("secret key", err)

    def test_an_empty_assignment_is_not_a_finding(self):
        # `KEY=` with no value is what a .example file looks like; flagging it would make
        # the guard fire on its own documentation.
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {"notes/keys.txt": "DJ_TOKEN=\nSPOTIFY_CLIENT_ID=\n"})
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 0, err)

    def test_the_guard_never_prints_a_secret_value(self):
        # Standing rule: key names and lengths only, never values. The guard reports the
        # PATH of an offending file, never a line from inside it.
        VALUE = "SENTINELSECRETVALUEMUSTNEVERBEPRINTEDBYTHEGUARD"
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {"notes/scratch.txt": f"VLLM_API_KEY={VALUE}\n"})
            rc, err = run_guard("shareable", td)
        self.assertEqual(rc, 1, err)
        self.assertNotIn(VALUE, err)


class LocalAuthorisedModeRequiresAManifest(unittest.TestCase):
    """The owner's backup of his own trade secret is not a leak. An UNLABELLED one is."""

    PROTECTED = {
        "training/corpus.jsonl": "{}\n",
        "backend/remix/.env": "PLACEHOLDER=1\n",
    }

    def test_protected_material_with_no_manifest_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, dict(self.PROTECTED))
            rc, err = run_guard("local-authorized", td)
        self.assertEqual(rc, 1, err)
        self.assertIn("no SECRETS-INSIDE.txt", err)

    def test_protected_material_named_in_the_manifest_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            files = dict(self.PROTECTED)
            files["SECRETS-INSIDE.txt"] = textwrap.dedent("""\
                This archive deliberately contains protected material.
                training/corpus.jsonl
                backend/remix/.env
                """)
            make_tree(td, files)
            rc, err = run_guard("local-authorized", td)
        self.assertEqual(rc, 0, err)
        self.assertIn("all named in SECRETS-INSIDE.txt", err)

    def test_a_manifest_that_misses_one_item_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            files = dict(self.PROTECTED)
            files["SECRETS-INSIDE.txt"] = "training/corpus.jsonl\n"   # .env not named
            make_tree(td, files)
            rc, err = run_guard("local-authorized", td)
        self.assertEqual(rc, 1, err)
        self.assertIn("UNDECLARED", err)
        self.assertIn(".env", err)

    def test_a_git_directory_is_allowed_locally(self):
        # A backup without history is not a backup. .git is shareable-only.
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {".git/config": "[core]\n", "README.md": "hi\n"})
            rc, err = run_guard("local-authorized", td)
        self.assertEqual(rc, 0, err)

    def test_a_clean_local_archive_needs_no_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            make_tree(td, {"README.md": "hi\n"})
            rc, err = run_guard("local-authorized", td)
        self.assertEqual(rc, 0, err)


class MutationCheck(unittest.TestCase):
    """Prove the refusal is the guard's, not an accident of the harness.

    Every other test here asserts `rc == 1` on a tree containing a leak. That assertion
    passes just as well if the function is broken and returns 1 always. This test weakens
    the guard in a sandbox copy and shows the same tree then builds -- which is what makes
    the assertions above mean what they say.
    """

    def test_neutering_the_path_list_lets_the_corpus_through(self):
        body = GUARD.read_text()
        self.assertIn("training/corpus\\.jsonl$", body)
        weakened = body.replace("training/corpus\\.jsonl$", "training/NEVERMATCHES\\.jsonl$")
        self.assertNotEqual(weakened, body, "mutation did not apply -- the pattern moved")
        with tempfile.TemporaryDirectory() as td:
            sandbox = pathlib.Path(td) / "archive-guard.sh"
            sandbox.write_text(weakened)
            with tempfile.TemporaryDirectory() as tree:
                make_tree(tree, {"training/corpus.jsonl": "{}\n"})
                rc_real, _ = run_guard("shareable", tree)
                rc_weak, _ = run_guard("shareable", tree, guard=sandbox)
        self.assertEqual(rc_real, 1, "the real guard should refuse the corpus")
        self.assertEqual(rc_weak, 0, "the weakened guard should let it through")

    def test_neutering_the_git_rule_lets_history_through(self):
        body = GUARD.read_text()
        weakened = body.replace('[ -e "$root/.git" ]', '[ -e "$root/.git-NEVERMATCHES" ]')
        self.assertNotEqual(weakened, body, "mutation did not apply -- the .git test moved")
        with tempfile.TemporaryDirectory() as td:
            sandbox = pathlib.Path(td) / "archive-guard.sh"
            sandbox.write_text(weakened)
            with tempfile.TemporaryDirectory() as tree:
                make_tree(tree, {".git/config": "[core]\n"})
                rc_real, _ = run_guard("shareable", tree)
                rc_weak, _ = run_guard("shareable", tree, guard=sandbox)
        self.assertEqual(rc_real, 1)
        self.assertEqual(rc_weak, 0)


class TheCombinedRegexIsValid(unittest.TestCase):
    """A regression test for a real false-green.

    The pattern table was first written `pattern|reason`, split with `cut -d'|' -f1`. The
    patterns are extended-regex and contain `|` themselves, so `(^|/)\\.env$` was truncated
    to `(^`. grep died with "Unmatched ( or \\(" on stderr, matched nothing, and the guard
    reported the tree CLEAN. A broken scanner that says "clean" is worse than one that
    crashes, so the validity of the assembled regex is now asserted directly.
    """

    def test_the_assembled_path_regex_compiles_in_grep(self):
        script = (
            f'source "{GUARD}"\n'
            'combined="$(_ag_forbidden_paths | cut -f1 | paste -sd"|" -)"\n'
            'printf "%s\\n" "training/corpus.jsonl" | grep -E "$combined" >/dev/null\n'
            'echo "REGEX-COMPILED-AND-MATCHED"\n'
        )
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
        self.assertNotIn("Unmatched", p.stderr)
        self.assertIn("REGEX-COMPILED-AND-MATCHED", p.stdout, p.stderr)

    def test_every_row_in_the_table_has_a_pattern_and_a_reason(self):
        p = subprocess.run(
            ["bash", "-c", f'source "{GUARD}" && _ag_forbidden_paths'],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = [r for r in p.stdout.splitlines() if r.strip()]
        self.assertGreaterEqual(len(rows), 5)
        for row in rows:
            self.assertIn("\t", row, f"row has no TAB separator: {row!r}")
            pattern, reason = row.split("\t", 1)
            self.assertTrue(pattern.strip(), f"empty pattern in {row!r}")
            self.assertTrue(reason.strip(), f"pattern {pattern!r} has no recorded reason")

    def test_each_pattern_individually_compiles(self):
        p = subprocess.run(
            ["bash", "-c", f'source "{GUARD}" && _ag_forbidden_paths'],
            capture_output=True, text=True, timeout=60,
        )
        for row in [r for r in p.stdout.splitlines() if r.strip()]:
            pattern = row.split("\t", 1)[0]
            q = subprocess.run(
                ["grep", "-E", pattern], input="", capture_output=True, text=True, timeout=30
            )
            self.assertNotIn("Unmatched", q.stderr, f"pattern does not compile: {pattern!r}")
            self.assertIn(q.returncode, (0, 1), f"grep errored on {pattern!r}: {q.stderr}")


class EveryPackagingPathCallsIt(unittest.TestCase):
    """The whole point of the extraction. If a new archive path lands without the guard,
    this test is what notices."""

    PACKAGING = ["scripts/build-deb.sh"]

    def test_known_packaging_scripts_source_the_guard(self):
        missing = []
        for rel in self.PACKAGING:
            p = REPO / rel
            if not p.is_file():
                missing.append(f"{rel} (absent)")
                continue
            body = p.read_text()
            if "archive-guard.sh" not in body or "archive_guard " not in body:
                missing.append(rel)
        self.assertEqual(missing, [], f"packaging paths not calling the shared guard: {missing}")


if __name__ == "__main__":
    unittest.main()
