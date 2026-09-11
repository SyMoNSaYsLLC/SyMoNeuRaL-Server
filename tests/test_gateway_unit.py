"""The gateway unit's ExecStart has to name the crate that is actually on disk.

This exists because the string in that one line took the **public API** down for four hours
and nothing went red. `712e15b` moved the Rust crate to `backend/gateway/` with every
other app -- Garrett: *"all applications should be in /backend/apps"* -- and
`ops/symoneural-gateway.service` kept pointing at `@@ROOT@@/symon-gateway/target/release/`.
The unit stayed `enabled`, so `systemctl is-active` reported `activating` against a path with
no binary at it, `ops/Caddyfile`'s `/api/*` hop to `127.0.0.1:8000` had nothing to reach, and
every visitor got **502** -- while `api.py` was healthy on :8800 and all thirteen rack units
read correctly on the loopback. The whole suite was green throughout, because every suite in
this repo exercises `api.py` and no check anywhere read this file.

Deliberately NOT asserting that the binary exists. `target/` is gitignored, so on a fresh
clone the honest state is "crate present, not built" and `install-gateway.sh` already refuses
in that case with the command to build it. What is invariant, build or no build, is that the
path names *this repo's crate*: the directory holds a `Cargo.toml` whose package name is the
binary the unit launches. That is the half that went stale, and it is checkable dry.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
UNIT = ROOT / "ops" / "symoneural-gateway.service"
INSTALLER = ROOT / "scripts" / "install-gateway.sh"


def _exec_start():
    for line in UNIT.read_text().splitlines():
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{UNIT} has no ExecStart line at all")


class GatewayUnitPathTests(unittest.TestCase):
    def test_exec_start_is_rooted_on_the_installer_placeholder(self):
        """`install-gateway.sh` substitutes @@ROOT@@; a literal path would install wrong."""
        self.assertTrue(_exec_start().startswith("@@ROOT@@/"), _exec_start())

    def test_exec_start_names_a_crate_that_exists_in_this_repo(self):
        exec_start = _exec_start()
        m = re.fullmatch(r"@@ROOT@@/(.+)/target/release/([\w-]+)", exec_start)
        self.assertIsNotNone(
            m, f"ExecStart is not a cargo release binary path: {exec_start!r}")
        crate_dir, binary = ROOT / m.group(1), m.group(2)
        cargo = crate_dir / "Cargo.toml"
        self.assertTrue(
            cargo.is_file(),
            f"ExecStart launches {exec_start}, but there is no crate at {crate_dir} -- "
            "the unit points somewhere the source is not, which is a 502 on the public "
            "site and a green test suite at the same time")
        name = re.search(r'^name = "([^"]+)"', cargo.read_text(), re.M)
        self.assertIsNotNone(name, f"{cargo} declares no package name")
        self.assertEqual(
            name.group(1), binary,
            f"{cargo} builds {name.group(1)!r} but the unit launches {binary!r}; cargo "
            "writes the package name, so the unit would ENOENT on every start")

    def test_the_installer_and_the_unit_agree_on_the_path(self):
        """One gateway identity across builder, installer, manifest and unit.

        This used to read `^BIN="\\$ROOT/(.+)"$` out of the installer and compare that literal
        with the unit's. It was right about the problem -- two files holding one path is how
        the stale one went unnoticed for four hours -- and it scaled badly: the answer to "two
        copies" is not "a test that checks the two copies match", it is one copy. There are
        now four statements of this identity and none of them is a second path:

            Cargo.toml [[bin]] name        what cargo will produce
            gateway-build.json             what is canonical, and its hash
            ops/symoneural-gateway.service what systemd launches
            the two scripts                DERIVE from the first two, holding no literal

        So this compares the three declarations and then asserts the scripts declare nothing.
        A version of this test that pinned the installer's line SHAPE would have gone red when
        `BIN` became manifest-derived -- a stale-regex failure wearing the costume of a
        stale-path one.
        """
        import json

        unit_rel = _exec_start().removeprefix("@@ROOT@@/")
        manifest = json.loads(
            (ROOT / "ops" / "manifests" / "gateway-build.json").read_text())
        self.assertEqual(
            manifest["relative_path"], unit_rel,
            "ops/manifests/gateway-build.json names one artifact and the unit launches "
            "another. Both files can be individually plausible while the box serves the "
            "binary neither of them describes -- which is the 2026-08-26 state.")

        cargo = (ROOT / "backend" / "apps" / "gateway" / "Cargo.toml").read_text()
        bin_section = re.search(r"^\[\[bin\]\](.*?)(?=^\[|\Z)", cargo, re.M | re.S)
        self.assertIsNotNone(bin_section, "the gateway crate declares no [[bin]] section")
        bin_name = re.search(r'^\s*name = "([^"]+)"', bin_section.group(1), re.M)
        self.assertIsNotNone(bin_name, "the [[bin]] section declares no name")
        self.assertEqual(
            bin_name.group(1), pathlib.PurePosixPath(unit_rel).name,
            "cargo would build one filename and the unit launches another, so the unit "
            "ENOENTs on every start")

    def test_neither_script_holds_its_own_copy_of_the_gateway_path(self):
        """The scripts derive; they do not declare.

        `scripts/install-gateway.sh` reads the binary from `ops/manifests/gateway-build.json`
        and `ops/build-gateway.sh` reads it from `Cargo.toml`, and the direction of each is
        deliberate: the manifest records what IS canonical, Cargo.toml determines what WILL be
        produced, and deriving the builder from the manifest would let a stale record dictate
        a build.

        A literal reappearing in either is not a style complaint. It is the same edit that put
        `symon-gateway` in both of these files and left it there through the rename, so that
        the builder recorded a superseded binary and the installer guarded a file the unit did
        not launch.
        """
        builder = (ROOT / "ops" / "build-gateway.sh").read_text()
        installer = INSTALLER.read_text()
        for label, text in (("ops/build-gateway.sh", builder),
                            ("scripts/install-gateway.sh", installer)):
            code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
            with self.subTest(script=label):
                self.assertNotRegex(
                    code, r"target/release/[A-Za-z]",
                    f"{label} spells out a release-binary path. It should derive one: the "
                    "installer from the manifest, the builder from Cargo.toml.")

    def test_the_superseded_binary_name_is_gone_from_both_scripts(self):
        """`symon-gateway` may survive in prose -- the comments explaining the rename are the
        reason the next reader will not undo it -- but not in anything executed."""
        for path in (ROOT / "ops" / "build-gateway.sh", INSTALLER):
            code = "\n".join(l for l in path.read_text().splitlines()
                             if not l.lstrip().startswith("#"))
            with self.subTest(script=path.name):
                self.assertNotIn(
                    "symon-gateway", code,
                    f"{path.name} still names the superseded binary in code. Both files did, "
                    "for three days after the rename, and neither the build nor the install "
                    "failed -- the old file was still on disk, so every guard passed while "
                    "guarding the wrong artifact.")


INSTALLED = pathlib.Path("/etc/systemd/system/symoneural-gateway.service")


def _exec_start_of(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            return line.split("=", 1)[1].strip()
    return None


def _installed_is_stale(installed_text: str, template_text: str, root: pathlib.Path):
    """None if the installed unit matches the template, else why it does not.

    Split out from the test so the comparison itself is exercised on every machine, not
    only on one with the unit installed -- see the two tests below.
    """
    got = _exec_start_of(installed_text)
    if got is None:
        return "the installed unit has no ExecStart line at all"
    want = (_exec_start_of(template_text) or "").replace("@@ROOT@@", str(root))
    if got != want:
        return (f"the INSTALLED unit launches {got!r} but the repo template says {want!r}; "
                "the running box does not have the fix that is committed here")
    return None


class InstalledGatewayUnitTests(unittest.TestCase):
    """The template being right is not the same as the box being right.

    Everything above reads `ops/symoneural-gateway.service`, which is the file in git. That
    is necessary and it is not sufficient: the unit systemd actually runs is the copy under
    /etc, written by `install-gateway.sh`, and the two drift the moment somebody commits the
    template without re-running the installer. That is not hypothetical either -- it is what
    happened AFTER the four-hour outage in this file's docstring was diagnosed. `88bf9b3`
    corrected the template, every test above went green on it, and nobody ran the installer,
    so /etc kept the pre-`712e15b` path and the unit sat in `activating (auto-restart)` with
    `status=203/EXEC` under `Restart=always`. :8000 was answered the whole time by a gateway
    somebody had started by hand, so every probe of the live site passed. The fix was in the
    repo and the outage was one reboot away, with a green suite either side of it.

    Guarded on the file existing, because a fresh clone or CI has no installed unit and an
    unconditional read there is an environment-dependent failure -- the exact thing this
    file's docstring refuses to do. Green-by-skip where there is nothing installed; red
    precisely on a box where what is deployed no longer matches what is committed.
    """

    def test_the_comparison_catches_a_stale_installed_unit(self):
        """Runs everywhere, including where nothing is installed.

        Without this, the check below is skip-only off this box, and a skipped test looks
        exactly like a passing one in the count at the foot of `.claude/CLAUDE.md`.
        """
        stale = "[Service]\nExecStart=/srv/app/symon-gateway/target/release/symon-gateway\n"
        template = "[Service]\nExecStart=@@ROOT@@/backend/gateway/target/release/symon-gateway\n"
        why = _installed_is_stale(stale, template, pathlib.Path("/srv/app"))
        self.assertIsNotNone(why, "a stale installed ExecStart was reported as matching")
        self.assertIn("symon-gateway/target", why)

        fresh = "[Service]\nExecStart=/srv/app/backend/gateway/target/release/symon-gateway\n"
        self.assertIsNone(_installed_is_stale(fresh, template, pathlib.Path("/srv/app")))

    @unittest.skipUnless(INSTALLED.is_file(), f"no unit installed at {INSTALLED}")
    def test_installed_unit_matches_the_committed_template(self):
        try:
            installed_text = INSTALLED.read_text()
        except PermissionError:  # pragma: no cover -- unit is 644, but do not fail on perms
            self.skipTest(f"{INSTALLED} is not readable by this user")
        why = _installed_is_stale(installed_text, UNIT.read_text(), ROOT)
        self.assertIsNone(
            why, f"{why}\n\nre-install it:  sudo ./scripts/install-gateway.sh")


class GatewayHopTests(unittest.TestCase):
    """The Caddyfile's hop and the unit's bind are the same port, or the site is a 502.

    Written as a pair on purpose: each file is individually plausible, and the failure only
    exists between them. This is the same shape as the ExecStart bug one class up.
    """

    def test_caddy_proxies_api_to_the_port_the_gateway_binds(self):
        caddy = (ROOT / "ops" / "Caddyfile").read_text()
        bind = re.search(r"^Environment=SYMON_GATEWAY_BIND=(\S+)$", UNIT.read_text(), re.M)
        self.assertIsNotNone(bind, "the unit does not set SYMON_GATEWAY_BIND")
        self.assertIn(f"reverse_proxy {bind.group(1)}", caddy,
                      f"Caddy does not proxy to {bind.group(1)}, which is where the gateway "
                      "listens; /api/* would 502 for every visitor")

    def test_the_gateway_forwards_to_the_api_port_api_py_serves(self):
        api_port = re.search(r'SYMONEURAL_PORT", "(\d+)"',
                             (ROOT / "backend" / "server.py").read_text())
        self.assertIsNotNone(api_port, "api.py's default port is no longer readable")
        self.assertIn(f"SYMON_API_UPSTREAM=http://127.0.0.1:{api_port.group(1)}",
                      UNIT.read_text(),
                      "the gateway forwards to a port api.py does not default to")


if __name__ == "__main__":
    # At the END of the file, and with backend/ on the path: see the block at the foot of
    # test_streamer_migration.py for what a misplaced one of these hides.
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    unittest.main()
