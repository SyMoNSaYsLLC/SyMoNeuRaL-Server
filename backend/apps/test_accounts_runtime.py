"""`scripts/accounts-runtime.sh` — the account/session domain owner.

Two security domains, two scripts, and this file pins the boundary between them.
`enable-surfaces.sh` owns which surfaces are on and their per-surface tokens;
`accounts-runtime.sh` owns the session signer. That split is not tidiness: the surface
script's `--show` printed every value whose name did not contain TOKEN, and the session
signer -- which lived in the same file -- went out in the clear. Removing the signer from
that script's reach is the structural fix; these tests keep it removed.

Everything here runs WITHOUT root and touches no file under `/etc`. The script's own
privileged paths refuse to run as a normal user by design, so what is tested is the logic
that decides what gets written and what gets printed, against fixtures.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "accounts-runtime.sh"
SURFACES = ROOT / "scripts" / "enable-surfaces.sh"


class ScriptShape(unittest.TestCase):
    def test_it_exists_and_is_executable(self):
        self.assertTrue(SCRIPT.is_file(), f"{SCRIPT} is missing")
        self.assertTrue(SCRIPT.stat().st_mode & 0o111, "not executable")

    def test_it_parses(self):
        r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_privileged_command_refuses_a_non_root_caller(self):
        """The refusal is the boundary. If any subcommand ever runs as an ordinary user it
        can read a 0600 file it should not be able to read, or write one it should not."""
        for cmd in ("status", "validate", "fingerprint", "rotate-session-secret"):
            with self.subTest(cmd=cmd):
                r = subprocess.run([str(SCRIPT), cmd], capture_output=True, text=True, timeout=30)
                self.assertNotEqual(r.returncode, 0, f"{cmd} did not refuse a non-root caller")
                self.assertIn("must run as root", r.stderr)

    def test_the_minimum_length_agrees_with_the_module_that_enforces_it(self):
        """A constant duplicated in two files is a constant that will drift. The script
        cannot import Python, so the number is repeated -- and this reads BOTH and compares,
        which is the only way a repeated constant stays honest."""
        mod = (ROOT / "backend" / "apps" / "accounts" / "__init__.py").read_text()
        m = re.search(r"^MIN_SECRET_CHARS\s*=\s*(\d+)", mod, re.M)
        self.assertIsNotNone(m, "MIN_SECRET_CHARS is gone from apps/accounts")
        s = re.search(r"^MIN_CHARS=(\d+)", SCRIPT.read_text(), re.M)
        self.assertIsNotNone(s, "MIN_CHARS is gone from accounts-runtime.sh")
        self.assertEqual(s.group(1), m.group(1),
                         "accounts-runtime.sh and apps/accounts disagree on the minimum "
                         "secret length; one of them will reject what the other accepts")


class DomainSeparation(unittest.TestCase):
    """Neither automation may edit the other's file. This is the whole point of the split."""

    def test_the_surface_script_never_writes_the_accounts_file(self):
        self.assertNotIn("accounts.env", SURFACES.read_text(),
                         "enable-surfaces.sh references the accounts domain file")

    def test_the_accounts_script_never_writes_the_surfaces_file(self):
        body = SCRIPT.read_text()
        self.assertNotIn("surfaces.env", body,
                         "accounts-runtime.sh references the surfaces domain file")
        self.assertNotIn("api.env", body,
                         "accounts-runtime.sh still references the legacy combined file")

    def test_the_accounts_script_owns_exactly_one_env_file(self):
        files = set(re.findall(r"/etc/symoneural/[A-Za-z0-9_.-]+", SCRIPT.read_text()))
        self.assertEqual(files, {"/etc/symoneural/accounts.env"},
                         f"accounts-runtime.sh touches more than its own domain: {files}")


