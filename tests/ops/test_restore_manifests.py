# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""The restore plan must describe THIS repository, not the one it described last week.

`restore/manifests/` is what a future owner reads after reinstalling Linux, and it is the
only place several facts exist at all: which upstream revision an engine forks from, which
of seven Python environments a component runs in, which database cannot be copied with
`cp`, which unit is deliberately disabled. A manifest that has quietly drifted from the
repository is worse than no manifest, because it will be believed.

So the manifests are generated, and these tests assert the properties a generated artefact
has to keep having:

  * **Coverage.** Every runtime on disk has a registry row. A new engine folder must not be
    silently absent from the restore plan.
  * **Idempotence.** Generating twice produces the same bytes. Three separate generators in
    this repository have re-read their own output and accumulated a copy per run, which is
    why "run it twice and diff" is in the project's completion sequence.
  * **Referential integrity.** Every join resolves. A smoke pointing at an application that
    does not exist is a restore step nobody can run.
  * **Truthfulness against disk.** A recipe that names an output path is checked against the
    filesystem. This repository has recorded an engine as unbuilt because a probe looked in
    `build/bin` when the binary was in `build/kawpowminer` -- true of the path, false of the
    engine, and written three days after the build succeeded.
  * **Anti-vacuity.** A manifest that is empty satisfies every "nothing failed" assertion.
    Minimum row counts are asserted so a truncated generation fails loudly.

The tests do NOT run builds or start services. They check that the plan is internally
coherent and consistent with the disk. Whether the plan WORKS is what
`symoneural-restore smoke` answers, and only a real run can answer it.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest


def _find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())
MANIFESTS = ROOT / "restore" / "manifests"

REQUIRED = {
    "COMPONENTS.tsv": 15,
    "APPLICATIONS.tsv": 12,
    "SOURCE-CLOSURE.tsv": 15,
    "BUILD-RECIPES.tsv": 15,
    "ARTIFACTS.tsv": 10,
    "SERVICES.tsv": 4,
    "DEPENDENCIES.tsv": 100,
    "PERSISTENT-STATE.tsv": 6,
    "RESTORE-ORDER.tsv": 10,
    "SMOKES.tsv": 12,
}


def read(name: str) -> list[dict[str, str]]:
    p = MANIFESTS / name if not name.endswith("CLOSURE.tsv") or "/" in name else None
    p = MANIFESTS / name
    if not p.is_file():
        p = ROOT / name
    lines = p.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]


class ManifestsExist(unittest.TestCase):

    def test_every_required_manifest_is_present_and_not_truncated(self):
        for name, minimum in REQUIRED.items():
            with self.subTest(manifest=name):
                p = MANIFESTS / name
                self.assertTrue(p.is_file(), f"{name} is missing from {MANIFESTS}")
                rows = read(name)
                self.assertGreaterEqual(
                    len(rows), minimum,
                    f"{name} has {len(rows)} rows, expected at least {minimum}. A "
                    f"truncated manifest passes every 'nothing failed' check for the "
                    f"wrong reason.")

    def test_root_level_manifests_exist(self):
        """The reset spec asks for these two at the repository root, not under restore/."""
        for name in ("FIRST-PARTY-CLOSURE.tsv", "THIRD-PARTY-REBUILD-MANIFEST.tsv"):
            with self.subTest(manifest=name):
                self.assertTrue((ROOT / name).is_file(), f"{name} is missing")

    def test_every_row_has_the_full_column_count(self):
        for name in REQUIRED:
            with self.subTest(manifest=name):
                lines = (MANIFESTS / name).read_text().splitlines()
                width = len(lines[0].split("\t"))
                for i, ln in enumerate(lines[1:], start=2):
                    self.assertEqual(
                        len(ln.split("\t")), width,
                        f"{name}:{i} has a different column count from the header; "
                        f"`cut -f` on this file would return the wrong field.")

    def test_no_cell_is_empty(self):
        """An empty cell is ambiguous with a parse error. `-` is the empty value."""
        for name in REQUIRED:
            with self.subTest(manifest=name):
                for i, row in enumerate(read(name), start=2):
                    for k, v in row.items():
                        self.assertNotEqual(
                            v, "", f"{name}:{i} column {k} is empty; use '-'")


