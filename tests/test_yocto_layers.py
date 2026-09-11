"""Static checks on the meta-symoneural-* layer family.

The 12 layers under `yocto/` were authored and committed without `bitbake -p` ever having
been run against them. When it finally was, on 2026-08-19, it exited 1 on a hard ERROR and
then `bitbake -g` exited 1 twice more. These tests encode the three defects that were fixed
by hand so they cannot come back, and they are static on purpose: a test that shells out to
bitbake needs a 963-recipe parse, a writable DL_DIR and about a minute, so it would be
skipped in practice and guard nothing.

What this file does NOT claim: that the layers build, or that any image boots. `virtual/kernel`
is still unresolved by design -- see the comment above PREFERRED_PROVIDER_virtual/kernel in
meta-symoneural-bsp/conf/machine/symoneural-workstation.conf. These tests check the three
things that are true and were not.

POKY is located the same way `yocto/scripts/setup-build.sh:21` locates it, so a box that
moves openembedded-core moves both at once.
"""
from __future__ import annotations

import fnmatch
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YOCTO = ROOT / "yocto"
POKY = Path(os.environ.get("POKY", "/home/google/yocto"))

LAYERS = sorted(p for p in YOCTO.glob("meta-symoneural-*") if p.is_dir())
MACHINE_CONFS = sorted(YOCTO.glob("meta-symoneural-*/conf/machine/*.conf"))
DISTRO_CONFS = sorted(YOCTO.glob("meta-symoneural-*/conf/distro/*.conf"))

# `VAR ?= "value"`, `VAR = "value"`, `VAR ??= "value"` -- the assignment forms these confs use.
ASSIGN = re.compile(r'^\s*([A-Za-z0-9_/${}.:+-]+)\s*\??\?*=\s*"([^"]*)"', re.M)
REQUIRE = re.compile(r'^\s*(?:require|include|include_all)\s+(\S+)', re.M)


def assignments(path: Path) -> list[tuple[str, str]]:
    return ASSIGN.findall(path.read_text())


class LayerInventoryTests(unittest.TestCase):
    """Anti-vacuity. Every other test in this file iterates over one of these lists; if a
    glob silently stops matching, those tests pass by checking nothing. This one fails
    instead, and it is the reason the counts below are written as floors rather than as
    equalities -- a thirteenth layer is a normal event, zero machine confs is not."""

    def test_the_globs_this_file_depends_on_actually_match(self):
        self.assertGreaterEqual(len(LAYERS), 12, f"first-party layers found: {LAYERS}")
        self.assertGreaterEqual(len(MACHINE_CONFS), 2,
                                f"machine confs found: {MACHINE_CONFS}")
        self.assertGreaterEqual(len(DISTRO_CONFS), 1, f"distro confs found: {DISTRO_CONFS}")

    def test_the_assignment_regex_reads_a_known_line(self):
        """If ASSIGN stops matching, every check below reads an empty list and goes green."""
        ws = YOCTO / "meta-symoneural-bsp/conf/machine/symoneural-workstation.conf"
        self.assertIn(("KERNEL_IMAGETYPE", "bzImage"), assignments(ws))


class WksLocationTests(unittest.TestCase):
    """The single hard ERROR that made every parse exit 1:

        wic/wks files at .../meta-symoneural-filesystem/wic need to be moved to files/wic
        within the layer to be found/used

    emitted by oe/sanity.py:694. `WKS_SEARCH_PATH` is built from BBPATH, not from the layer
    root -- image_types_wic.bbclass:49 joins '%s/files/wic' over every BBPATH entry -- so a
    .wks one directory too high is invisible to the layer that ships it.
    """

    def test_every_wks_a_machine_asks_for_is_somewhere_wic_will_look(self):
        asked = [(c, v) for c in MACHINE_CONFS for k, v in assignments(c)
                 if k == "WKS_FILE"]
        self.assertTrue(asked, "no machine conf sets WKS_FILE; this test checked nothing")
        searched = [layer / "files" / "wic" for layer in LAYERS]
        for conf, wks in asked:
            with self.subTest(conf=conf.name, wks=wks):
                hits = [d / wks for d in searched if (d / wks).is_file()]
                self.assertTrue(hits, f"{conf.name} sets WKS_FILE = {wks!r}, and no "
                                      f"first-party layer has files/wic/{wks}")

    def test_no_layer_keeps_a_wks_directory_at_its_root(self):
        """The shape of the original bug, independent of whether a machine names the file.
        A layer with both `wic/` and `files/wic/` parses clean and silently uses neither the
        file you edited nor the one you meant."""
        for layer in LAYERS:
            with self.subTest(layer=layer.name):
                stray = layer / "wic"
                self.assertFalse(stray.is_dir(),
                                 f"{layer.name}/wic/ is where wic does not look; it belongs "
                                 f"at {layer.name}/files/wic/")


