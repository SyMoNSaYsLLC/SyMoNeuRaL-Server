# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Production code must not read source out of `external/`. Enforced, so it stays true.

The owner is wiping this machine and does not want to carry 149 GB of third-party source
through the reset. That is only safe if nothing the product runs depends on those trees
being present -- and the honest situation is more interesting than "nothing does".

## The real dependency, and why it is allowed

`tools/sh/fork_engines.sh` reads `external/referencestochatgpt/{llama.cpp,
stable-diffusion.cpp,whisper.cpp}` and builds the three engines that serve chat, image and
ASR. That is a genuine build-time dependency on `external/`, it is load-bearing, and
pretending otherwise to make a gate go green would be a lie the next restore would discover.

What makes it omittable is that each of those trees is a clean `git clone` of a public
remote at a pinned revision -- measured, and re-checked by `tools/sh/restore-upstream.sh
--check`. So the dependency is on an UPSTREAM, which is reacquirable, not on a local
directory, which is not. `THIRD-PARTY-REBUILD-MANIFEST.tsv` carries the pins and
`restore-upstream.sh` fetches them.

This test therefore draws the line at a different place than a naive `grep external/`
would:

**Counts as a violation:** first-party RUNTIME code -- the API, the apps, the site
generators, the CLIs -- resolving a path under `external/`, `vendor clones`, an old build
snapshot, or a retired workspace. That is a runtime that cannot start without a tree the
backup does not carry.

**Does not count:**

  * `tools/sh/fork_engines.sh` and `tools/sh/restore-upstream.sh`. These are BUILD AUTHORITY and
    ACQUISITION tooling. Their whole job is to consume an upstream; a build script that
    names its input is not a hidden dependency, it is a recipe. Both are covered by the
    manifest, which records the pin that makes the input reacquirable.
  * Prose, docstrings and documentation. A comment explaining why `external/` is
    reference-only is inert. The last blanket path-rewrite in this repository silently
    edited an assertion inside a regex, so prose is left alone deliberately.
  * The manifests themselves, which exist to name these paths.

## The detector must catch split-form path construction

`ROOT / "external" / "referencestochatgpt"` is the same dependency as
`ROOT / "external/referencestochatgpt"` and a substring search for `external/` finds only
the second. This is not hypothetical: nine files including the live `api.py` once spelled
`ROOT / "engines" / "symoneural-llm"` in split form, a string sweep missed every one of
them, and the shims that were assumed dead turned out to be load-bearing. So the pattern
below matches the split form too, and `test_the_detector_catches_split_form_construction`
proves it does.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest


def _find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"no repo root above {start}")


ROOT = _find_root(pathlib.Path(__file__).resolve())

#: Directories that will not exist after the reset. A runtime that resolves a path into one
#: of these cannot start on a restored machine.
RETIRED = (
    "external",
    "referencestochatgpt",
    "SyMoNeuRaL-Workspace",
    "SyMoNeuRaL-Projects",
    "symoneural-cutover-rollback",
)

#: Build authority and acquisition tooling, whose input IS an upstream. Each is covered by
#: THIRD-PARTY-REBUILD-MANIFEST.tsv, which records the pin that makes the input
#: reacquirable. Short on purpose: a long exempt list is how a guard stops guarding.
EXEMPT_PREFIXES = (
    "tools/sh/fork_engines.sh",                 # the build authority for the five forks
    "tools/sh/restore-upstream.sh",             # the acquisition tool for their upstreams
    "tools/sh/fork_render_ui.sh",               # build authority for symoneural-ui; its
                                             # ComfyUI pin is in the rebuild manifest
    "tools/build/build_recovery_root.py",          # its "external/" is an EXCLUSION list -- the
                                             # rule that keeps vendored trees OUT of a
                                             # first-party source bundle. Deleting it
                                             # because the detector fired would put
                                             # somebody else's SDK back in the bundle.
    "tools/data/offload-to-drive.sh",             # its ENTIRE JOB is relocating external/ to
                                             # Google Drive; naming the trees it moves is
                                             # the tool, not a dependency on them
    "restore/lib/models.py",                 # "external/" appears in a path-PREFIX FILTER
                                             # that classifies a reference as
                                             # DOCUMENTATION_ONLY. Removing it would make
                                             # the model requiredness taxonomy wrong.
    "training/project-history/",             # the history CORPUS: recorded question and
                                             # answer text about what was and was not in
                                             # external/. Training data, not a code path.
    "restore/lib/registry.py",               # records where the upstreams live
    "restore/lib/deps.py",                   # verifies the pins against those trees
    "backend/test_no_external_source_dependency.py",
    "docs/",                                 # documentation and historical record
    "THIRD-PARTY-REBUILD-MANIFEST.tsv",
    "FIRST-PARTY-CLOSURE.tsv",
    "restore/manifests/",
)

