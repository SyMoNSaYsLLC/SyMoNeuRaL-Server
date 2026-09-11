"""`runtimeconfig` decides what may change this process's environment. Test it like that.

Almost every assertion here is a REFUSAL. The module's job is to let a user-owned file
configure the box without letting that file become a way to set `LD_PRELOAD` on the serving
interpreter or to quietly override what systemd passed. So the interesting cases are the ones
where it declines, and a suite that only proved it can read a file would be testing the easy
half.
"""

from __future__ import annotations

import os
import pathlib
import stat
import sys
import tempfile
import unittest


from runtime import runtimeconfig  # noqa: E402


class _Sandbox(unittest.TestCase):
    """A config dir of our own, and an environment we can dirty without consequence."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="symoneural-runtimeconfig-")
        self.dir = pathlib.Path(self._tmp.name)
        self._saved = dict(os.environ)
        os.environ[runtimeconfig.CONFIG_DIR_ENV] = str(self.dir)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved)
        self._tmp.cleanup()

    def write(self, name: str, text: str, mode: int = 0o600) -> pathlib.Path:
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        p.chmod(mode)
        return p


class Parsing(_Sandbox):
    def test_the_four_shapes_a_hand_edited_file_has(self):
        got = runtimeconfig.parse(
            "# a comment\n"
            "\n"
            "SYMONEURAL_A=1\n"
            "export SYMONEURAL_B=2\n"
            '  SYMONEURAL_C = "3"  \n'
            "SYMONEURAL_D='4'\n"
            "a line with no equals sign\n")
        self.assertEqual(got, {"SYMONEURAL_A": "1", "SYMONEURAL_B": "2",
                               "SYMONEURAL_C": "3", "SYMONEURAL_D": "4"})

    def test_an_empty_value_is_kept_rather_than_dropped(self):
        """"Present but empty" is how a template ships an unconfigured install.

        Every gate on this box tests the value for truth, not the name for presence, so an
        empty value must survive parsing and read as off. Dropping the name would make an
        unconfigured install indistinguishable from a misspelled one.
        """
        self.assertEqual(runtimeconfig.parse("SYMONEURAL_X=\n"), {"SYMONEURAL_X": ""})

    def test_a_malformed_line_does_not_take_the_whole_file_down(self):
        got = runtimeconfig.parse("garbage\nSYMONEURAL_OK=yes\n=novalue\n")
        self.assertEqual(got.get("SYMONEURAL_OK"), "yes")


class WhatItRefuses(_Sandbox):
    def test_a_name_outside_the_allowed_prefixes_is_refused(self):
        """The whole reason this is an allow-list. A config file is an instruction to change
        this process's environment, and `LD_PRELOAD` in one must not reach the interpreter."""
        self.write("a.env", "LD_PRELOAD=/tmp/evil.so\nPATH=/tmp\nSYMONEURAL_OK=1\n")
        loaded = runtimeconfig.load(warn=False)
        self.assertEqual(loaded, ["SYMONEURAL_OK"])
        self.assertNotIn("LD_PRELOAD", os.environ)
        self.assertEqual(os.environ.get("PATH"), self._saved.get("PATH"))

    def test_a_refused_name_is_reported_and_not_silently_dropped(self):
        self.write("a.env", "LD_PRELOAD=/tmp/evil.so\n")
        runtimeconfig.load(warn=False)
        self.assertTrue(any("LD_PRELOAD" in r for r in runtimeconfig.rejected()),
                        "a refusal nobody can see is indistinguishable from a bug")

    def test_a_world_readable_file_is_not_read_at_all(self):
        """These files hold a session-signing secret. Moving them somewhere convenient must
        not also move them somewhere every local user can read."""
        self.write("a.env", "SYMONEURAL_SECRETISH=value\n", mode=0o644)
        loaded = runtimeconfig.load(warn=False)
        self.assertEqual(loaded, [])
        self.assertNotIn("SYMONEURAL_SECRETISH", os.environ)
        self.assertTrue(runtimeconfig.rejected(), "the refusal must be reported")

    def test_a_group_readable_file_is_also_refused(self):
        self.write("a.env", "SYMONEURAL_SECRETISH=value\n", mode=0o640)
        self.assertEqual(runtimeconfig.load(warn=False), [])

    def test_it_never_overrides_what_the_process_was_started_with(self):
        """systemd's EnvironmentFile, or an operator's export, outranks a file on disk.

        This direction is the safety property: the module can configure a box that had no
        configuration, and can never quietly change one that already worked.
        """
        os.environ["SYMONEURAL_ALREADY"] = "from-the-environment"
        self.write("a.env", "SYMONEURAL_ALREADY=from-the-file\n")
        runtimeconfig.load(warn=False)
        self.assertEqual(os.environ["SYMONEURAL_ALREADY"], "from-the-environment")