class PreferenceTests(unittest.TestCase):
    """`PREFERRED_VERSION_linux-yocto ?= "6.12%"` sat in symoneural-workstation.conf naming a
    version with no recipe anywhere on the box -- linux-yocto_6.18.bb is the only one. It
    produced no parse error because linux-yocto was already being skipped for an unrelated
    reason, so a stale pin behind a live failure is exactly the thing that survives a parse.
    """

    @classmethod
    def setUpClass(cls):
        if not (POKY / "openembedded-core/meta").is_dir():
            raise unittest.SkipTest(
                f"openembedded-core not found at {POKY / 'openembedded-core/meta'} "
                f"(POKY={POKY}); recipe existence cannot be checked from the repo alone")
        cls.recipes: dict[str, set[str]] = {}
        trees = [POKY / "openembedded-core", POKY / "meta-openembedded", YOCTO]
        for tree in trees:
            if not tree.is_dir():
                continue
            for bb in tree.rglob("*.bb"):
                if "/.git/" in str(bb):
                    continue
                pn, _, pv = bb.stem.partition("_")
                cls.recipes.setdefault(pn, set()).add(pv)

    def test_the_recipe_index_is_populated(self):
        self.assertGreater(len(self.recipes), 500,
                           f"only {len(self.recipes)} recipes indexed under {POKY}")
        self.assertIn("linux-yocto", self.recipes)

    def test_every_preferred_provider_names_a_recipe_that_exists(self):
        named = [(c, k, v) for c in MACHINE_CONFS + DISTRO_CONFS for k, v in assignments(c)
                 if k.startswith("PREFERRED_PROVIDER_")]
        self.assertTrue(named, "no PREFERRED_PROVIDER_* found; this test checked nothing")
        for conf, key, value in named:
            with self.subTest(conf=conf.name, key=key):
                self.assertIn(value, self.recipes,
                              f"{conf.name} sets {key} = {value!r} and no {value}*.bb "
                              f"exists under {POKY} or {YOCTO}")

    def test_every_preferred_version_matches_a_recipe_on_disk(self):
        """A `%` in PREFERRED_VERSION is bitbake's wildcard, so the comparison is a glob
        against the versions actually present, not string equality."""
        for conf in MACHINE_CONFS + DISTRO_CONFS:
            for key, value in assignments(conf):
                if not key.startswith("PREFERRED_VERSION_"):
                    continue
                pn = key[len("PREFERRED_VERSION_"):]
                with self.subTest(conf=conf.name, key=key):
                    have = self.recipes.get(pn, set())
                    self.assertTrue(
                        any(fnmatch.fnmatch(pv, value.replace("%", "*")) for pv in have),
                        f"{conf.name} pins {key} = {value!r} but the {pn} recipes on disk "
                        f"are {sorted(have) or 'none'}")


class DuplicateInclusionTests(unittest.TestCase):
    """Three `Duplicate inclusion` WARNINGs fired on every parse because symoneural.conf
    required no-static-libs.inc, security_flags.inc and yocto-uninative.inc, all three of
    which defaultsetup.conf:8,:9,:13 already requires. defaultsetup.conf is not opt-in:
    meta/conf/bitbake.conf:833 includes it unconditionally. Measured with `bitbake -p`:
    6 WARNING messages before the three lines were deleted, 3 after. Three avoidable
    warnings is how the other three stop being read.
    """

    @classmethod
    def setUpClass(cls):
        cls.default = POKY / "openembedded-core/meta/conf/distro/defaultsetup.conf"
        if not cls.default.is_file():
            raise unittest.SkipTest(f"defaultsetup.conf not found at {cls.default} "
                                    f"(POKY={POKY}); nothing to compare against")
        cls.already = {t for t in REQUIRE.findall(cls.default.read_text())
                       if "${" not in t}

    def test_defaultsetup_is_the_file_this_test_thinks_it_is(self):
        self.assertIn("conf/distro/include/no-static-libs.inc", self.already)
        self.assertIn("conf/distro/include/yocto-uninative.inc", self.already)

    def test_no_first_party_distro_conf_requires_what_bitbake_conf_already_pulled_in(self):
        for conf in DISTRO_CONFS:
            for target in REQUIRE.findall(conf.read_text()):
                with self.subTest(conf=conf.name, target=target):
                    self.assertNotIn(target, self.already,
                                     f"{conf.name} requires {target}, which "
                                     f"defaultsetup.conf already requires; this is a "
                                     f"Duplicate inclusion warning on every parse")


if __name__ == "__main__":
    unittest.main()
