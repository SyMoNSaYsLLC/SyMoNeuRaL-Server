"""The start/reload config mismatch must be detectable, and must not cry wolf.

`tools/serving_config_audit.py` exists because the commissioning report cited
`/etc/caddy/Caddyfile` as the file to edit when the running `symoneural-web` reads
`<root>/ops/Caddyfile`. On this box the two verbs name different files:

    ExecStart  --config /home/google/Symoneural/ops/Caddyfile
    ExecReload --config /etc/caddy/Caddyfile

Those are root-owned facts a test may not change, so the decision logic is tested against
synthetic inputs instead, and the live state is asserted only where it is safe to read.

Two failure modes are guarded here, and the second is the one that actually bit:

  1. The check must FIRE when the two paths differ -- otherwise it is decoration.
  2. It must NOT fire on two byte-identical Caddyfiles that merely live at different paths.
     Caddy's adapted JSON embeds its own config path in `file_server`'s `hide`, so a naive
     comparison reports a difference between identical files. That produced a false
     "ALREADY DIVERGED" reading during the investigation, which is exactly the class of
     confident-wrong answer this suite exists to prevent.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise AssertionError(f"repo root not found above {here}: no backend/api.py marker")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import serving_config_audit as sca  # noqa: E402


class ClassifyVerbMismatch(unittest.TestCase):
    """The decision function, against inputs a test controls completely."""

    @staticmethod
    def _reader(table: dict[str, bytes | None]):
        return lambda p: table.get(p)

    def test_same_path_is_not_a_finding(self):
        r = sca.classify_verb_mismatch("/etc/x", "/etc/x", self._reader({}))
        self.assertIsNone(r, "identical paths must not be reported")

    def test_missing_reload_path_is_not_a_finding(self):
        """A unit with no ExecReload at all cannot have this defect."""
        self.assertIsNone(sca.classify_verb_mismatch("/etc/x", None, self._reader({})))
        self.assertIsNone(sca.classify_verb_mismatch(None, "/etc/x", self._reader({})))

    def test_different_paths_identical_content_is_latent(self):
        """This box's current state: a trap, not yet a fault."""
        r = sca.classify_verb_mismatch(
            "/repo/Caddyfile", "/etc/caddy/Caddyfile",
            self._reader({"/repo/Caddyfile": b"same", "/etc/caddy/Caddyfile": b"same"}))
        self.assertIsNotNone(r, "different paths must be reported even when content matches")
        self.assertEqual(r["severity"], "latent")
        self.assertTrue(r["files_identical_now"])
        self.assertIn("silently reverts", r["what_it_means"])

    def test_different_paths_different_content_is_active(self):
        """The state after somebody edits ops/Caddyfile to fix the 502 -- the real hazard.

        This is the assertion that makes the check worth having: if it did not fire here,
        a reload could revert a fix and nothing would say so.
        """
        r = sca.classify_verb_mismatch(
            "/repo/Caddyfile", "/etc/caddy/Caddyfile",
            self._reader({"/repo/Caddyfile": b"reverse_proxy 127.0.0.1:8800",
                          "/etc/caddy/Caddyfile": b"reverse_proxy 127.0.0.1:8000"}))
        self.assertEqual(r["severity"], "active")
        self.assertFalse(r["files_identical_now"])
        self.assertIn("ALREADY DIFFER", r["what_it_means"])

    def test_unreadable_side_is_active_not_latent(self):
        """Unknown content must not be optimistically treated as agreement.

        If one file cannot be read, whether a reload would change the served config is
        unknown -- and unknown is a reason to look, not a reason to relax.
        """
        r = sca.classify_verb_mismatch(
            "/repo/Caddyfile", "/etc/caddy/Caddyfile",
            self._reader({"/repo/Caddyfile": b"x", "/etc/caddy/Caddyfile": None}))
        self.assertEqual(r["severity"], "active")
        self.assertIsNone(r["files_identical_now"])


class NormaliseCollapsesTheConfigPathSelfReference(unittest.TestCase):
    """Two identical Caddyfiles at different paths must compare equal after normalising.

    Caddy's `file_server` hides the config file it was adapted from, so the adapted JSON
    differs between two byte-identical files purely because of where they sit. Comparing
    raw adaptations reports a difference that does not exist in the served behaviour.
    """

    def test_hide_is_scrubbed(self):
        a = {"apps": {"http": {"handle": [{"hide": ["/repo/Caddyfile"], "root": "/var/www"}]}}}
        b = {"apps": {"http": {"handle": [{"hide": ["/etc/caddy/Caddyfile"], "root": "/var/www"}]}}}
        self.assertNotEqual(a, b, "the fixtures must actually differ, or this proves nothing")
        self.assertEqual(sca._normalise(a), sca._normalise(b))

    def test_normalise_does_not_hide_a_real_difference(self):
        """Scrubbing must be narrow: a genuine upstream change must survive it."""
        a = {"handle": [{"hide": ["/repo/Caddyfile"], "upstreams": [{"dial": "127.0.0.1:8800"}]}]}
        b = {"handle": [{"hide": ["/etc/caddy/Caddyfile"], "upstreams": [{"dial": "127.0.0.1:8000"}]}]}
        self.assertNotEqual(sca._normalise(a), sca._normalise(b),
                            "normalise must not swallow the :8000 vs :8800 difference -- that "
                            "is the whole subject of the 502 finding")

    def test_normalise_passes_none_through(self):
        self.assertIsNone(sca._normalise(None))


class TheToolRunsOnThisBox(unittest.TestCase):
    """End-to-end, read-only. Asserts shape rather than a particular verdict.

    The verdict is expected to change: the whole point of the finding is that somebody
    should reconcile the two paths. A test asserting "one finding, latent" would go red as
    soon as the defect was fixed, which is backwards.
    """

    def test_json_mode_is_parseable_and_exits_zero(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "serving_config_audit.py"), "--json"],
            capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0,
                         f"the audit must not fail a caller's CI for root-owned state; "
                         f"stderr={r.stderr[-400:]}")
        d = json.loads(r.stdout)
        for key in ("unit", "start_config", "reload_config", "findings"):
            self.assertIn(key, d)
        self.assertIsInstance(d["findings"], list)

    def test_it_reads_a_config_path_for_at_least_one_verb(self):
        """If both come back None the tool is not measuring anything.

        Guards against a systemctl output-format change silently turning this into a
        check that always passes -- the failure mode the whole commissioning pass was
        written to catch.
        """
        d = sca.audit()
        self.assertTrue(
            d["start_config"] or d["reload_config"],
            "no --config path parsed from either ExecStart or ExecReload; the `systemctl "
            "show` rendering probably changed and this audit is now blind")


if __name__ == "__main__":
    unittest.main()