class RegistryCoversDisk(unittest.TestCase):

    def test_every_runtime_on_disk_has_a_registry_row(self):
        """A new runtime folder must fail this, not be silently left out of the plan."""
        sys.path.insert(0, str(ROOT / "restore"))
        from lib import registry as R
        known = R.component_ids()
        on_disk = sorted(p.name for p in ROOT.iterdir()
                         if p.is_dir() and p.name.startswith("symoneural-"))
        missing = [n for n in on_disk if n not in known]
        self.assertEqual(
            missing, [],
            f"these runtimes exist on disk and are absent from restore/lib/registry.py: "
            f"{missing}. A runtime missing from the registry is missing from the restore "
            f"plan.")

    def test_the_coverage_check_is_looking_at_something(self):
        """Anti-vacuity: if the glob found nothing the check above passes trivially."""
        on_disk = [p.name for p in ROOT.iterdir()
                   if p.is_dir() and p.name.startswith("symoneural-")]
        self.assertGreaterEqual(
            len(on_disk), 8,
            f"only {len(on_disk)} runtime folders were found; the discovery glob looks "
            f"broken and the coverage test above would pass without checking anything.")


class Idempotent(unittest.TestCase):
    """Generator determinism, kept separate from manifest freshness.

    These were one test and should not have been. A generated manifest records the
    revision it was generated FROM, and committing it produces a new revision -- so the
    committed copy can never name the commit that contains it. That is the same
    impossibility as a file containing its own checksum, which this project already hit
    once when BACKUP.json carried the hash of the ZIP it was inside.

    Conflating the two made a real property (the generator does not accumulate output)
    fail for an unrelated and unavoidable reason (HEAD moved). So determinism is tested by
    generating twice and comparing THOSE two runs, and freshness is tested separately with
    the revision columns excluded.
    """

    @staticmethod
    def _generate() -> dict[str, bytes]:
        r = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build" / "build_restore_manifests.py")],
            cwd=ROOT, capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            raise AssertionError(f"the generator failed:\n{r.stdout}\n{r.stderr}")
        return {name: (MANIFESTS / name).read_bytes() for name in REQUIRED}

    def test_generating_twice_changes_nothing(self):
        """Three generators in this repository have accumulated a copy per run."""
        first = self._generate()
        second = self._generate()
        for name in REQUIRED:
            with self.subTest(manifest=name):
                self.assertEqual(
                    first[name], second[name],
                    f"{name} differs between two consecutive generations. Either a "
                    f"measurement is non-deterministic or the generator is re-reading "
                    f"its own output.")

    def test_committed_manifests_match_the_working_tree_apart_from_the_revision(self):
        """Freshness. Revision columns are excluded for the reason in the class docstring."""
        committed = {}
        for name in REQUIRED:
            r = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:restore/manifests/{name}"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                committed[name] = r.stdout
        self.assertTrue(committed, "no manifests are committed yet")

        self._generate()

        def strip_rev(text: str) -> list[list[str]]:
            lines = text.splitlines()
            header = lines[0].split("\t")
            drop = {i for i, h in enumerate(header)
                    if h in ("SOURCE_REVISION", "PIN_VERIFIED")}
            return [[c for i, c in enumerate(ln.split("\t")) if i not in drop]
                    for ln in lines]

        for name, old_text in committed.items():
            with self.subTest(manifest=name):
                self.assertEqual(
                    strip_rev(old_text),
                    strip_rev((MANIFESTS / name).read_text()),
                    f"{name} in HEAD differs from what the registry generates now "
                    f"(revision columns excluded). Regenerate and commit: "
                    f"python3 tools/build/build_restore_manifests.py")


