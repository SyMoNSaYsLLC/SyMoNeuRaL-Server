"""The Tuner/Guide -> Streamer migration, asserted rather than assumed.

Garrett: *"i said tuner and guide needed to be merged and migrated to streamer"* -- the
migration is the namespace and the visitor-facing surfaces, not just the Python package.
This file guards the two halves of that which a rename sweep gets wrong, and it exists
because **both of them were got wrong here first**, within minutes of each other:

1. **The storage shim inverted itself.** The pages carry the visitor's playlist,
   favourites and credentials in `localStorage`, under keys that were `symoneural.tuner*`.
   A read-old-write-new shim was written into `tools/build/build_pages.py` and then the very
   same pass renamed every `symoneural.tuner` literal in the file -- including the shim's
   own `_OLD`. The result read `_OLD = 'symoneural.streamer'`: syntactically perfect, and
   a no-op that would have silently emptied every visitor's saved playlist. Nothing on the
   page would look broken. `node --check` was happy. That is why the assertion below is on
   the *retired* spelling: it is the one string in the file a rename must NOT touch.

2. **The rack row and the page name have to move together.** `apps/test_status_rack.py`
   infers each row from the module name in the AST, so it stayed green while `status()`
   published `id="tuner"` -- see the note there where `ROW_OF_MODULE` used to be.

Reads generated output, not the generator: what ships is what a visitor gets.
"""
from __future__ import annotations

import pathlib
import re
import unittest

SITE = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "site"
PAGES = ("streamer.html", "streamer-watch.html")

#: The prefix the visitor's data was stored under before the merge. Spelled out rather than
#: derived, because deriving it from anything is how it got overwritten the first time.
RETIRED_PREFIX = "symoneural." + "tuner"
LIVE_PREFIX = "symoneural.streamer"


class StorageMigrationTests(unittest.TestCase):
    def test_both_pages_carry_the_visitor_data_across_the_rename(self):
        for name in PAGES:
            with self.subTest(page=name):
                src = (SITE / name).read_text()
                self.assertIn(f"_OLD = '{RETIRED_PREFIX}'", src,
                              f"{name} does not read the retired key prefix, so a visitor's "
                              "playlist, favourites and credentials are dropped on the floor. "
                              "This is exactly the inert-shim bug in this file's docstring.")
                self.assertIn(f"_NEW = '{LIVE_PREFIX}'", src)

    def test_the_shim_does_not_overwrite_newer_data(self):
        """Idempotent, or a reload rolls the visitor back to what they had before."""
        for name in PAGES:
            with self.subTest(page=name):
                self.assertIn("getItem(_nk) === null", (SITE / name).read_text())

    def test_the_live_pages_store_under_the_new_prefix(self):
        for name in PAGES:
            with self.subTest(page=name):
                src = (SITE / name).read_text()
                # Every key literal except the shim's own _OLD must be the new prefix.
                stale = [ln.strip() for ln in src.splitlines()
                         if RETIRED_PREFIX in ln and "_OLD" not in ln]
                self.assertEqual(stale, [], f"{name} still stores under the retired prefix")


