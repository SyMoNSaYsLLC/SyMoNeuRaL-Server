"""`X-Symoneural-Token` -- the operator credential header, and the name it replaced.

This file sits at the top of `apps/` rather than in a package because the thing it covers is
not in one. Seven surfaces read this header, in six files, and until the rename each of them
spelled it as a bare string literal in its own gate. That is the shape of defect this file
exists for: a credential name is agreed between a sender and a reader that never import each
other, so a rename can be applied to one side, pass every existing test, and 401 an operator
whose token is correct.

`api.py` is **read as source, never imported** -- the same discipline as
`apps/test_studio_models.py`, whose `_extract` this borrows. Importing the serving module
builds every rate limiter, resolves the GPU governor and mounts `site/`.

Three things are pinned here and each one has its own failure mode:

1. **The literals.** Every gate test in this repo asserts through `gate.HEADER`, which is the
   right way to write those tests and means none of them can notice the constant being wrong.
   A symbolic test suite plus a misspelled constant is a green run and a dead surface.
2. **The fallback, per reader.** Exercised by presenting the legacy name *alone*. A test that
   sends both names passes with the fallback deleted, which is the same one-sided mistake
   `apps/coder/test_coder.py::test_both_env_prefixes_are_scrubbed_and_nothing_else_is` was
   written to avoid on the env side.
3. **That no reader has only half of it.** The tripwire at the bottom. It is the one assertion
   here that will still be doing work in six months, when the next gated surface is added by
   copying an existing one.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
import unittest

BACKEND = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ROOT = BACKEND.parent
API_PY = BACKEND / "backend" / "server.py"
TREE = ast.parse(API_PY.read_text())

NEW = "X-Symoneural-Token"
LEGACY = "X-Sym-Token"

sys.path.insert(0, str(BACKEND / "apps"))
from studio.plugins.exp import gate as exp_gate                                   # noqa: E402
from studio import gate as studio_gate                             # noqa: E402


def _extract(*names: str) -> dict:
    """Execute just the named top-level definitions from api.py, in an empty namespace.

    Lifted from `apps/test_studio_models.py`, and duplicated rather than imported so that a
    test file is not a dependency of another test file. Only assignments and function
    definitions are taken, so no decorator runs and no import at the top of api.py executes.
    `api.py` has `from __future__ import annotations`, so `request: Request` is a string here
    and `Request` does not need to exist in the namespace.
    """
    wanted = []
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            wanted.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    wanted.append(node)
                    break
    found = {n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             else n.targets[0].id for n in wanted}
    assert not set(names) - found, f"{API_PY} no longer defines {sorted(set(names) - found)}"
    ns: dict = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(API_PY), "exec"), ns)
    return ns


class _Headers(dict):
    """A case-insensitive `get`, which is what Starlette hands a route.

    The reader in `api.py` relies on this and reads one spelling of each name; the two gate
    modules do not, and try both cases, because their tests hand them plain dicts. Modelling
    the real object here is the difference between testing that behaviour and assuming it.
    """

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == key.lower():
                return v
        return default


class _Request:
    def __init__(self, **headers):
        self.headers = _Headers(headers)


class TheLiterals(unittest.TestCase):
    """The wire names, spelled out once, so a typo in a constant is a red test.

    Written as literals deliberately. Asserting `gate.HEADER == gate.HEADER` is what every
    other test in this repo effectively does with this value, and it is why the rename could
    have gone in half-done.
    """

    def test_every_reader_agrees_on_the_new_name(self):
        ns = _extract("OPERATOR_HEADER", "OPERATOR_HEADER_LEGACY")
        self.assertEqual(ns["OPERATOR_HEADER"], NEW)
        self.assertEqual(exp_gate.HEADER, NEW)
        self.assertEqual(studio_gate.HEADER, NEW)

    def test_every_reader_agrees_on_the_legacy_name(self):
        ns = _extract("OPERATOR_HEADER", "OPERATOR_HEADER_LEGACY")
        self.assertEqual(ns["OPERATOR_HEADER_LEGACY"], LEGACY)
        self.assertEqual(exp_gate.HEADER_LEGACY, LEGACY)
        self.assertEqual(studio_gate.HEADER_LEGACY, LEGACY)

    def test_the_two_names_are_not_the_same_string(self):
        """A blanket `sed` over this repo produced exactly this collision once already, in
        `apps/coder/__init__.py`, where `_SECRET_PREFIXES` became two copies of one prefix and
        the fallback was silently gone. Cheap assertion, demonstrated failure mode."""
        self.assertNotEqual(NEW, LEGACY)
        self.assertNotEqual(exp_gate.HEADER, exp_gate.HEADER_LEGACY)
        self.assertNotEqual(studio_gate.HEADER, studio_gate.HEADER_LEGACY)


class TheApiReader(unittest.TestCase):
    """`_operator_token`, the reader in front of the asicminer and cryptominer routes."""

    def setUp(self):
        self.read = _extract("OPERATOR_HEADER", "OPERATOR_HEADER_LEGACY",
                             "_operator_token")["_operator_token"]

    def test_the_new_name_is_read(self):
        self.assertEqual(self.read(_Request(**{NEW: "tok"})), "tok")

    def test_the_legacy_name_alone_still_authorises(self):
        """Alone, not alongside the new one. With both present this passes even with the
        fallback deleted, which is the whole point of naming it this way."""
        self.assertEqual(self.read(_Request(**{LEGACY: "tok"})), "tok")

    def test_the_new_name_wins_when_both_are_present(self):
        """Same precedence rule as `symoneuralenv.promote()`: the new spelling is
        authoritative. One rule for the whole rename rather than one per surface."""
        self.assertEqual(self.read(_Request(**{NEW: "new", LEGACY: "old"})), "new")

    def test_a_case_variant_is_read(self):
        """Starlette normalises header case, so a client sending `x-symoneural-token` is
        indistinguishable from one sending the canonical spelling and must not 401."""
        self.assertEqual(self.read(_Request(**{NEW.lower(): "tok"})), "tok")
        self.assertEqual(self.read(_Request(**{LEGACY.lower(): "tok"})), "tok")

    def test_no_header_is_none_rather_than_empty_string(self):
        """`token_ok` refuses both, but `None` and `""` reach different branches of it and
        only one of them is what "the operator sent nothing" means."""
        self.assertIsNone(self.read(_Request()))

    def test_the_401_names_the_new_header_and_not_the_legacy_one(self):
        """A caller sending the legacy name was accepted, so a 401 mentioning it would
        describe a rejection that did not happen for that reason."""
        src = API_PY.read_text()
        self.assertIn('f"bad or missing {OPERATOR_HEADER}"', src)
        self.assertNotIn(f'"bad or missing {LEGACY}"', src)


class TheGates(unittest.TestCase):
    """`present_token` in both gate packages. Same two-sided shape as above."""

    def test_the_legacy_header_alone_still_authorises_exp(self):
        self.assertEqual(exp_gate.present_token({LEGACY: "tok"}, {}), "tok")

    def test_the_legacy_header_alone_still_authorises_studio(self):
        self.assertEqual(studio_gate.present_token({LEGACY: "tok"}, {}), "tok")

    def test_the_legacy_header_is_read_in_either_case(self):
        """These two take plain dicts as well as Starlette `Headers` -- their own tests hand
        them dicts -- so unlike `api.py` they cannot lean on case normalisation."""
        for g in (exp_gate, studio_gate):
            self.assertEqual(g.present_token({LEGACY.lower(): "tok"}, {}), "tok",
                             g.__name__)

    def test_the_new_header_wins_over_the_legacy_one(self):
        for g in (exp_gate, studio_gate):
            self.assertEqual(g.present_token({NEW: "new", LEGACY: "old"}, {}), "new",
                             g.__name__)

    def test_the_header_still_wins_over_bearer_and_query(self):
        """Widening the header loop must not have reordered it below the other two channels:
        a page that sends both a header and a query token has to get the header's answer."""
        for g in (exp_gate, studio_gate):
            self.assertEqual(
                g.present_token({LEGACY: "from-header", "authorization": "Bearer from-auth"},
                                {"token": "from-query"}), "from-header", g.__name__)

    def test_the_legacy_studio_cookie_still_authorises(self):
        """The sharpest of the fallbacks. This cookie is minted on a request the operator has
        already made, so a tab open at the moment of deploy is holding `sym_studio` -- and the
        framed editor's sub-resource requests, the only thing it exists for, carry no header
        and no query string to fall back on. Reading one name and minting the other is the
        seven-aborted-requests failure `tests/studio.mjs` was written to catch."""
        self.assertEqual(studio_gate.COOKIE, "symoneural_studio")
        self.assertEqual(studio_gate.COOKIE_LEGACY, "sym_studio")
        self.assertEqual(
            studio_gate.present_token({}, {}, {studio_gate.COOKIE_LEGACY: "tok"}), "tok")

    def test_the_new_studio_cookie_wins_over_the_legacy_one(self):
        self.assertEqual(
            studio_gate.present_token({}, {}, {studio_gate.COOKIE: "new",
                                               studio_gate.COOKIE_LEGACY: "old"}), "new")

    def test_only_the_new_cookie_is_ever_minted(self):
        """Read both, set one. Minting the legacy name would give the deprecation no end."""
        src = (BACKEND / "apps" / "studio" / "routes.py").read_text()
        self.assertIn("response.set_cookie(COOKIE,", src)
        self.assertNotIn("set_cookie(COOKIE_LEGACY", src)


