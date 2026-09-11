"""`archive/vendor-sdks/` — the SDKs #103 copied out of `external/`, and the licence that let them.

`external/` is `/references` in `.gitignore`: 295 git repos, 109 GB, none of it version
controlled by us. Garrett asked for the SDKs to live *"in a git location in /backend"*, and
the only thing that decides whether a given tree may make that trip is its licence.

So this file is almost entirely about provenance, and deliberately not about the code. What
is inside `anthropic-sdk-go` is Anthropic's business; what is ours is whether we had a grant
to copy it, whether the grant travelled with the copy, and whether the record of both is
something a person can check without trusting the tool that wrote it.

## Why the manifest is re-derived here rather than read

`tools/lib/index_references.py vendor` writes `archive/vendor-sdks/PROVENANCE.md` and decides what to
copy, so a test that only read that file would be asking the tool to confirm its own homework.
#97's `TheProvenanceBuiltByARealExtractionTests` is the precedent and the warning: every
licence test there called the helper functions directly, so a `license_determined` field
returning a hardcoded `True` *from the builder* was invisible, and one of seven deliberate
breaks stayed green. Tested branch is not shipped branch.

The assertions below therefore read the licence text **out of the vendored copy on disk**, now,
and compare that to what the manifest claims. The two agreeing is the evidence. Either one
alone is a claim.

## The case that decides the whole design

`claude-agent-sdk-typescript` ships a `LICENSE.md`. It reads *"© Anthropic PBC. All rights
reserved. Use is subject to Anthropic's Commercial Terms of Service."* A rule keyed on "does
it have a licence file" would have vendored it, and a rule keyed on the first non-blank line
would have read `Copyright ... Anthropic, PBC` — which is what an MIT file says too, word for
word. Only the operative grant separates them, and `test_the_classifier_reads_the_grant_and_not_the_file`
is that stated as an assertion against synthetic input, so it keeps holding after the real
trees change underneath it.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
VENDOR = ROOT / "archive" / "vendor-sdks"
MANIFEST = VENDOR / "PROVENANCE.md"

sys.path.insert(0, str(ROOT / "tools"))
import index_references as ix  # noqa: E402

#: Named individually rather than derived, because these two ARE the assertion. Both are
#: repos Garrett asked for by name, and both were refused on the licence read. A future run
#: that "helpfully" vendors them must turn this file red rather than quietly succeed.
MUST_NOT_BE_VENDORED = (
    "anthropics/claude-agent-sdk-demos",          # ships no licence file at all
    "anthropics/claude-agent-sdk-typescript",     # ships one, and it reserves every right
)


def _vendored_trees() -> list[pathlib.Path]:
    if not VENDOR.is_dir():
        return []
    return sorted(p for p in VENDOR.glob("*/*") if p.is_dir())


class VendoredSdkTests(unittest.TestCase):

    def test_something_was_actually_vendored(self):
        """The vacuity guard. Every assertion below is satisfied by an empty directory, and
        this repo has already retired checks that scored green on an empty file."""
        trees = _vendored_trees()
        self.assertTrue(trees, "archive/vendor-sdks holds no SDK trees at all")
        self.assertTrue(MANIFEST.is_file(), "archive/vendor-sdks/PROVENANCE.md is missing")
        self.assertGreater(len(MANIFEST.read_text()), 800, "the manifest is a stub")
        names = {f"{p.parent.name}/{p.name}" for p in trees}
        self.assertIn("anthropics/claude-agent-sdk-python", names,
                      "the one SDK Garrett named that carries a grant is not here")

    # ---- the licence, re-read from the copy rather than taken from the manifest --------

    def test_every_vendored_tree_carries_a_grant_we_can_still_read(self):
        """Read off the VENDORED copy, not off `external/` and not off the manifest.

        The copy is the artefact that now lives in this repository, so it is the one whose
        licence has to hold up. If `PRUNE` ever swallowed a LICENSE file on the way in, this
        is what says so — and that is not hypothetical: the copy drops `node_modules`,
        `target`, `dist` and half a dozen other directories, and the list is edited by hand.
        """
        for tree in _vendored_trees():
            with self.subTest(tree=tree.name):
                verdict, lic_file, evidence = ix.licence_grant(tree)
                self.assertIn(verdict, ix.VENDORABLE,
                              f"{tree.name} is in archive/vendor-sdks with licence {verdict!r}; "
                              "only a permissive grant may be copied here")
                self.assertTrue(lic_file, f"{tree.name} has no licence file in the copy")
                self.assertTrue((tree / lic_file).is_file())
                self.assertTrue(evidence, f"{tree.name} matched {verdict} with no evidence")

    def test_the_manifest_agrees_with_the_licences_on_disk(self):
        """The tool's claim and the disk, compared. Either alone is a claim, not evidence."""
        text = MANIFEST.read_text()
        for tree in _vendored_trees():
            rel = f"{tree.parent.name}/{tree.name}"
            verdict, _, _ = ix.licence_grant(tree)
            with self.subTest(tree=rel):
                self.assertIn(f"`{rel}`", text,
                              f"{rel} is vendored and the manifest does not name it")
                row = next((ln for ln in text.splitlines() if f"`{rel}`" in ln), "")
                self.assertIn(verdict, row,
                              f"the manifest records a different licence for {rel} than the "
                              f"copy on disk carries ({verdict})")

    def test_the_refused_repos_are_named_and_absent(self):
        """The two Garrett asked for that could not come, and the record that says why.

        Absent a grant the default is all rights reserved, so 'no LICENSE file' is not a
        permissive default. The manifest naming them IS the deliverable for these two: an
        unlicensed adoption is a decision for him to make knowingly, and this is where it
        would be written down if he ever makes it."""
        text = MANIFEST.read_text()
        for rel in MUST_NOT_BE_VENDORED:
            with self.subTest(rel=rel):
                self.assertFalse((VENDOR / rel).exists(),
                                 f"{rel} was vendored and carries no permissive grant")
                self.assertIn(f"`{rel}`", text,
                              f"{rel} was refused and the manifest does not say so; a "
                              "refusal nobody recorded is indistinguishable from an oversight")

    def test_the_classifier_reads_the_grant_and_not_the_file(self):
        """The discriminating case, against synthetic input so it survives upstream changes.

        `claude-agent-sdk-typescript` really does ship a `LICENSE.md`, and its copyright line
        is the same shape as an MIT file's. Presence of a licence file and its first line are
        both useless as a test; the operative grant is the only thing that separates them."""
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "LICENSE").write_text(
                "Copyright 2023 Anthropic, PBC.\n\n"
                "Permission is hereby granted, free of charge, to any person obtaining a copy")
            self.assertEqual(ix.licence_grant(root)[0], "MIT")

            (root / "LICENSE").write_text(
                "© Anthropic PBC. All rights reserved. Use is subject to Anthropic's "
                "Commercial Terms of Service.")
            self.assertEqual(ix.licence_grant(root)[0], "ALL-RIGHTS-RESERVED",
                             "a reserved-rights licence was not distinguished from a grant")

            (root / "LICENSE").unlink()
            self.assertEqual(ix.licence_grant(root)[0], "NONE",
                             "a project with no licence file must not read as permissive")

    # ---- the mechanics that make a copy a real copy ------------------------------------

    def test_no_vendored_tree_carries_its_own_git_directory(self):
        """A nested `.git` makes git store a mode-160000 gitlink and track none of the
        contents — so the tree would look present in `ls` and be empty in the repository."""
        for tree in _vendored_trees():
            with self.subTest(tree=tree.name):
                self.assertFalse((tree / ".git").exists(),
                                 f"{tree.name} still has its .git; git will store a gitlink")
                self.assertFalse((tree / ".gitmodules").is_file(),
                                 f"{tree.name} declares submodules, which will not populate")

    def test_gitignore_does_not_silently_swallow_vendored_files(self):
        """`.gitignore` carries `*.log`, `*.bak`, `*.key`, `*.safetensors`, `*.gguf`,
        `__pycache__/` and `**/.venv/` with **no path anchor**, so each one matches inside a
        vendored tree as readily as in ours.

        A tree that is 90% tracked reads as complete in `ls` and is not in the repository,
        which is the worst of both: the provenance record says the code is here and git does
        not have it. Asked of git itself rather than reimplemented — a second copy of these
        patterns here would be a second thing to keep in step."""
        trees = _vendored_trees()
        if not trees:
            self.skipTest("nothing vendored")
        # Compiled bytecode is not vendored source and must NOT be committed, so it is excluded
        # from the question rather than from the answer. `__pycache__/` being gitignored inside a
        # vendored tree is the pattern working, not swallowing anything: the `.py` beside it is
        # tracked, and the `.pyc` is regenerable from it by definition.
        #
        # Measured 2026-09-03: this went red listing 58 files, every one a `.pyc` under
        # `__pycache__/`, left behind when a repository-wide pytest run collected the vendored
        # suites. No vendored source was ignored at all. The failure message told the reader to
        # add a `.gitignore` negation for `archive/vendor-sdks`, which would have started committing
        # bytecode -- a real change made to satisfy a test that had misread its own evidence.
        #
        # Same rule as `test_control_plane_matrix.is_app_module_dir`: a transient cache directory
        # must never be able to turn a published invariant red.
        files = [str(p.relative_to(ROOT)) for t in trees for p in t.rglob("*")
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]
        self.assertTrue(files, "vendored trees contain no files")
        out = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT,
                             input="\n".join(files), capture_output=True, text=True,
                             timeout=120)
        ignored = [ln for ln in out.stdout.splitlines() if ln.strip()]
        self.assertEqual(ignored[:20], [], (
            f"{len(ignored)} vendored files are gitignored and would never be committed. "
            "Add a negation to .gitignore for archive/vendor-sdks rather than renaming the files, "
            "which would break the copy against its upstream."))

    def test_the_tree_walkers_that_audit_our_code_do_not_audit_this_one(self):
        """Vendored source must be pruned from the audits, not exempted file by file.

        `apps/test_credential_header.py` says why in its own docstring — the `.venv` prune
        exists because third-party code carries incidental `SYM_` constants nobody here can
        rename, and *"the header rule survived reading them by luck."* Measured when these
        SDKs landed: that walk went 537 → 2291 files, 77% of them third-party, and the
        references-boundary walk went 2926 → 4646. Both prune `vendor` now, and this asserts
        it so a future edit to either set does not quietly re-admit 1700 files."""
        import test_credential_header as tch
        import test_references_boundary as trb
        self.assertIn("vendor", tch.PRUNED_DIRS,
                      "test_credential_header walks archive/vendor-sdks; it will go red on an "
                      "upstream SDK naming a header, which is not ours to rename")
        self.assertIn("vendor", trb.SKIP_PARTS,
                      "test_references_boundary walks archive/vendor-sdks")

    def test_the_manifest_says_that_vendoring_is_not_installing(self):
        """The gap most likely to be discovered the expensive way.

        The intent recorded on #103 is *a dependency we will import*, and copying source does
        not produce a dependency graph: `claude-agent-sdk-python` needs `anyio`, `sniffio`,
        `mcp` and `jsonschema`, none of which are on the system interpreter — and
        `.claude/CLAUDE.md` bars `pip install` there because that is the serving path.

        Asserted rather than left to prose because the manifest is the first thing somebody
        reads before writing `import claude_agent_sdk`, and it is the last cheap moment to
        find out that it will not resolve."""
        text = MANIFEST.read_text().lower()
        self.assertIn("venv", text,
                      "the manifest does not say that importing this needs its own venv")
        for dep in ("anyio", "mcp", "jsonschema"):
            self.assertIn(dep, text,
                          f"the manifest does not name {dep}, which an import would need")


if __name__ == "__main__":
    unittest.main()