class ReferentialIntegrity(unittest.TestCase):

    def setUp(self):
        self.comps = read("COMPONENTS.tsv")
        self.apps = read("APPLICATIONS.tsv")
        self.recipes = read("BUILD-RECIPES.tsv")
        self.smokes = read("SMOKES.tsv")
        self.states = read("PERSISTENT-STATE.tsv")
        self.closure = read("SOURCE-CLOSURE.tsv")

    def test_component_ids_are_unique(self):
        ids = [c["COMPONENT_ID"] for c in self.comps]
        self.assertEqual(len(ids), len(set(ids)),
                         "duplicate COMPONENT_ID -- an alias became a second component")

    def test_every_application_names_a_real_component(self):
        cids = {c["COMPONENT_ID"] for c in self.comps}
        for a in self.apps:
            with self.subTest(app=a["APPLICATION_ID"]):
                self.assertIn(a["PRIMARY_RUNTIME_COMPONENT"], cids)

    def test_every_component_has_exactly_one_recipe(self):
        cids = [c["COMPONENT_ID"] for c in self.comps]
        rids = [r["COMPONENT_ID"] for r in self.recipes]
        self.assertEqual(sorted(cids), sorted(rids))

    def test_every_production_application_has_a_real_smoke(self):
        sids = {s["SMOKE_ID"] for s in self.smokes}
        for a in self.apps:
            if a["PRODUCTION_STATUS"] != "PRODUCTION":
                continue
            with self.subTest(app=a["APPLICATION_ID"]):
                self.assertNotEqual(a["RESTORE_SMOKE_ID"], "-")
                self.assertIn(a["RESTORE_SMOKE_ID"], sids)

    def test_no_smoke_is_merely_a_version_check(self):
        """`--version` proves a file exists. A restore smoke must exercise the app.

        #94 shipped a desktop client whose eighteen checks were green and whose chat
        surface was dead on arrival, because every check asked what was on disk.
        """
        for s in self.smokes:
            with self.subTest(smoke=s["SMOKE_ID"]):
                cmd = s["COMMAND"]
                self.assertFalse(
                    cmd.strip().endswith("--version"),
                    f"{s['SMOKE_ID']} is a version check, which cannot fail for a broken "
                    f"application")
                self.assertNotEqual(s["EXPECTED_RESULT"], "-")


class TruthfulAgainstDisk(unittest.TestCase):

    def test_declared_source_roots_exist(self):
        for c in read("COMPONENTS.tsv"):
            with self.subTest(component=c["COMPONENT_ID"]):
                if c["PRODUCTION_STATUS"] in ("PRODUCTION", "INFRASTRUCTURE"):
                    self.assertNotEqual(
                        c["SOURCE_ROOT_PRESENT"], "ABSENT",
                        f"{c['COMPONENT_ID']} is {c['PRODUCTION_STATUS']} and its source "
                        f"root {c['SOURCE_ROOT']} is not on disk")

    def test_production_artifacts_are_where_the_recipe_says(self):
        """The kawpowminer lesson: a probe that looks in the wrong directory reports a
        built engine as unbuilt, and the note outlives the mistake."""
        recipes = {r["COMPONENT_ID"]: r for r in read("BUILD-RECIPES.tsv")}
        for c in read("COMPONENTS.tsv"):
            if c["PRODUCTION_STATUS"] != "PRODUCTION":
                continue
            out = recipes[c["COMPONENT_ID"]]["OUTPUT_ARTIFACT"]
            if out in ("-",):
                continue
            with self.subTest(component=c["COMPONENT_ID"]):
                self.assertTrue(
                    (ROOT / out).exists(),
                    f"{c['COMPONENT_ID']} is PRODUCTION and its declared output {out} is "
                    f"not on disk. Either the recipe names the wrong path or the "
                    f"component is not actually built.")

    def test_upstream_pins_are_full_revisions(self):
        for r in read("THIRD-PARTY-REBUILD-MANIFEST.tsv"):
            with self.subTest(upstream=r["NAME"]):
                self.assertRegex(r["PINNED_REVISION"], r"^[0-9a-f]{40}$")
                self.assertTrue(r["UPSTREAM_PROJECT"].startswith("https://"))

    def test_upstream_pins_still_match_the_checkouts(self):
        """While external/ is still here, the pin is checkable. Once it is gone it is not.

        This is the claim that lets 149 GB be omitted from the backup, so it is verified
        rather than asserted -- and the verification is recorded in the manifest itself.
        """
        rows = read("THIRD-PARTY-REBUILD-MANIFEST.tsv")
        checked = [r for r in rows if r["PIN_VERIFIED"].startswith("PIN_VERIFIED")]
        absent = [r for r in rows if "ABSENT" in r["PIN_VERIFIED"]]
        for r in rows:
            with self.subTest(upstream=r["NAME"]):
                self.assertFalse(
                    r["PIN_VERIFIED"].startswith("PIN_MISMATCH"),
                    f"{r['NAME']}: {r['PIN_VERIFIED']}. The recorded revision is not what "
                    f"is checked out, so a restore would build something else.")
        if not absent:
            self.assertEqual(
                len(checked), len(rows),
                "every upstream tree is present but not every pin verified")

    def test_declared_dependency_locks_exist(self):
        for r in read("BUILD-RECIPES.tsv"):
            lock = r["DEPENDENCY_LOCK"]
            if lock in ("-",):
                continue
            with self.subTest(component=r["COMPONENT_ID"]):
                self.assertTrue(
                    (ROOT / lock).is_file(),
                    f"{r['COMPONENT_ID']} names dependency lock {lock}, which does not "
                    f"exist. A restore recipe pointing at a file nobody wrote is worse "
                    f"than no recipe.")

    def test_every_lock_names_the_interpreter_it_was_read_from(self):
        locks = sorted((ROOT / "restore" / "locks").glob("*.lock.txt"))
        self.assertGreaterEqual(len(locks), 5, "the dependency locks are missing")
        for f in locks:
            with self.subTest(lock=f.name):
                head = f.read_text().splitlines()[:12]
                self.assertTrue(any(ln.startswith("# Interpreter") for ln in head),
                                f"{f.name} does not say which interpreter it describes")
                pins = [ln for ln in f.read_text().splitlines()
                        if ln.strip() and not ln.startswith("#")]
                self.assertGreater(len(pins), 5, f"{f.name} has almost no pins")
                for pin in pins:
                    self.assertIn("==", pin,
                                  f"{f.name} has an unpinned requirement: {pin}")