class NeverPrintsTheSecret(unittest.TestCase):
    """`status` reports shapes, `fingerprint` reports a truncated one-way digest, and
    `rotate` reports both digests. None of the three may report a value."""

    def test_no_command_echoes_a_raw_value(self):
        body = SCRIPT.read_text()
        # A bare `$secret`/`$new`/`$old` inside a printf format or argument list would put the
        # value on stdout. They may appear only inside ${#...} (length) or _fingerprint calls.
        for var in ("secret", "new", "old"):
            for m in re.finditer(rf'printf[^\n]*\$\{{?{var}\}}?\b', body):
                line = m.group(0)
                self.assertTrue("_fingerprint" in line or "${#" in line,
                                f"a printf appears to emit ${var} in the clear: {line}")

    def test_the_secret_is_never_accepted_on_argv(self):
        """`ps` is world-readable on this box. A secret passed as an argument is a secret
        every local user can read for the life of the call -- the same class of mistake as
        printing it, which is the mistake this script exists because of."""
        body = SCRIPT.read_text()
        self.assertIn("openssl rand", body, "the secret is not generated inside the script")
        self.assertNotRegex(body, r"rotate-session-secret\)\s*\n\s*cmd_rotate\s+\"\$2\"",
                            "rotate takes a positional secret")

    def test_fingerprint_is_one_way_and_truncated(self):
        body = SCRIPT.read_text()
        self.assertRegex(body, r"_fingerprint\(\)\s*\{[^}]*sha256sum[^}]*cut -c1-\d+",
                         "the fingerprint is not a truncated sha256")