class WhatItAccepts(_Sandbox):
    def test_both_prefixes_load_and_the_legacy_one_is_still_promotable(self):
        """A legacy name from a FILE must end up indistinguishable from one from the environment.

        This is why `api.py` calls `runtimeconfig.load()` before `symoneuralenv.promote()`. If
        the loader ran after, a file-supplied `SYM_LEGACY` would never become
        `SYMONEURAL_LEGACY` and the file would be a second-class source with subtly different
        behaviour -- the kind of difference that is invisible until a surface reads the
        canonical spelling and finds nothing.
        """
        self.write("a.env", "SYM_LEGACY=1\nSYMONEURAL_CURRENT=2\n")
        loaded = runtimeconfig.load(warn=False)
        self.assertEqual(sorted(loaded), ["SYMONEURAL_CURRENT", "SYM_LEGACY"])

        from runtime import symoneuralenv  # noqa: PLC0415 -- only this test needs it
        symoneuralenv.promote(warn=False)
        self.assertEqual(os.environ.get("SYMONEURAL_LEGACY"), "1",
                         "a legacy name that arrived from a config file must promote exactly "
                         "like one that arrived from the environment")

    def test_files_are_read_in_a_stable_order(self):
        """Two files setting one key must resolve the same way on every boot. Directory order
        is not sorted order, and a config that depends on inode layout is a config that changes
        under you after a copy."""
        self.write("b-second.env", "SYMONEURAL_DUP=second\n")
        self.write("a-first.env", "SYMONEURAL_DUP=first\n")
        runtimeconfig.load(warn=False)
        self.assertEqual(os.environ["SYMONEURAL_DUP"], "first",
                         "the alphabetically first file must win, every time")

    def test_a_missing_directory_is_not_an_error(self):
        os.environ[runtimeconfig.CONFIG_DIR_ENV] = str(self.dir / "does-not-exist")
        self.assertEqual(runtimeconfig.load(warn=False), [])
        self.assertEqual(runtimeconfig.candidates(), [])

    def test_only_dot_env_files_are_read(self):
        self.write("notes.txt", "SYMONEURAL_NOPE=1\n")
        self.write("real.env", "SYMONEURAL_YES=1\n")
        self.assertEqual(runtimeconfig.load(warn=False), ["SYMONEURAL_YES"])


class TheCheckCanFail(_Sandbox):
    def test_sabotage_the_prefix_filter_and_the_refusal_test_goes_red(self):
        """A guard that cannot be observed failing is not evidence of anything.

        Break the allow-list on purpose and confirm the thing it protects actually stops being
        protected -- otherwise `test_a_name_outside_the_allowed_prefixes_is_refused` could be
        passing because `load()` does nothing at all.
        """
        self.write("a.env", "LD_PRELOAD=/tmp/evil.so\n")
        saved = runtimeconfig._ALLOWED_PREFIXES
        try:
            runtimeconfig._ALLOWED_PREFIXES = ("LD_",)
            runtimeconfig.load(warn=False)
            self.assertIn("LD_PRELOAD", os.environ,
                          "with the filter widened this MUST get through; if it does not, the "
                          "refusal test above proves nothing")
        finally:
            runtimeconfig._ALLOWED_PREFIXES = saved
            os.environ.pop("LD_PRELOAD", None)


class TheRepositoryLocation(unittest.TestCase):
    def test_the_default_config_dir_is_inside_the_repo_and_gitignored(self):
        """`run/` is gitignored in full, which is what makes this location safe for secrets.

        Not a convention anyone has to remember -- enforced by the same `.gitignore` that
        already covers `run/coder.log` and the surface databases. If someone un-ignores `run/`,
        this goes red before a secret can be committed.
        """
        root = runtimeconfig.ROOT
        self.assertTrue((root / "backend" / "server.py").is_file(),
                        f"repo root wrongly derived as {root}")
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertRegex(ignore, r"(?m)^/?run/?$",
                         "run/ must stay gitignored: it is where the session-signing secret "
                         "now lives, and the only thing stopping it being committed")


if __name__ == "__main__":
    unittest.main()
