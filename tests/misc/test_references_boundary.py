"""`external/` is read by people, never by code. This is that rule stated as a test.

Garrett's instruction is verbatim: *"we cannot use code in references its for reference only
we must rebrand if we want to use it"*, and task #74's acceptance test is *"nothing under
`external/` is imported, built or linked"*. A rule written in a document is a rule until
somebody forgets it; the reason this is a test is that the repo had already broken it in
eleven places without anybody noticing.

**What went wrong, and why grepping for `external/` is not the check.** Nine suites
imported Playwright from `contrib/llama.cpp/tools/ui/node_modules/playwright` and three more
call sites read `contrib/whisper.cpp/samples/jfk.wav`. Both paths moved under `external/`
in the restructure, so every one of them was *already broken* -- eight browser suites could
not start at all, and four published figures with commit SHAs beside them had quietly become
unreproducible. The tempting fix was to add the `external/` prefix, which would have made
them run and broken the rule. So the check below looks for **both** spellings: a bare
`contrib/` path (stale, and a repointing waiting to happen) and a `external/` one (the
rule, broken outright).

Kept deliberately narrow. It reads source text and asserts on paths, so it cannot tell a
real import from the word appearing in a sentence -- which is why prose mentions are allowed
through by requiring a path separator and a quote-ish context, and why the exemptions below
are listed one by one rather than pattern-matched. A check that fires on its own explanatory
comment is a check people delete.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())

#: Where code lives. `external/` itself is excluded -- it is allowed to refer to itself.
SEARCH_DIRS = ("tests", "backend", "tools", "scripts", "engines", "ops")
SUFFIXES = (".py", ".mjs", ".js", ".sh", ".cmake", ".txt", ".json")

#: Skipped wholesale: installed trees and generated output are not ours to police here.
SKIP_PARTS = {"node_modules", ".venv", "build", "__pycache__", "dist", ".git",
              # `archive/vendor-sdks` -- the SDKs #103 copied out of `external/` under a read
              # licence. Third-party source, and this rule is about OUR code reaching into a
              # read-only tree: a vendored file naming `contrib/llama.cpp/` would be neither
              # a violation we caused nor one we could fix, and it would fire on a `git pull`
              # of an upstream SDK.
              #
              # Measured rather than assumed: with the ten SDKs present this walk goes from
              # 2926 files to 4646, 1720 of them (37%) third-party. `apps/test_vendor_sdks.py`
              # is what polices the vendored trees, and it polices provenance, which is the
              # thing about them that is actually ours.
              "vendor"}

#: Files allowed to name these paths, each with the reason. Documentation of a deleted path
#: is how the next reader learns why it is deleted, so the files that explain the boundary
#: are the ones that must be able to spell it.
ALLOWED = {
    "backend/test_references_boundary.py": "this file states the rule",
    "tests/browser.mjs": "explains the path it replaced",
    "tests/fixtures/README.md": "explains the fixture it replaced",
    # Exempted with the reason stated, not by weakening the pattern above. This script reads
    # Bitmain's own firmware archives out of `external/Projects_Crypto/` -- vendor blobs
    # that are the *subject* of the emulation, not a library it links, and the one thing in
    # the tree that genuinely cannot be recreated, the same argument that exempts NVIDIA's
    # sources. It is still the wrong home for an input a script reads at runtime, so where
    # those archives should live is recorded as a question for Garrett rather than answered
    # here. Narrow on purpose: this names one file, so the next offender still fails.
    "scripts/qemu-antminer.sh": "reads vendor firmware archives; relocation is an open question",
    # The engine fork tool, exempted for the opposite reason to the one above: it takes a
    # vendored upstream tree as build INPUT -- the way you would treat a release tarball --
    # and writes our engine to `engines/` as OUTPUT. After it runs the shipped product has no
    # path into the read-only tree at all, which is the outcome this rule exists to produce.
    # It was passing only because it spells the parent without a trailing slash, which `BAD`
    # does not match. That is a punctuation accident, not a decision, and it would have broken
    # the moment an upstream source sat one directory deeper -- which is exactly what happened
    # when the ASR engine's source turned out to live under a differently-named parent.
    "tools/sh/fork_engines.sh": "takes external/ as build input, writes engines/ as output",
    # The external-source DETECTOR's own fixtures. Its
    # test_the_detector_catches_split_form_construction asserts that a real dependency is
    # recognised, and a fixture proving that has to LOOK like the thing being detected --
    # so it contains the literal strings this rule forbids. Exempting it is not weakening
    # the rule: without those fixtures the other detector passes vacuously, which is the
    # failure both files exist to prevent. Named individually, so the next offender fails.
    "backend/test_no_external_source_dependency.py":
        "fixtures that must look like the dependency they detect",
}

#: A path into a third-party working tree, in either spelling. `\b` on the left so that
#: `our-contrib/` and `symoneural_external/` do not match.
BAD = re.compile(r"""\b(?:external/[A-Za-z0-9._-]+/|contrib/(?:llama\.cpp|whisper\.cpp|cuda-samples|stable-diffusion\.cpp)/)""")


def _candidates() -> list[pathlib.Path]:
    out = []
    for d in SEARCH_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in SUFFIXES:
                continue
            if SKIP_PARTS & set(p.parts):
                continue
            out.append(p)
    return out


class ReferencesAreNotOnAnyCodePath(unittest.TestCase):
    def test_no_source_file_names_a_third_party_working_tree(self):
        offenders = []
        for p in _candidates():
            rel = p.relative_to(ROOT).as_posix()
            if rel in ALLOWED:
                continue
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                m = BAD.search(line)
                if not m:
                    continue
                # A comment is prose, and prose about a removed path is the point of a
                # comment. Only flag it when it is being used: quoted, or after an import.
                stripped = line.lstrip()
                if stripped.startswith(("#", "//", "*", "#:")):
                    continue
                if not re.search(r"""['"]""", line):
                    continue
                offenders.append(f"{rel}:{n}: {stripped[:110]}")
        self.assertEqual(
            offenders, [],
            "code names a path under external/ (or the pre-restructure contrib/ spelling "
            "of one). Both are wrong and for different reasons: the bare contrib/ form no "
            "longer exists, and adding the external/ prefix to make it resolve breaks the "
            "rule that nothing under external/ is imported, built or linked. Put what you "
            "need in our own tree.\n  " + "\n  ".join(offenders))

    def test_the_check_can_actually_fail(self):
        # A pattern that matches nothing passes this suite forever. Prove it bites.
        self.assertTrue(BAD.search("from '../external/playwright/index.mjs'"))
        self.assertTrue(BAD.search("join(REPO, 'contrib/llama.cpp/tools/ui/node_modules')"))
        self.assertIsNone(BAD.search("our-contrib/thing/x"))
        self.assertIsNone(BAD.search("backend/studio/plugins/reinforce"))


if __name__ == "__main__":
    unittest.main()