class NamespaceTests(unittest.TestCase):
    def test_no_page_calls_a_retired_api_prefix(self):
        """A page calling /api/tuner/* or /api/guide/* gets a 404: both prefixes moved.

        Deliberately no alias is kept for the API. A stale *bookmark* is permanent and gets
        a redirect; a stale *cached page* resolves itself on the next reload, which is
        Garrett's own test for whether something needs handling at all -- "if it isnt going
        to break our project and its something that will resolve itself naturally DROP IT".

        Both halves of the merge are guarded here, and the guide half is the one that can
        regress silently. `/api/streamer/guide/...` does not contain `/api/guide`, so this
        stays quiet at the correct prefix and fires the moment a page reaches for the flat
        one -- which is exactly what `tests/streamer_guide.mjs` was doing while it looked
        like a port fault. The concatenation is so this file does not match its own source.
        """
        for page in SITE.glob("*.html"):
            body = page.read_text()
            for retired in ("/api/" + "tuner", "/api/" + "guide"):
                with self.subTest(page=page.name, prefix=retired):
                    self.assertNotIn(retired, body,
                                     f"site/{page.name} fetches the retired {retired}; the "
                                     "router that answered it is mounted elsewhere now")

    def test_the_retired_pages_are_gone_not_merely_superseded(self):
        for gone in ("tuner.html", "tuner-watch.html"):
            with self.subTest(page=gone):
                self.assertFalse((SITE / gone).exists(),
                                 f"site/{gone} still exists; two pages for one surface is "
                                 "the duplicate-href defect the merge was ordered to fix")

    def test_the_pages_the_migration_produces_exist(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertTrue((SITE / name).is_file())


class NestedGuidePrefixTests(unittest.TestCase):
    """The guide is mounted UNDER the streamer, and this is the collision that forces it.

    Both routers declare `/state`. Mounted flat -- `/api/streamer` and `/api/guide` folded
    to one shared prefix, which is the obvious reading of "one surface, one name" -- the
    second registration lands on a path the first already answers, and Starlette resolves
    to the first match. The guide's probe would not error. It would return the *streamer's*
    state, so the rack would report the guide ready whenever ffmpeg was present, and a
    visitor would have no way to see it. That is the decorative-indicator failure this repo
    bars, arrived at by routing rather than by CSS.

    Asserted against the routers themselves rather than by importing `api.py`: that module
    builds every rate limiter, resolves the GPU governor and mounts `site/` at import.
    """

    def setUp(self):
        from fastapi import FastAPI

        import streamer

        self.app = FastAPI()
        self.app.include_router(streamer.router, prefix="/api/streamer")
        self.app.include_router(streamer.guide_router, prefix="/api/streamer/guide")
        self.streamer_router, self.guide_router = streamer.router, streamer.guide_router

    def _endpoint(self, path):
        return next((r.endpoint for r in self.app.routes
                     if getattr(r, "path", None) == path), None)

    def test_both_halves_declare_state_which_is_why_nesting_is_load_bearing(self):
        for name, router in (("streamer", self.streamer_router),
                             ("guide", self.guide_router)):
            with self.subTest(half=name):
                self.assertIn("/state", [r.path for r in router.routes])

    def test_each_state_probe_resolves_to_its_own_half(self):
        outer = self._endpoint("/api/streamer/state")
        inner = self._endpoint("/api/streamer/guide/state")
        self.assertIsNotNone(outer, "the streamer's own probe is unreachable")
        self.assertIsNotNone(inner, "the guide's probe is unreachable -- shadowed?")
        self.assertIsNot(outer, inner,
                         "both probes resolve to the SAME endpoint: the guide is shadowed "
                         "and is reporting the streamer's state as its own")

    def test_api_py_mounts_the_guide_nested_under_the_streamer(self):
        api = (next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "api.py").read_text()
        self.assertIn('prefix="/api/streamer/guide"', api)
        self.assertNotIn('prefix="/api/guide"', api,
                         "the guide is mounted flat again; see this class's docstring for "
                         "what that does to its /state probe")


class InvocableDocsTests(unittest.TestCase):
    """Every command `ops/registry/MEASUREMENTS.md` hands an agent has to be runnable.

    The commanded suites lived in `.claude/CLAUDE.md` until 2026-08-22, when R-180 moved the
    whole test-and-ladder section verbatim to `ops/registry/MEASUREMENTS.md`; this class was
    repointed in the same commit, because a moved source with an unrepointed consumer is the
    exact unpropagated-move failure it exists to catch.

    This lives with the migration because the migration is what broke it, and broke it in
    the one way a stale figure cannot be broken. CLAUDE.md told three sessions to run
    `node tests/tuner_failpaths.mjs`, `node tests/tuner_watch.mjs` and (indirectly)
    `tests/tuner_fake_provider.py` after all three had been renamed to `streamer_*`. A
    stale count can be re-measured by whoever doubts it; a command that cannot run just
    fails, and reads as the suite being broken rather than the instruction being wrong.

    Scoped to the fenced ```bash blocks on purpose -- those are the copy-and-paste surface.
    The prose around them deliberately names retired files, both to record which tree a
    figure was read on and, in one place, to say out loud that `node tests/tuner_watch.mjs`
    cannot run any more. Asserting on the whole file would forbid saying that.
    """

    #: `tests/<name>.<ext>` as it appears inside a fenced bash block.
    _PATH = re.compile(r"\b(tests/[\w.-]+\.(?:mjs|py|sh))")

    def _commanded_paths(self, doc):
        text = (next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / doc).read_text()
        # Odd-indexed chunks of a ```-split are the fenced blocks; take the bash ones.
        blocks = [b for i, b in enumerate(text.split("```")) if i % 2 and b.startswith("bash")]
        return sorted({m for b in blocks for m in self._PATH.findall(b)})

    def test_every_test_file_claude_md_tells_you_to_run_exists(self):
        paths = self._commanded_paths("ops/registry/MEASUREMENTS.md")
        self.assertTrue(paths, "no tests/ invocation found at all -- did the fences move?")
        root = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
        for rel in paths:
            with self.subTest(path=rel):
                self.assertTrue((root / rel).is_file(),
                                f"MEASUREMENTS.md tells you to run {rel}, which does not "
                                "exist; a command that cannot run reads as a broken suite")

    #: The two suites this test knowingly does not hold, and why. Both are red for reasons
    #: that belong to task #74's acceptance work, not to the docs: `account.mjs` requests
    #: `http://127.0.0.1:NaN/account.html`, and `stickers.mjs` is 15/16 on a `waitForFunction`
    #: timeout. Naming them here rather than dropping them from the set is the point -- an
    #: exemption with no stated reason is indistinguishable from an oversight, which is how
    #: the next `streamer_guide.mjs` would hide inside this very test.
    KNOWN_RED = {"account.mjs", "stickers.mjs"}

    def _browser_suites(self):
        """The `.mjs` files that actually drive a browser, read off their imports.

        Derived rather than listed, because a hand-kept list is the thing this class exists
        to stop. `code_cli.mjs` is the case that forces it: it is a `tests/*.mjs` file and it
        is not a browser suite at all -- it drives a *process* through `node:child_process`,
        and its own header says why (Playwright drives browsers; the terminal client is the
        desktop half of #78). Excluding it by name would have read as an unexplained
        exemption; excluding it by "does it import the shared chromium resolution" is a fact
        about the file. `browser.mjs` itself is dropped for the same reason it always was:
        it *is* that resolution, and has no assertions of its own.
        """
        suites = set()
        for path in (next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "tests").glob("*.mjs"):
            if path.name == "browser.mjs":
                continue
            if "from './browser.mjs'" in path.read_text():
                suites.add(path.name)
        return suites

    def test_the_browser_suites_are_all_named_there(self):
        """A suite nobody is told to run is a suite that rots unnoticed.

        `streamer_guide.mjs` sat dead for a fortnight -- its generated `app.py` still
        importing `from guide import router` -- and the reason nobody caught it is that
        CLAUDE.md listed four suites and it was the fifth. `project.mjs` then proved the
        same point a second time from a different direction: it was 15/16, and the red was
        `/api/news/ticker` 404ing because its harness mounts only the project router while
        `site/ui.js` fetches the ticker on every page. Nothing about the streamer rename
        broke it and nothing about it was hard to fix; it simply went unrun.
        """
        on_disk = self._browser_suites()
        named = {rel.split("/")[-1]
                 for rel in self._commanded_paths("ops/registry/MEASUREMENTS.md")}
        unnamed = on_disk - named - self.KNOWN_RED
        self.assertEqual(set(), unnamed,
                         f"browser suites exist that MEASUREMENTS.md never tells anyone to "
                         f"run: {sorted(unnamed)}")

if __name__ == "__main__":
    # This block lives at the END of the file, and that is not a style point. It used to sit
    # above `InvocableDocsTests`, where `unittest.main()` ran before the class was defined --
    # so `python3 backend/test_streamer_migration.py` reported **9 tests** and never
    # collected the guard at all. An invocation that succeeds while silently doing less than
    # it says is the same defect `InvocableDocsTests` exists to catch, committed inside the
    # test that catches it.
    #
    # The sys.path insert is what makes running it directly work rather than merely run.
    # `NestedGuidePrefixTests` does `import streamer`, and there is no `__init__.py`
    # or pytest config anywhere under `backend/` -- so what puts `backend/` on the path is the
    # `-m` in CLAUDE.md's `cd backend && python3 -m pytest apps/ -q`: `python3 -m` prepends the
    # cwd. Verified both ways here -- with `-m`, `apps/test_roster.py` is 13 passed; without it,
    # `Interrupted: 1 error during collection`, zero tests run. Invoked as a script instead,
    # Python prepends the script's own directory (`backend/apps`), which is one level too deep,
    # so the import raised `ModuleNotFoundError: No module named 'apps'` in three tests.
    import sys

    sys.path.insert(0, str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())))
    unittest.main()