#: Extensions that are executed. A `.md` naming a path is prose.
CODE_SUFFIXES = (".py", ".sh", ".bash", ".js", ".ts", ".mjs", ".go", ".rs", ".service",
                 ".c", ".cpp", ".h", ".hpp", ".cmake", ".mk", ".yaml", ".yml", ".json")


def _pattern(name: str) -> re.Pattern:
    """A path being RESOLVED, in either spelling.

    Three shapes:
      "external/...."            a quoted path fragment
      / "external" /             pathlib split form -- the one a substring grep misses
      $ROOT/external/            shell interpolation

    A BACKTICK is deliberately not accepted as a quote here. A backtick-wrapped path is
    markdown emphasis in a comment, and accepting it made this detector report 33
    docstrings that explain why external/ is reference-only -- flagging the documentation
    of the rule as a violation of the rule.
    """
    n = re.escape(name)
    return re.compile(
        rf'''(["']{n}/)'''                      # "external/..."
        rf'''|(/\s*["']{n}["']\s*/)'''          # / "external" /
        rf'''|(\$\{{?\w+\}}?/{n}/)'''           # $ROOT/external/
        rf'''|(^\s*{n}/)''',                    # a bare leading path in a config
        re.MULTILINE)


def _mask_inert(rel: str, text: str) -> str:
    """Blank out comments and docstrings, keeping line numbers intact.

    A path inside a comment is not executed, and a path inside a module or function
    docstring is documentation -- both are prose by construction. What is NOT masked is an
    ordinary string literal, because `SRC = "external/ComfyUI"` is a real dependency that
    happens to be spelled as a string, and masking all strings would blind the detector to
    the only shape it most needs to catch.

    Replacement preserves newlines so a reported line number still points at the right line.
    """
    def blank(s: str) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in s)

    if rel.endswith(".py"):
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text
        lines = text.splitlines(keepends=True)
        offs, acc = [], 0
        for ln in lines:
            offs.append(acc)
            acc += len(ln)
        spans = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = node.body[0] if node.body else None
                if isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant) \
                        and isinstance(doc.value.value, str):
                    c = doc.value
                    if c.end_lineno is not None:
                        a = offs[c.lineno - 1] + c.col_offset
                        b = offs[c.end_lineno - 1] + c.end_col_offset
                        spans.append((a, b))
        for a, b in sorted(spans, reverse=True):
            text = text[:a] + blank(text[a:b]) + text[b:]

    out = []
    for ln in text.splitlines(keepends=True):
        s = ln.lstrip()
        if s.startswith("#") or s.startswith("//") or s.startswith("* ") \
                or s.startswith("--"):
            out.append(blank(ln))
        else:
            out.append(ln)
    return "".join(out)


PATTERNS = {name: _pattern(name) for name in RETIRED}


def _tracked_code_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"],
                         capture_output=True, text=True, check=True).stdout
    files = [f for f in out.split("\0") if f]
    return [f for f in files
            if f.endswith(CODE_SUFFIXES)
            and not f.startswith(EXEMPT_PREFIXES)]