# The audited surface, named as explicit roots rather than a walk from the repo root.
#
# Two reasons, and the first is correctness rather than speed. `.claude/worktrees/` holds
# checked-out git worktrees of other branches -- 160 files carrying the pre-rename header --
# and a walk from the root reports every one of them, which is 160 findings about code that is
# not on this branch and cannot be fixed from it. `external/` is Garrett's workshop of
# upstream sources and is out of audit scope by standing instruction. `contrib/` is vendored
# third-party source (llama.cpp among others) that this repo does not author.
#
# The second reason is that a walk past `contrib/` takes tens of seconds, and a slow tripwire
# is one somebody eventually excludes.
AUDITED_ROOTS = ("backend", "tools", "bin", "scripts", "tests", "docs", "deploy", "site",
                 "training", "ops")

SUFFIXES = (".py", ".js", ".mjs", ".html", ".sh", ".md", ".example", ".yaml", ".yml")

# Files inside the audited roots that name the legacy header for a reason other than reading
# it as a credential. Each is a decision with a stated reason, not an exemption granted to
# make this test green.
TRIPWIRE_EXEMPT = {
    # The corpus builder describes the ASIC gate in prose for the project-history Q&A set. It
    # is not a reader and has no fallback that could be missing.
    "training/project-history/build_history_corpus.py",
    # This file names both literals at the top, which is its entire job.
    "backend/test_credential_header.py",
    # A self-contained Windows worker export, dated 2026-01-02, that reads its own
    # environment and is not this codebase's to rename. NOT MINE -- see GARRETT-INBOX.md.
    "backend/cryptominer/SyMon_MinerGPUWorker_PROD_20260102-1818",
}