class ReleaseDocument(unittest.TestCase):

    def test_release_json_is_valid_and_matches_the_manifests(self):
        rel = json.loads((ROOT / "restore" / "RELEASE.json").read_text())
        self.assertEqual(rel["component_count"], len(read("COMPONENTS.tsv")))
        self.assertEqual(rel["application_count"], len(read("APPLICATIONS.tsv")))
        # Three heads, not one -- see the Idempotent class docstring. A tracked document
        # cannot contain the SHA of the commit containing it, so `repository_head` was
        # replaced by fields that say WHICH head each value is.
        self.assertRegex(rel["manifest_generated_from_head"], r"^[0-9a-f]{40}$")
        self.assertRegex(rel["current_measured_head"], r"^[0-9a-f]{40}$")
        self.assertIsNone(rel["final_archive_head"],
                          "final_archive_head must stay null until an archive exists")
        self.assertEqual(rel["restore_entrypoint"], "restore/symoneural-restore")

    def test_release_json_carries_no_secret_values(self):
        """Names, never values. The document travels off this machine."""
        text = (ROOT / "restore" / "RELEASE.json").read_text().lower()
        for marker in ("sk-ant-", "bearer ", "-----begin", "password", "api_key=",
                       "secret="):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, text)


class EntryPoint(unittest.TestCase):

    def test_the_entry_point_is_executable_and_verifies(self):
        exe = ROOT / "restore" / "symoneural-restore"
        self.assertTrue(exe.is_file(), "restore/symoneural-restore is missing")
        self.assertTrue(exe.stat().st_mode & 0o111, "it is not executable")
        r = subprocess.run([str(exe), "verify"], cwd=ROOT, capture_output=True,
                           text=True, timeout=300)
        self.assertEqual(r.returncode, 0,
                         f"symoneural-restore verify failed:\n{r.stdout}\n{r.stderr}")
        self.assertIn("RESTORE_VERIFY=PASS", r.stdout)

    def test_it_refuses_an_unknown_component_rather_than_doing_nothing(self):
        """Silently succeeding on a typo is how a restore appears to work and does not."""
        r = subprocess.run(
            [str(ROOT / "restore" / "symoneural-restore"), "build", "no-such-component"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertNotEqual(r.returncode, 0, "an unknown component id exited 0")
        self.assertIn("unknown component", (r.stdout + r.stderr).lower())

    def test_mutating_subcommands_are_dry_by_default(self):
        """No --apply must mean nothing happened."""
        for args in (["build", "all"], ["test", "all"], ["install", "all"]):
            with self.subTest(cmd=args):
                r = subprocess.run(
                    [str(ROOT / "restore" / "symoneural-restore"), *args],
                    cwd=ROOT, capture_output=True, text=True, timeout=300)
                self.assertIn("--apply", r.stdout,
                              f"{args} did not say it was a dry run")
                self.assertIn("would run", r.stdout)


if __name__ == "__main__":
    unittest.main()