def _violations() -> list[tuple[str, str, int, str]]:
    found = []
    for rel in _tracked_code_files():
        p = ROOT / rel
        try:
            text = _mask_inert(rel, p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for name, pat in PATTERNS.items():
            for m in pat.finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                line = text.splitlines()[line_no - 1].strip()
                found.append((rel, name, line_no, line[:160]))
    return found


class ExternalSourceDependency(unittest.TestCase):

    def test_active_external_source_dependencies_is_zero(self):
        """ACTIVE_EXTERNAL_SOURCE_DEPENDENCIES=0 -- the reset gate."""
        v = _violations()
        if v:
            lines = "\n".join(f"  {rel}:{n}  [{name}]  {line}" for rel, name, n, line in v)
            self.fail(
                f"{len(v)} production reference(s) to a tree that will not survive the "
                f"reset:\n{lines}\n\n"
                "Either replace the reference with first-party code or a reinstallable "
                "package dependency, or -- if it is genuinely build authority consuming a "
                "pinned upstream -- add it to EXEMPT_PREFIXES with its reason and record "
                "the pin in THIRD-PARTY-REBUILD-MANIFEST.tsv.")

    def test_the_detector_catches_split_form_construction(self):
        """The bug that got past a string sweep must not get past this.

        `ROOT / "external" / "contrib"` is the same dependency as `ROOT / "external/contrib"`.
        Nine files once spelled an engine path in split form, a substring search found none
        of them, and the shims everyone believed were dead were load-bearing.
        """
        samples = [
            'src = ROOT / "external" / "contrib" / "llama.cpp"',
            "path = root / 'external' / 'referencestochatgpt'",
            'SRC = "external/referencestochatgpt/llama.cpp"',
            'rsync -a "$ROOT/external/contrib/" "$DST/"',
            'WORKSPACE = HOME / "SyMoNeuRaL-Workspace" / "build"',
        ]
        for s in samples:
            with self.subTest(sample=s):
                self.assertTrue(
                    any(p.search(s) for p in PATTERNS.values()),
                    f"the detector did not recognise a real dependency: {s}")

    def test_prose_is_not_treated_as_a_dependency(self):
        """A docstring naming external/ is inert and must not fail the build."""
        samples = [
            "# external/ is a reference-only tree; nothing in it may be linked.",
            "See the external directory for historical context.",
            "the engines were being run straight out of external, which is wrong",
        ]
        for s in samples:
            with self.subTest(sample=s):
                self.assertFalse(
                    any(p.search(s) for p in PATTERNS.values()),
                    f"prose was treated as a dependency: {s}")

    def test_the_detector_actually_scanned_something(self):
        """Anti-vacuity. A scanner that reads nothing reports zero violations forever."""
        files = _tracked_code_files()
        self.assertGreater(
            len(files), 300,
            f"only {len(files)} tracked code files were scanned; the file list looks "
            f"broken, and a PASS above would mean the scan did not run rather than that "
            f"the repository is clean.")

    def test_every_exemption_is_a_real_path(self):
        """An exemption for a path that no longer exists silently widens the guard."""
        for pref in EXEMPT_PREFIXES:
            with self.subTest(exemption=pref):
                p = ROOT / pref
                self.assertTrue(
                    p.exists() or any(f.startswith(pref) for f in
                                      subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                                                     capture_output=True, text=True
                                                     ).stdout.split()),
                    f"EXEMPT_PREFIXES names '{pref}', which is not in the repository. "
                    f"A stale exemption exempts whatever moves into that path next.")

    def test_the_build_authority_dependency_is_recorded_not_hidden(self):
        """fork_engines.sh IS exempt, so its dependency must be recorded elsewhere.

        This is the check that stops the exemption from being a loophole: every upstream
        the build authority consumes has to appear in the rebuild manifest with a pinned
        revision, because the pin is the only reason omitting the tree is safe.
        """
        man = ROOT / "THIRD-PARTY-REBUILD-MANIFEST.tsv"
        self.assertTrue(man.is_file(), "THIRD-PARTY-REBUILD-MANIFEST.tsv is missing")
        rows = man.read_text().splitlines()
        header = rows[0].split("\t")
        rev_col = header.index("PINNED_REVISION")
        name_col = header.index("NAME")
        pins = {r.split("\t")[name_col]: r.split("\t")[rev_col] for r in rows[1:]}

        fork = (ROOT / "tools" / "fork_engines.sh").read_text()
        consumed = {n for n in ("llama.cpp", "stable-diffusion.cpp", "whisper.cpp",
                                "kawpowminer") if n in fork}
        self.assertTrue(consumed, "fork_engines.sh names no upstream -- has it moved?")
        for name in sorted(consumed):
            with self.subTest(upstream=name):
                self.assertIn(name, pins,
                              f"tools/sh/fork_engines.sh builds from '{name}' and it has no "
                              f"row in THIRD-PARTY-REBUILD-MANIFEST.tsv. Without a pin, "
                              f"omitting external/ from the backup makes this engine "
                              f"unrebuildable.")
                self.assertRegex(pins[name], r"^[0-9a-f]{40}$",
                                 f"'{name}' has no full revision pin: {pins[name]!r}")


if __name__ == "__main__":
    unittest.main()