PRUNED_DIRS = {".venv", "node_modules", "contrib", "__pycache__", ".git", "site-packages",
               # `archive/vendor-sdks` -- the SDKs #103 copied out of external/. Third-party
               # source we did not write and cannot rename, and the docstring below already
               # argues the principle: prune vendored trees, do not exempt their files one
               # at a time.
               #
               # Measured the way that docstring models, rather than asserted: with the ten
               # vendored SDKs present the walk goes from **537 files to 2291**, and 1754 of
               # those -- 77% -- are third-party. The header rule survives reading them
               # today, which is the same luck the `.venv` note records; the next `git pull`
               # of an SDK is a coin toss this test does not need to take.
               "vendor"}

# Names retired rather than renamed, so they have no `SYMONEURAL_` counterpart by design.
# `SYM_FETCH_QWEN36` carried an upstream company name into our environment and was dropped;
# `scripts/fetch-models.sh:71` says so at the line that still honours it as a third fallback.
# Exempting the *name* is tighter than exempting the two files that mention it.
RETIRED_ENV_NAMES = {"SYM_FETCH_QWEN36"}

# Files whose subject matter *is* the legacy spelling. Both are the rename's own machinery:
# one tests the promotion shim, the other tests that the coder scrubber redacts both prefixes.
# A rule that cannot be exempted here would force its own tests to lie.
ENV_TRIPWIRE_EXEMPT = TRIPWIRE_EXEMPT | {
    "backend/test_symoneuralenv.py",
    "backend/coder/test_coder.py",
}

LEGACY_ENV = re.compile(r"\bSYM_([A-Z0-9][A-Z0-9_]*)\b")


