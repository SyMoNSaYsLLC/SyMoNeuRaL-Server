"""tools/export_snapshot.sh -- allow-list construction and fail-closed refusal.

`docs/ops/EXPORTS.md` rule 4 makes this script the only sanctioned way a snapshot leaves
this box, so the thing worth testing is not that it can write a zip. It is that it REFUSES,
and that a path nobody classified does not ship.

## Everything here is synthetic

No test touches a real protected artefact. The fixture tree is built in a fresh `mktemp`
directory on every run and contains files this repo has never had -- `corpus.jsonl` here
holds the bytes `SYNTHETIC-FIXTURE-NOT-REAL-DATA`, not the 327 examples. Planting a sentinel
into a real protected path to see whether the exporter notices would be the same mistake the
exporter exists to prevent.

## The unclassified-path test is the one that matters

Allow-list and deny-list architectures agree on the easy cases: both ship an allowed file
and both refuse a known-protected one. They give OPPOSITE answers for a harmless file that
nobody classified -- deny-list ships it, allow-list does not. So `test_unclassified_path_
is_excluded` is what actually distinguishes the implemented architecture from the one the
A-2 contract forbids, and it asserts absence is caused by the allow-list rather than by an
ignore rule: the file is inside the manifest-named directory's sibling, plainly visible to
the exporter, and simply never named.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPORTER = ROOT / "tools" / "export_snapshot.sh"

SENTINEL = "SYNTHETIC-FIXTURE-NOT-REAL-DATA"


class _ExporterFixture(unittest.TestCase):
    """Shared synthetic fixture + invocation helpers.

    Split out from the test cases so the P1 class below can reuse the fixture WITHOUT
    inheriting -- and therefore re-running -- the A-2 cases. Subclassing a TestCase to get
    at its setUp silently doubles every inherited test, which inflates the pass count and
    makes a regression report say 29 when it means 22.
    """

    # Committed with explicit identity and gpgsign off, so the fixture neither reads nor
    # depends on the operator's global git config -- and cannot be broken by it.
    GIT_ID = ("-c", "user.email=fixture@invalid", "-c", "user.name=P2 Fixture",
              "-c", "commit.gpgsign=false")

    def _git(self, *args: str, check: bool = True):
        r = subprocess.run(["git", *self.GIT_ID, "-C", str(self.root), *args],
                           capture_output=True, text=True)
        if check:
            self.assertEqual(r.returncode, 0, f"fixture git {args} failed: {r.stderr}")
        return r

    def setUp(self):
        self.assertTrue(EXPORTER.is_file(), f"exporter missing at {EXPORTER}")
        self.assertTrue(os.access(EXPORTER, os.X_OK), "exporter is not executable")
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="a2-export-fixture-"))
        self.root = self.tmp / "fixture-root"
        (self.root / "deliverable").mkdir(parents=True)
        (self.root / "deliverable" / "app.txt").write_text(f"{SENTINEL} allowed\n")
        (self.root / "deliverable" / "readme.md").write_text(f"{SENTINEL} allowed\n")
        # Harmless, present, and deliberately NOT named in any manifest.
        (self.root / "unlisted").mkdir()
        (self.root / "unlisted" / "notes.txt").write_text(f"{SENTINEL} unclassified\n")

        # P2 made the fixture a real repository. The exporter now refuses when release
        # identity cannot resolve, so a plain mktemp directory -- which is what this fixture
        # used to be -- is no longer a valid export root. It is also the only way to test
        # drift at all: drift is defined against HEAD, so there must be a HEAD.
        #
        # `git init` inside mktemp, never inside this repository, so git cannot discover the
        # parent and compare fixture files against SyMoNeuRaL's own HEAD.
        self._git("init", "-q", ".")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "fixture baseline")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------------------
    def _manifest(self, *lines: str) -> pathlib.Path:
        p = self.tmp / "fixture-scope.manifest"
        p.write_text("# synthetic A-2 test fixture -- not a production manifest\n"
                     + "\n".join(lines) + "\n")
        return p

    def _run(self, manifest: pathlib.Path, out: pathlib.Path | None, *extra: str):
        argv = ["bash", str(EXPORTER), "--manifest", str(manifest), "--root", str(self.root)]
        if out is not None:
            argv += ["--out", str(out)]
        argv += list(extra)
        return subprocess.run(argv, capture_output=True, text=True)


class ExportSnapshotTests(_ExporterFixture):
    """A-2 contract: allow-list construction and fail-closed refusal."""

    # -- positive --------------------------------------------------------------------
    def test_allowed_path_is_exported(self):
        """An explicitly named path ships, and the archive is inspectable."""
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0, f"expected success, got {r.returncode}: {r.stderr}")
        self.assertTrue(out.is_file(), "no archive was produced")

        names = zipfile.ZipFile(out).namelist()
        self.assertIn("deliverable/app.txt", names)
        self.assertIn("deliverable/readme.md", names)
        self.assertIn("EXPORT-MANIFEST", names)

        manifest_text = zipfile.ZipFile(out).read("EXPORT-MANIFEST").decode()
        self.assertIn("source-sha:", manifest_text, "manifest must name the source SHA")
        self.assertIn("deliverable/app.txt", manifest_text)
        # A checksum per file, so a recipient can verify what they received.
        self.assertIn("sha256", manifest_text)

    # -- the architecture-distinguishing test ----------------------------------------
    def test_unclassified_path_is_excluded(self):
        """A harmless unnamed file must NOT ship. Deny-list would ship it; allow-list does not."""
        out = self.tmp / "export.zip"
        # Prove the file is really there and visible to the exporter before we assert absence.
        self.assertTrue((self.root / "unlisted" / "notes.txt").is_file())

        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0, r.stderr)

        names = zipfile.ZipFile(out).namelist()
        self.assertNotIn("unlisted/notes.txt", names,
                         "unclassified path leaked -- this is deny-list behaviour")
        # Absence must be caused by the allow-list, not by an ignore rule: naming it ships it.
        out2 = self.tmp / "export2.zip"
        r2 = self._run(self._manifest("deliverable", "unlisted"), out2)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertIn("unlisted/notes.txt", zipfile.ZipFile(out2).namelist(),
                      "file is ignorable, so the first absence proved nothing")

    # -- negative / fail-closed --------------------------------------------------------
    def test_protected_path_is_refused(self):
        """A synthetic protected artefact in the candidate set aborts the export."""
        # Synthetic file at a path that matches a protected CLASS. Contents are a marker.
        (self.root / "training").mkdir()
        (self.root / "training" / "corpus.jsonl").write_text(f'{{"{SENTINEL}": true}}\n')
        planted = self.root / "training" / "corpus.jsonl"
        self.assertTrue(planted.is_file(), "precondition: prohibited artefact must be present")

        out = self.tmp / "must-not-exist.zip"
        # An over-broad manifest entry -- exactly the stage-1 mistake stage 2 exists to catch.
        r = self._run(self._manifest("deliverable", "training"), out)

        self.assertNotEqual(r.returncode, 0, "exporter did not refuse a protected path")
        self.assertFalse(out.exists(), "an archive was emitted despite refusal")
        self.assertIn("PROTECTED", r.stderr, "refusal must name the offending class")
        self.assertIn("corpus.jsonl", r.stderr, "refusal must name the offending path")
        self.assertNotIn(SENTINEL, r.stderr, "refusal must not print file contents")

    def test_refusal_precedes_archive_creation(self):
        """No partial archive survives a refusal."""
        (self.root / "run").mkdir()
        (self.root / "run" / "state.db").write_text(f"{SENTINEL}\n")
        out = self.tmp / "partial.zip"
        r = self._run(self._manifest("deliverable", "run"), out)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(out.exists(), "partial archive left on disk after refusal")

    # -- interface safety --------------------------------------------------------------
    def test_no_manifest_is_refused(self):
        """There is no implicit whole-repo export."""
        r = subprocess.run(["bash", str(EXPORTER), "--out", str(self.tmp / "x.zip")],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--manifest is required", r.stderr)

    def test_traversal_is_refused(self):
        """A manifest cannot escape the root."""
        r = self._run(self._manifest("../../etc/passwd"), self.tmp / "x.zip")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("traversal", r.stderr)

    def test_missing_manifest_path_is_refused(self):
        """A manifest that no longer matches the tree must not silently ship less."""
        r = self._run(self._manifest("deliverable", "gone"), self.tmp / "x.zip")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not exist", r.stderr)



# ==========================================================================================
# P1 (D-11) -- signing-material exclusions.
#
# WHY THIS EXISTS BEFORE ANY KEY DOES. Measured 2026-09-02 against the then-live 17 patterns:
# `ops/keys/release.asc`, `.gnupg/pubring.kbx`, `ops/release.gpg`, `ops/release.minisig`,
# `ops/signing/release_ed25519` and its `.pub` ALL passed stage 2. That was harmless only
# because zero keys existed. Generating a key first would have opened a window in which the
# private half was exportable, so P1 is a prerequisite of the key ceremony, not a follow-up.
#
# NO REAL KEY MATERIAL IS USED. Every fixture below is a synthetic armor header over the
# bytes SYNTHETIC-FIXTURE-NOT-REAL-DATA. There is no key to extract from this file, and
# generating a real one to test with would be the exact mistake the control exists to prevent.
#
# Note the consequence of content-based detection: a manifested file that merely QUOTES a
# private-key header now refuses. That is correct fail-closed behaviour. It also means this
# test file must never appear in an export manifest -- and it does not.
# ==========================================================================================

# Synthetic armor headers. Real keys are ~1.6 KB of base64 after the header; these are the
# header line only, which is what the control matches on.
PRIVATE_PGP = f"-----BEGIN PGP PRIVATE KEY BLOCK-----\n{SENTINEL}\n-----END PGP PRIVATE KEY BLOCK-----\n"
PRIVATE_SSH = f"-----BEGIN OPENSSH PRIVATE KEY-----\n{SENTINEL}\n-----END OPENSSH PRIVATE KEY-----\n"
PRIVATE_PEM = f"-----BEGIN RSA PRIVATE KEY-----\n{SENTINEL}\n-----END RSA PRIVATE KEY-----\n"
# The carve-out. Note PUBLIC: none of the three private patterns match this line, which is
# why P1-c needs no special case in the exporter -- only a test that keeps it that way.
PUBLIC_PGP = f"-----BEGIN PGP PUBLIC KEY BLOCK-----\n{SENTINEL}\n-----END PGP PUBLIC KEY BLOCK-----\n"


class P1SigningMaterialExclusionTests(_ExporterFixture):
    """P1-a path/name rules, P1-b content detection, P1-c public-material carve-out."""

    def _refused(self, r, out: pathlib.Path, *, expect_in_stderr: str):
        """Every P1 refusal owes the same three things: non-zero, diagnosable, no archive."""
        self.assertNotEqual(r.returncode, 0, f"exporter did NOT refuse: {r.stdout}")
        self.assertFalse(out.exists(), "an archive was emitted despite refusal")
        self.assertIn("PROTECTED", r.stderr, "refusal must name a protected class")
        self.assertIn(expect_in_stderr, r.stderr,
                      f"refusal must be diagnosable; stderr was: {r.stderr}")
        self.assertNotIn(SENTINEL, r.stderr, "refusal must never print file contents")

    # -- P1-a: unambiguously private by path or name -----------------------------------
    def test_p1a_kbx_keybox_refused(self):
        (self.root / "deliverable" / "pubring.kbx").write_text(f"{SENTINEL}\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="pubring.kbx")

    def test_p1a_private_keys_v1d_refused(self):
        d = self.root / "deliverable" / "private-keys-v1.d"
        d.mkdir()
        (d / "ABCD1234.key").write_text(f"{SENTINEL}\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="private-keys-v1.d")

    def test_p1a_gnupg_home_refused(self):
        d = self.root / "deliverable" / ".gnupg"
        d.mkdir()
        (d / "trustdb.gpg").write_text(f"{SENTINEL}\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr=".gnupg")

    def test_p1a_minisig_refused(self):
        (self.root / "deliverable" / "release.minisig").write_text(f"{SENTINEL}\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="release.minisig")

    def test_p1a_ops_keys_dir_refused(self):
        """Refused by LOCATION: the custody directory is protected whatever the file is named."""
        d = self.root / "ops" / "keys"
        d.mkdir(parents=True)
        # Deliberately innocuous name and innocuous contents -- location alone must refuse.
        (d / "notes.txt").write_text(f"{SENTINEL} not actually a key\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable", "ops"), out), out,
                      expect_in_stderr="ops/keys/notes.txt")

    def test_p1a_ops_signing_dir_refused(self):
        d = self.root / "ops" / "signing"
        d.mkdir(parents=True)
        (d / "notes.txt").write_text(f"{SENTINEL} not actually a key\n")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable", "ops"), out), out,
                      expect_in_stderr="ops/signing/notes.txt")

    # -- P1-b: content detection, independent of name ----------------------------------
    # Each fixture sits under deliverable/ at a name that NO P1-a pattern matches. If one
    # were placed at ops/keys/*.asc it would refuse for the wrong reason and prove nothing
    # about content inspection.
    def test_p1b_armored_pgp_private_key_content_refused(self):
        (self.root / "deliverable" / "release.asc").write_text(PRIVATE_PGP)
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="(content)")

    def test_p1b_openssh_private_key_content_refused(self):
        """Named .gpg, contents are OpenSSH. Name says one thing, bytes say another."""
        (self.root / "deliverable" / "thing.gpg").write_text(PRIVATE_SSH)
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="OpenSSH private key (content)")

    def test_p1b_generic_pem_private_key_content_refused(self):
        """EXTENSIONLESS. No name pattern can reach this without refusing arbitrary files."""
        (self.root / "deliverable" / "nokey").write_text(PRIVATE_PEM)
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="deliverable/nokey")

    def test_p1b_detection_is_extension_independent(self):
        """The SAME bytes must refuse under every name, including a .txt web asset."""
        for name in ("release.asc", "thing.gpg", "nokey", "innocuous.txt", "notes.md"):
            with self.subTest(name=name):
                target = self.root / "deliverable" / name
                target.write_text(PRIVATE_SSH)
                out = self.tmp / f"must-not-exist-{name}.zip"
                self._refused(self._run(self._manifest("deliverable"), out), out,
                              expect_in_stderr="(content)")
                target.unlink()

    def test_p1b_leading_nul_does_not_bypass(self):
        """A binary prefix must not turn a private key into 'binary file, skipped'."""
        (self.root / "deliverable" / "padded").write_bytes(
            b"\x00\x00\x00binary junk\n" + PRIVATE_SSH.encode())
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="(content)")

    def test_p1b_large_file_does_not_bypass(self):
        """The header sits ~4 MB in, AFTER the padding.

        This is the test that fails if anyone 'optimises' the scan with `head -c`. A byte
        cap is not a performance tweak, it is the bypass: pad past the cap and the key ships.
        """
        big = self.root / "deliverable" / "big.bin"
        with big.open("wb") as fh:
            fh.write(b"padding padding padding\n" * 175_000)   # ~4 MB of noise first
            fh.write(PRIVATE_SSH.encode())                      # header near the END
        self.assertGreater(big.stat().st_size, 4_000_000, "fixture is not actually large")
        out = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable"), out), out,
                      expect_in_stderr="(content)")

    def test_p1b_uninspectable_candidate_is_refused(self):
        """An inspection that could NOT run has not passed.

        grep exits >=2 on an unreadable file. The naive `if grep -q ...; then refuse; fi`
        reads that error as 'no match' and exports the file uninspected. Verified on this
        host: unreadable -> rc 2, clean miss -> rc 1, match -> rc 0.
        """
        blocked = self.root / "deliverable" / "unreadable.bin"
        blocked.write_text(f"{SENTINEL}\n")
        blocked.chmod(0o000)
        try:
            if os.access(blocked, os.R_OK):
                self.skipTest("running as root; file modes do not restrict reads")
            out = self.tmp / "must-not-exist.zip"
            self._refused(self._run(self._manifest("deliverable"), out), out,
                          expect_in_stderr="uninspectable")
        finally:
            blocked.chmod(0o644)

    # -- P1-c: the carve-out that keeps P1 from over-blocking ---------------------------
    def test_p1c_public_armored_keyring_is_exportable(self):
        """A PUBLIC keyring .asc MUST still export.

        This is the load-bearing test of P1-c, in the same sense that
        `test_unclassified_path_is_excluded` is load-bearing for A-2. P1 is only correct if
        it discriminates private signing material from public verification material. A
        recipient cannot verify anything without the public key, so refusing it would break
        the very release chain D-11 exists to build.

        It will FAIL LOUDLY if a future change adds a blanket ``.asc`` suffix prohibition
        -- which
        is exactly why it is written as a positive assertion about archive contents rather
        than a comment asking people not to do that.
        """
        keyring = self.root / "deliverable" / "symoneural-archive-keyring.asc"
        keyring.write_text(PUBLIC_PGP)
        # Must be COMMITTED, not merely present: since P2, an untracked candidate is refused
        # as "not present in HEAD". Committing it keeps this a test of P1-c (is public
        # material exportable?) rather than an accidental test of P2-b.
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "public keyring fixture")
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0,
                         f"public keyring was refused -- P1 is over-blocking: {r.stderr}")
        self.assertTrue(out.is_file(), "no archive produced for a legitimate public export")
        self.assertIn("deliverable/symoneural-archive-keyring.asc",
                      zipfile.ZipFile(out).namelist(),
                      "public verification material must be present in the archive")

    # -- scope: a refusal control, not a repository scanner ----------------------------
    def test_p1_inspects_only_manifested_candidates(self):
        """An UNMANIFESTED private key must not even be looked at.

        If P1 were a repository-wide secret scanner it would find this and refuse, which
        would be the wrong architecture: it would make every export depend on the state of
        files nobody asked to export. Stage 2b iterates the same CANDIDATES array stage 1
        built, so an unnamed path is never opened.
        """
        (self.root / "unlisted" / "stray.asc").write_text(PRIVATE_SSH)
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0,
                         f"unmanifested key caused a refusal -- P1 became a scanner: {r.stderr}")
        names = zipfile.ZipFile(out).namelist()
        self.assertNotIn("unlisted/stray.asc", names, "unmanifested file leaked into archive")
        # And naming it DOES refuse -- proving the pass above was scope, not a blind spot.
        out2 = self.tmp / "must-not-exist.zip"
        self._refused(self._run(self._manifest("deliverable", "unlisted"), out2), out2,
                      expect_in_stderr="(content)")



# ==========================================================================================
# P2 (D-11) -- non-forgeable release identity.
#
# The archive states a `source-sha`. P2 is what makes that statement mean something.
#
# P2-a  it must RESOLVE. The old code was `git rev-parse HEAD || echo UNKNOWN`, which wrote
#       the literal UNKNOWN and continued. Signing that yields a valid signature over an
#       unidentifiable release -- worse than no signature, because it looks authoritative.
#
# P2-b  the bytes must CORRESPOND to it. The exporter copies from the working tree but
#       labels with HEAD, so a modified candidate ships content the stated commit never
#       contained. A recipient cannot detect it: the checksums match the manifest, and the
#       manifest names a real commit.
#
# P2-c  the label must be BOUND to the release authority, via a signed tag. Verified by a
#       separate tool so the exporter stays runnable with no key.
#
# NO KEY MATERIAL. P2-c injects a stub verifier through SYMONEURAL_TAG_VERIFY_CMD. No key is
# generated, no tag is signed, and `git verify-tag` is never expected to succeed here.
# ==========================================================================================

VERIFIER = ROOT / "tools" / "verify_release_identity.sh"


class P2ReleaseIdentityTests(_ExporterFixture):
    """P2-a unresolved identity, P2-b candidate/HEAD correspondence, P2-c signed-tag binding."""

    def _refused_p2(self, r, out: pathlib.Path, *, expect: str):
        self.assertNotEqual(r.returncode, 0, f"exporter did NOT refuse: {r.stdout}")
        self.assertFalse(out.exists(), "an archive was emitted despite refusal")
        self.assertIn(expect, r.stderr, f"refusal must be diagnosable; stderr: {r.stderr}")

    # -- P2-a ---------------------------------------------------------------------------
    def test_p2a_head_resolution_succeeds_in_a_real_repo(self):
        """The positive control: identity resolves, and the archive states that real SHA."""
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        head = self._git("rev-parse", "HEAD").stdout.strip()
        self.assertRegex(head, r"^[0-9a-f]{40}$")
        manifest_text = zipfile.ZipFile(out).read("EXPORT-MANIFEST").decode()
        self.assertIn(f"source-sha: {head}", manifest_text,
                      "archive must state the resolved HEAD, not a placeholder")

    def test_p2a_non_repository_root_is_refused(self):
        """A root that is not a repository has no release identity at all."""
        bare = self.tmp / "not-a-repo"
        (bare / "deliverable").mkdir(parents=True)
        (bare / "deliverable" / "app.txt").write_text(f"{SENTINEL}\n")
        manifest = self._manifest("deliverable")
        out = self.tmp / "must-not-exist.zip"
        r = subprocess.run(["bash", str(EXPORTER), "--manifest", str(manifest),
                            "--root", str(bare), "--out", str(out)],
                           capture_output=True, text=True)
        self._refused_p2(r, out, expect="release identity unresolved")

    def test_p2a_repository_with_no_commits_is_refused(self):
        """`git init` with no commit: a repository, but HEAD resolves to nothing."""
        fresh = self.tmp / "no-commits"
        (fresh / "deliverable").mkdir(parents=True)
        (fresh / "deliverable" / "app.txt").write_text(f"{SENTINEL}\n")
        subprocess.run(["git", "init", "-q", str(fresh)], check=True,
                       capture_output=True, text=True)
        out = self.tmp / "must-not-exist.zip"
        r = subprocess.run(["bash", str(EXPORTER), "--manifest", str(self._manifest("deliverable")),
                            "--root", str(fresh), "--out", str(out)],
                           capture_output=True, text=True)
        self._refused_p2(r, out, expect="release identity unresolved")

    def test_p2a_unknown_is_never_an_accepted_source_sha(self):
        """UNKNOWN must not survive anywhere as a value -- only in explanatory comments.

        The old fallback made UNKNOWN a legal source-sha. This asserts the exporter can no
        longer emit it: the string appears in no `printf`, no assignment, and no default.
        """
        text = EXPORTER.read_text()
        code_lines = [ln for ln in text.splitlines()
                      if "UNKNOWN" in ln and not ln.lstrip().startswith("#")]
        self.assertEqual(code_lines, [],
                         f"UNKNOWN reachable as a value in exporter code: {code_lines}")

    def test_p2a_unresolved_identity_creates_no_archive(self):
        bare = self.tmp / "bare2"
        (bare / "deliverable").mkdir(parents=True)
        (bare / "deliverable" / "app.txt").write_text(f"{SENTINEL}\n")
        out = self.tmp / "must-not-exist.zip"
        subprocess.run(["bash", str(EXPORTER), "--manifest", str(self._manifest("deliverable")),
                        "--root", str(bare), "--out", str(out)],
                       capture_output=True, text=True)
        self.assertFalse(out.exists(), "archive produced despite unresolved identity")

    def test_p2a_subdirectory_root_is_refused(self):
        """`HEAD:<path>` resolves against the repo root, so a subdirectory root would
        silently compare the WRONG paths. Refused rather than compared incorrectly."""
        out = self.tmp / "must-not-exist.zip"
        manifest = self._manifest("app.txt")
        r = subprocess.run(["bash", str(EXPORTER), "--manifest", str(manifest),
                            "--root", str(self.root / "deliverable"), "--out", str(out)],
                           capture_output=True, text=True)
        self._refused_p2(r, out, expect="repository top level")

    # -- P2-b ---------------------------------------------------------------------------
    def test_p2b_clean_candidate_exports(self):
        """Positive control: committed, unmodified candidates export."""
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deliverable/app.txt", zipfile.ZipFile(out).namelist())

    def test_p2b_modified_candidate_refused_then_restored_succeeds(self):
        """The required sabotage cycle: clean -> modify -> refuse -> restore -> succeed."""
        target = self.root / "deliverable" / "app.txt"
        original = target.read_text()

        out0 = self.tmp / "before.zip"
        self.assertEqual(self._run(self._manifest("deliverable"), out0).returncode, 0)

        target.write_text(f"{SENTINEL} DRIFTED\n")
        out1 = self.tmp / "must-not-exist.zip"
        r = self._run(self._manifest("deliverable"), out1)
        self._refused_p2(r, out1, expect="deliverable/app.txt")
        self.assertIn("DRIFT", r.stderr, "refusal must name the drift class")
        self.assertNotIn(SENTINEL, r.stderr, "refusal must not print file contents")

        # Restore EXACTLY. Success afterwards proves the refusal was caused by the drift.
        target.write_text(original)
        out2 = self.tmp / "after.zip"
        r2 = self._run(self._manifest("deliverable"), out2)
        self.assertEqual(r2.returncode, 0, f"restored tree still refused: {r2.stderr}")
        self.assertTrue(out2.is_file())

    def test_p2b_untracked_candidate_is_refused(self):
        """The hole `diff-index` alone leaves.

        An untracked path does not appear in `diff-index` output, so it reads as CLEAN. But
        stage 1 expands a manifested directory into its files, so an uncommitted file inside
        a named directory becomes a candidate and would ship under a source-sha that never
        contained it. Verified against a throwaway repo before implementing: diff-index
        returns empty for an untracked file.
        """
        (self.root / "deliverable" / "brand-new.txt").write_text(f"{SENTINEL} uncommitted\n")
        out = self.tmp / "must-not-exist.zip"
        r = self._run(self._manifest("deliverable"), out)
        self._refused_p2(r, out, expect="not present in HEAD")
        self.assertIn("brand-new.txt", r.stderr)

    def test_p2b_deleted_candidate_is_refused(self):
        """A manifest naming a file deleted from the tree must not silently ship less.

        The manifest names the FILE, not its parent directory. Naming the directory would
        be caught earlier and for a different reason: stage 1 expands the directory, the
        deleted file simply is not among the results, and the remaining files export
        cleanly -- so the deletion never becomes a candidate at all. Naming the path
        directly is what puts the deletion in front of the identity check, and stage 1's
        existence check refuses first, which is the correct fail-closed order.
        """
        (self.root / "deliverable" / "readme.md").unlink()
        out = self.tmp / "must-not-exist.zip"
        r = self._run(self._manifest("deliverable/readme.md"), out)
        self.assertNotEqual(r.returncode, 0, "a deleted manifested path was not refused")
        self.assertFalse(out.exists())
        self.assertIn("readme.md", r.stderr)

    def test_p2b_mode_only_drift_is_refused(self):
        """Content identical, mode changed 100644 -> 100755. Byte comparison would MISS this;
        git object identity does not."""
        target = self.root / "deliverable" / "app.txt"
        before = target.read_bytes()
        target.chmod(0o755)
        self.assertEqual(target.read_bytes(), before, "precondition: content unchanged")
        out = self.tmp / "must-not-exist.zip"
        r = self._run(self._manifest("deliverable"), out)
        self._refused_p2(r, out, expect="deliverable/app.txt")

    def test_p2b_symlink_type_drift_is_refused(self):
        """Regular file replaced by a symlink.

        `git hash-object` FOLLOWS the link and hashes the target, while git stores the link
        target string -- which is why the implementation uses diff-index instead. Verified
        empirically before choosing the primitive.
        """
        target = self.root / "deliverable" / "app.txt"
        target.unlink()
        target.symlink_to("readme.md")   # inside the fixture, so the link resolves
        self.assertTrue(target.is_symlink(), "precondition: candidate is now a symlink")
        out = self.tmp / "must-not-exist.zip"
        r = self._run(self._manifest("deliverable/app.txt"), out)
        self._refused_p2(r, out, expect="deliverable/app.txt")
        self.assertIn("DRIFT", r.stderr, "type drift must be reported as drift")

    def test_p2b_unrelated_dirty_unmanifested_file_does_not_refuse(self):
        """P2-b is NOT a clean-working-tree requirement.

        This is the distinction that matters operationally: the real repository intentionally
        carries an unrelated modified file, and the customer manifest does not name it. Only
        EXPORTED candidates must correspond to the stated source-sha; an unmanifested dirty
        file has no bearing on whether the export is honestly labelled.
        """
        stray = self.root / "unlisted" / "notes.txt"
        stray.write_text(f"{SENTINEL} dirty and unmanifested\n")
        self.assertNotEqual(self._git("status", "--short").stdout.strip(), "",
                            "precondition: the tree really is dirty")
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0,
                         f"unmanifested dirty file wrongly blocked the export: {r.stderr}")
        self.assertNotIn("unlisted/notes.txt", zipfile.ZipFile(out).namelist())

    def test_p2b_refusal_precedes_staging(self):
        """Drift refusal happens before any bytes are copied, so no partial archive exists."""
        (self.root / "deliverable" / "app.txt").write_text("drifted\n")
        out = self.tmp / "partial.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(out.exists())
        self.assertFalse(any(self.tmp.glob("*.zip*")), "stray archive artefact left behind")

    def test_p2b_checks_run_under_dry_run(self):
        """--dry-run must exercise P2, or the real-manifest regression proves nothing."""
        (self.root / "deliverable" / "app.txt").write_text("drifted\n")
        r = self._run(self._manifest("deliverable"), None, "--dry-run")
        self.assertNotEqual(r.returncode, 0, "dry run skipped the P2 identity checks")
        self.assertIn("DRIFT", r.stderr)

    # -- P2-c: signed release-tag binding ----------------------------------------------
    # No key exists, so the verifier is injected. `true` stands for "signature verified
    # against the authorized release key"; `false` stands for "it did not".
    def _verify(self, tag: str, source_sha: str, *, verifier: str):
        # Canonical spelling. `tools/verify_release_identity.sh` still honours the legacy
        # SYM_ name, but a test that injects through the legacy branch would go green while
        # the canonical one was broken.
        env = dict(os.environ, SYMONEURAL_TAG_VERIFY_CMD=verifier)
        return subprocess.run(["bash", str(VERIFIER), "--tag", tag,
                               "--source-sha", source_sha, "--root", str(self.root)],
                              capture_output=True, text=True, env=env)

    def test_p2c_verified_tag_matching_source_sha_succeeds(self):
        """Both mandatory conditions hold: signature verifies AND tag commit == source-sha."""
        self._git("tag", "rel-ok")
        head = self._git("rev-parse", "HEAD").stdout.strip()
        r = self._verify("rel-ok", head, verifier="true")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RELEASE IDENTITY VERIFIED", r.stdout)

    def test_p2c_invalid_tag_signature_refuses(self):
        """Condition 1 fails: the tag is not from the release authority."""
        self._git("tag", "rel-badsig")
        head = self._git("rev-parse", "HEAD").stdout.strip()
        r = self._verify("rel-badsig", head, verifier="false")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not verify", r.stderr)
        self.assertNotIn("RELEASE IDENTITY VERIFIED", r.stdout)

    def test_p2c_tag_source_sha_mismatch_refuses(self):
        """Condition 2 fails: an AUTHENTIC signature over a DIFFERENT commit.

        This is a real attack shape -- reuse a genuinely signed tag to bless an archive built
        from another commit -- so the verifier never lets "the tag verified" imply "the tag
        points at this release". The verifier here returns success, and it still refuses.
        """
        self._git("tag", "rel-elsewhere")
        (self.root / "deliverable" / "app.txt").write_text(f"{SENTINEL} second commit\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "second")
        new_head = self._git("rev-parse", "HEAD").stdout.strip()
        r = self._verify("rel-elsewhere", new_head, verifier="true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("!=", r.stderr)
        self.assertNotIn("RELEASE IDENTITY VERIFIED", r.stdout)

    def test_p2c_unresolved_source_sha_is_not_releasable(self):
        """An archive predating P2 could state UNKNOWN. It is not releasable."""
        self._git("tag", "rel-unknown")
        r = self._verify("rel-unknown", "UNKNOWN", verifier="true")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unresolved", r.stderr)

    def test_p2c_both_conditions_are_checked_independently(self):
        """Neither condition alone is sufficient -- proven by failing each in isolation."""
        self._git("tag", "rel-indep")
        head = self._git("rev-parse", "HEAD").stdout.strip()
        # signature fails, SHA matches
        self.assertNotEqual(self._verify("rel-indep", head, verifier="false").returncode, 0)
        # signature passes, SHA does not match
        other = "0" * 40
        self.assertNotEqual(self._verify("rel-indep", other, verifier="true").returncode, 0)
        # both hold
        self.assertEqual(self._verify("rel-indep", head, verifier="true").returncode, 0)

    def test_p2c_exporter_runs_without_any_signing_key(self):
        """P2 must not make exporter refusal depend on signing infrastructure.

        Zero keys exist on this box. The exporter must still construct, refuse, and export.
        If a missing key ever started disabling protections, the dependency would be inverted.
        """
        out = self.tmp / "export.zip"
        r = self._run(self._manifest("deliverable"), out)
        self.assertEqual(r.returncode, 0, f"exporter needs a key it should not: {r.stderr}")
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