class RewritePreservesEverythingElse(unittest.TestCase):
    """The rotate path replaces one key in place. Losing an unrelated key here would take a
    surface down at the next restart, and the failure would look like a boot problem rather
    than an edit."""

    AWK = r'''
    /^[[:space:]]*(#|$)/ { print; next }
    $1 == k { print k "=" v; found=1; next }
    { print }
    END { if (!found) print k "=" v }
    '''

    def _rewrite(self, text, new="NEWVALUE"):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "in.env"
            src.write_text(text)
            r = subprocess.run(
                ["awk", "-v", "k=SYMONEURAL_SESSION_SECRET", "-v", f"v={new}", "-F=", self.AWK,
                 str(src)], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_unrelated_keys_and_comments_survive(self):
        out = self._rewrite(
            "# accounts domain\nSYMONEURAL_ACCOUNTS_ENABLED=1\n"
            "SYMONEURAL_SESSION_SECRET=OLDVALUE\nSYMONEURAL_OTHER=keepme\n")
        self.assertIn("# accounts domain", out)
        self.assertIn("SYMONEURAL_ACCOUNTS_ENABLED=1", out)
        self.assertIn("SYMONEURAL_OTHER=keepme", out)
        self.assertIn("SYMONEURAL_SESSION_SECRET=NEWVALUE", out)
        self.assertNotIn("OLDVALUE", out, "the previous secret survived the rewrite")

    def test_line_count_is_stable(self):
        src = "# c\nA=1\nSYMONEURAL_SESSION_SECRET=OLD\nB=2\n"
        self.assertEqual(len(self._rewrite(src).splitlines()), len(src.splitlines()))

    def test_a_missing_key_is_appended_rather_than_silently_dropped(self):
        out = self._rewrite("A=1\nB=2\n")
        self.assertIn("SYMONEURAL_SESSION_SECRET=NEWVALUE", out)
        self.assertIn("A=1", out)

    def test_a_value_containing_an_equals_sign_is_not_truncated(self):
        """`-F=` splits on every `=`, so a base64 secret ending in padding is the case that
        breaks a naive rewrite. Only field 1 is compared and the replacement is printed
        whole, so this holds -- asserted because it is easy to regress."""
        out = self._rewrite("SYMONEURAL_SESSION_SECRET=aGVsbG8=\nC=x=y\n")
        self.assertIn("C=x=y", out, "an unrelated value containing '=' was truncated")


MIGRATE = ROOT / "scripts" / "migrate-api-env.sh"


class MigrationClassifiesEveryKey(unittest.TestCase):
    """`scripts/migrate-api-env.sh` splits the legacy combined env file by security domain.

    The property that matters is FAILS CLOSED: a key with no declared destination must abort
    the migration rather than land in a default domain. Defaulting is exactly how a credential
    ends up in the file a feature-switch script is allowed to rewrite and print, which is the
    failure the split exists to make impossible.
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"(?ms)^domain_of\(\)\s*\{.*?^\}", MIGRATE.read_text())
        assert m, "domain_of() not found -- re-derive this test"
        cls.fn = m.group(0)

    def _domain(self, key):
        r = subprocess.run(["bash", "-c", f"{self.fn}\ndomain_of {key}"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_the_session_signer_goes_to_the_accounts_domain(self):
        """The whole point. If this ever says surfaces, the signer is back inside the reach
        of the script whose --show leaked it."""
        self.assertEqual(self._domain("SYMONEURAL_SESSION_SECRET"), "accounts")

    def test_surface_tokens_stay_in_the_surface_domain(self):
        """Ownership, not sensitivity. These are secrets too, but enable-surfaces.sh is their
        legitimate owner -- splitting on 'is it secret' would move them and break that script."""
        for k in ("SYM_CODER_TOKEN", "SYM_STUDIO_TOKEN", "SYM_PROJECT_TOKEN",
                  "SYMONEURAL_STUDIO_TOKEN", "SYMONEURAL_CODERS_ENABLED"):
            with self.subTest(key=k):
                self.assertEqual(self._domain(k), "surfaces")

    def test_an_undeclared_key_is_UNKNOWN_rather_than_defaulted(self):
        # Both spellings of the fictional key, for two reasons: an undeclared name must be
        # UNKNOWN whichever prefix it carries, and `test_credential_header`'s tripwire refuses
        # any file naming a legacy SYM_* var without its SYMONEURAL_* twin -- which it did to
        # this very line on first run, correctly, because a bare SYM_ name here is
        # indistinguishable from a real one someone forgot to rename.
        for k in ("SYMONEURAL_A_FUTURE_SECRET", "TOTALLY_NEW_KEY",
                  "SYM_SOMETHING_ELSE", "SYMONEURAL_SOMETHING_ELSE"):
            with self.subTest(key=k):
                self.assertEqual(self._domain(k), "UNKNOWN",
                                 "an unclassified key was given a default domain")

    def test_both_spellings_of_the_renamed_surfaces_are_covered(self):
        """apps/symoneuralenv.py's rename is partway through this tree, so the live service
        carries SYM_ names while new code writes SYMONEURAL_. A classifier that knew only one
        half would abort a real migration on the other."""
        for legacy, canonical in (("SYM_CODER_TOKEN", "SYMONEURAL_CODER_TOKEN"),
                                  ("SYM_STUDIO_TOKEN", "SYMONEURAL_STUDIO_TOKEN"),
                                  ("SYM_PROJECT_TOKEN", "SYMONEURAL_PROJECT_TOKEN")):
            with self.subTest(pair=legacy):
                self.assertEqual(self._domain(legacy), self._domain(canonical))
                self.assertNotEqual(self._domain(legacy), "UNKNOWN")

    def test_it_refuses_a_non_root_caller(self):
        for cmd in ("plan", "migrate", "verify", "retire"):
            with self.subTest(cmd=cmd):
                r = subprocess.run([str(MIGRATE), cmd], capture_output=True, text=True, timeout=30)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("must run as root", r.stderr)

    def test_no_subcommand_prints_a_value(self):
        body = MIGRATE.read_text()
        self.assertNotRegex(body, r"printf[^\n]*\$\{?line\}?[^\n]*>&?[12]?\s*$",
                            "a value line appears to be printed to a stream")
        self.assertIn("cut -d= -f1", body, "diff reporting no longer reduces to key names")