def _audited_sources():
    """Walk the audited roots, pruning vendored trees.

    Pruning rather than exempting, which is the lesson `.claude/worktrees/` taught the header
    rule: 160 files nobody here can fix, and a 35s test somebody eventually excludes. Six
    `.venv` trees sit under these roots and hold 32,654 files matching `SUFFIXES`. The header
    rule survived reading them by luck -- `X-Sym-Token` does not appear in redis -- but
    third-party code does contain incidental `SYM_` constants (`SYM_FN` and `SYM_H` in
    pygments' MySQL builtins, `SYM_CRLF`/`SYM_DOLLAR`/`SYM_EMPTY`/`SYM_LF`/`SYM_STAR` in
    redis). Measured by removing both entries: the walk goes from **410 files to 32,925** and
    the env rule below reports **8** offenders, none of them ours to fix.

    `.venv` and `site-packages` are each sufficient alone -- verified by removing one at a
    time, which changed nothing -- because every vendored file here is under both. Both are
    kept because they fail differently: a venv named something other than `.venv` is still
    caught by `site-packages`, and a vendored tree without a venv layout is still caught by
    `.venv` if it has one. Neither is redundant against the *next* directory, only against
    this tree today, so do not delete one on the evidence that it currently changes nothing.

    `.jsonl` is deliberately absent from `SUFFIXES`, and that is the only reason this walker
    never opens `training/corpus.jsonl`. Do not add it. The corpus is the trade secret named
    in CLAUDE.md, and a failure message from either assertion below prints the offending
    file's *path* -- but a future rule that printed matching *lines* would put the corpus into
    pytest output, and pytest output ends up in commit messages and pasted transcripts.
    """
    for root in AUDITED_ROOTS:
        base = ROOT / root
        if not base.is_dir():                           # `bin` is a directory; be tolerant
            if base.is_file():
                yield base.relative_to(ROOT), base
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in PRUNED_DIRS)
            for name in sorted(filenames):
                p = pathlib.Path(dirpath) / name
                if p.suffix not in SUFFIXES or not p.is_file():
                    continue
                rel = p.relative_to(ROOT)
                if any(str(rel).startswith(x) for x in TRIPWIRE_EXEMPT):
                    continue
                yield rel, p


class TheTripwire(unittest.TestCase):
    """No file may read the legacy header name without also reading the new one.

    One-way on purpose. A file naming only the new name is the finished state and needs no
    permission; a file naming only the legacy one is either a reader whose rename was applied
    to the sender and not to it, or a fallback that outlived the migration and was never
    deleted. Both are worth a red test.

    This is the assertion that survives the migration. The next gated surface in this repo
    will be written by copying an existing one, and if the copy is taken from a file that
    still carries the legacy read, this says so.
    """

    _sources = staticmethod(_audited_sources)

    def test_no_source_file_names_only_the_legacy_header(self):
        offenders = []
        for rel, p in self._sources():
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            # Case-insensitively, both sides. HTTP header names are case-insensitive by
            # RFC 9110, and a file that reads them out of a normalised dict spells them
            # lowercase -- `test_symoneural_cli.py` asserts on `x-symoneural-token` and
            # `x-sym-token`, names BOTH, and was still reported as legacy-only. That false
            # positive was invisible for as long as this module could not be imported at all,
            # which is its own lesson: a collection error hides every assertion behind it.
            low = text.lower()
            if LEGACY.lower() in low and NEW.lower() not in low:
                offenders.append(str(rel))
        self.assertEqual(offenders, [],
                         "these name the legacy credential header and not the new one; "
                         "either the rename was applied to only one side, or the file is a "
                         "fallback that should now be deleted")

    def test_the_tripwire_is_actually_reading_files(self):
        """A walker that matched nothing would satisfy the assertion above for the wrong
        reason. Two tripwires in this repo have already turned out to be matching nothing --
        `SYM_([A-Z0-9]+)_ENABLED` against `SYMONEURAL_NEWS_ENABLED` being the most recent --
        so this one states its own floor.
        """
        seen = [str(rel) for rel, p in self._sources()
                if LEGACY in p.read_text(errors="replace")]
        self.assertGreater(len(seen), 8,
                           f"the walker found only {len(seen)} files naming the legacy "
                           f"header; the fallbacks are in more places than that")
        self.assertIn("backend/studio/gate.py", seen)
        self.assertIn("backend/server.py", seen)


class TheEnvNameTripwire(unittest.TestCase):
    """No file may name a legacy `SYM_<NAME>` env var without also naming `SYMONEURAL_<NAME>`.

    The same one-way rule as `TheTripwire`, applied to the other half of the rename. It exists
    because the header rule did not catch the defect it should have: `symoneuralexp/page.js`
    displayed `SYM_EXP_ENABLED=1` and `SYM_EXP_TOKEN` to the operator as the configuration to
    set, long after the reader had been renamed, and `frontend/site/js/exp.js` carried the same four
    strings. 1225 tests passed over it. `symoneuralexp/test_exp.py:1243-1246` pins the two
    constants and byte-compares the generated copy, so both halves were self-consistently
    wrong: the assertions were symbolic, and the strings they never read were the ones an
    operator would actually type.

    Pairing is per name but scoped to the whole file: a file may carry as many legacy names as
    it likes provided each one's new spelling appears *somewhere* in it, which is the shape of
    the three-deep fallback at `scripts/fetch-models.sh:90` and of every dual-send sender.

    **That scoping is a real limit, and mutation testing is how it was found.** Reverting one
    of `symoneuralexp/page.js`'s four display strings to `SYM_EXP_TOKEN` leaves this rule
    green, because the other three still name `SYMONEURAL_EXP_TOKEN` and satisfy the pairing.
    So this catches a name whose rename was never applied anywhere in a file -- the original
    defect, where all four were legacy -- and *not* a single reverted line in a file that is
    otherwise migrated. Per-occurrence pinning has to live with the surface that owns the
    string: `symoneuralexp/test_exp.py::PageTests::
    test_the_page_names_no_legacy_env_var_to_the_operator` asserts `"SYM_EXP_" not in page.js`
    outright, and the generated copy inherits it from the byte-copy assertion beside it. A new
    gated surface wants that assertion too; this rule alone is not enough for it.

    **Scope, so this is not read as more than it is.** `\bSYM_[A-Z0-9_]+\b` matches
    SCREAMING_CASE environment names only. It does *not* cover the lowercase browser-storage
    and cookie keys -- `sym.studio.token`, `sym.exp.token`, `sym_session`, the `sym-acct-`
    tmpdir prefix -- which are deferred deliberately (task #25) because renaming a
    `sessionStorage` key logs every operator out. `symoneuralstudio`'s `sym_studio` cookie is
    the one lowercase name already migrated, and it is covered by its own gate tests, not here.
    """

    def _offenders(self):
        for rel, path in _audited_sources():
            if any(str(rel).startswith(x) for x in ENV_TRIPWIRE_EXEMPT):
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:                             # binary or unreadable; not our business
                continue
            missing = sorted({
                m.group(0) for m in LEGACY_ENV.finditer(text)
                if m.group(0) not in RETIRED_ENV_NAMES
                and f"SYMONEURAL_{m.group(1)}" not in text
            })
            if missing:
                yield str(rel), missing

    def test_no_source_file_names_only_the_legacy_env_var(self):
        offenders = dict(self._offenders())
        self.assertEqual(offenders, {},
                         "these name a legacy SYM_* environment variable without its "
                         "SYMONEURAL_* spelling; either the rename was applied to the reader "
                         "and not to this file, or -- if this is generated -- the generator "
                         "was fixed and `python3 tools/build_<name>.py` was never re-run")

    def test_the_env_tripwire_is_actually_reading_files(self):
        """`TheTripwire`'s floor, restated for this rule, because pruning six `.venv` trees
        out of the walk is exactly the kind of change that can silently empty a walker.

        Two floors, because they fail differently. The file count catches a prune that ate the
        repo; the legacy-name count catches the regex ceasing to match. The second floor is
        **5**, not the twenty a first draft of this test guessed at: only **8** files on this
        tree still name a legacy `SYM_*` env var at all, which is the rename being nearly done
        rather than the walker being broken. (The "771 read sites" in `symoneuralenv.py`'s
        docstring counts reads of the *new* spelling. It is not this number and never was.)
        """
        walked = [rel for rel, _ in _audited_sources()]
        self.assertGreater(len(walked), 250,          # 410 on this tree; margin, not a target
                           f"the walker reached only {len(walked)} files; a prune entry is "
                           f"matching a directory of ours")
        seen = [str(rel) for rel, path in _audited_sources()
                if LEGACY_ENV.search(path.read_text(errors="replace"))]
        self.assertGreater(len(seen), 5,
                           f"the walker found only {len(seen)} files naming any legacy SYM_* "
                           f"env var; there were 8 when this rule was written, and they do "
                           f"not all disappear in one commit")
        self.assertIn("backend/symoneuralenv.py", seen)
        self.assertIn("scripts/fetch-models.sh", seen)

    def test_the_pruned_trees_are_not_being_walked(self):
        """The prune is load-bearing for the rule above, not an optimisation, so it is pinned.
        Eight of the thirteen offenders in the first probe of this rule were vendored, and the
        remaining walk is 410 files against 32,925.
        """
        walked = {str(rel) for rel, _ in _audited_sources()}
        self.assertEqual([w for w in walked if any(f"/{d}/" in f"/{w}" for d in PRUNED_DIRS)],
                         [], "a vendored or generated tree is inside the audit walk")
        self.assertIn("backend/server.py", walked)         # and the prune did not eat the repo


if __name__ == "__main__":
    unittest.main()
