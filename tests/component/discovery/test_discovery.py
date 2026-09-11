"""Symon Say Discovery — the tests that keep its four load-bearing decisions honest.

Stdlib only, and collected by the ordinary `python3 -m pytest apps/ -q` run. That is not a
style preference: `apps/studio/plugins/reinforce/tests` and `apps/remix/tests` are both excluded by `--ignore`
because they import a package the system interpreter does not have, and an import error in a
pytest root does not fail one test, it aborts *collection* — `Interrupted: 2 errors`, zero
tests run, which reads exactly like the suite was broken by whatever landed last. This app
declines to become the third exclusion, and `test_no_third_party_import_at_module_level` is
what enforces that rather than trusting it.

The four decisions under test, each of which was made against a plausible alternative:

1. Every third-party import in `discovery.py` is lazy (above).
2. The credentials file is gitignored *and* its tracked template has no values in it.
3. `status()` returns a `state` that `api.py`'s `Unit` model will actually accept.
4. The shell wins over the env file, so a deployed secret is never clobbered by a checkout.
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
REPO = HERE.parents[4]
PKG = HERE

sys.path.insert(0, str(HERE.parents[3]))

from studio.plugins.discovery import discovery as app
from studio.plugins.discovery import discovery, envfile  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(("git", "-C", str(REPO)) + args, capture_output=True,
                          text=True, check=False).stdout


class ImportShapeTests(unittest.TestCase):
    """The one test that protects the whole suite's ability to run."""

    def test_no_third_party_import_at_module_level(self):
        """`discovery.py` must import nothing at module level that this box might not have.

        Checked against `sys.stdlib_module_names` rather than a hand-kept allow-list, so it
        stays true as the stdlib moves. Imports inside a function body are fine and are the
        whole design — only module-level ones are walked here.

        This fails the moment somebody moves `import requests` to the top of the file for
        tidiness, which is exactly the edit that would turn a pass count into `Interrupted`.
        """
        tree = ast.parse((PKG / "discovery.py").read_text())
        offenders = []
        for node in tree.body:  # module level only, deliberately not ast.walk
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root and root not in sys.stdlib_module_names:
                    offenders.append(f"line {node.lineno}: {name}")
        self.assertEqual([], offenders,
                         "module-level third-party imports abort pytest collection")

    def test_importing_the_package_needs_no_optional_dependency(self):
        """A subprocess import with the optional packages made unimportable.

        The in-process `import` above proves nothing on a box that happens to have them; this
        blocks `playwright` and `anthropic` in `sys.modules` first, so the assertion holds on
        Garrett's box after he installs them as well as on this one now.
        """
        code = (
            "import sys\n"
            "for name in ('playwright', 'anthropic', 'requests', 'bs4', 'lxml'):\n"
            "    sys.modules[name] = None\n"
            f"sys.path.insert(0, {str(HERE.parents[3])!r})\n"
            "from studio.plugins import discovery as d\n"
            "print(d.status()['state'])\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual("offline", proc.stdout.strip())


class CredentialContainmentTests(unittest.TestCase):
    """The rules that stop this app repeating `backend/remix/.env`.

    That file is tracked with live secret-shaped values and rides inside any archive carrying
    `.git`; the exposure has already happened and rotating it is Garrett's. The only reason it
    happened is that nothing excluded it before the first `git add -A`, so these two tests
    exist as of the commit that created the app rather than after an incident.
    """

    CREDENTIAL_SHAPED = re.compile(r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|_KEY|_CX)$")

    def test_the_real_env_file_is_ignored(self):
        """`git check-ignore`, not a substring search of `.gitignore`.

        A pattern can be present and still not match — `**/.venv/` looks like it would cover
        `symoneural-discovery.venv` and does not. Asking git is the only check that cannot be
        fooled by a plausible-looking line.
        """
        for rel in ("backend/studio/plugins/discovery/symoneural-discovery.env",
                    "backend/studio/plugins/discovery/symoneural-discovery.venv/bin/pip"):
            with self.subTest(rel=rel):
                proc = subprocess.run(("git", "-C", str(REPO), "check-ignore", "-q", rel),
                                      capture_output=True)
                self.assertEqual(0, proc.returncode, f"{rel} is NOT gitignored")

    def test_the_real_env_file_is_not_tracked(self):
        """Belt to the previous test's braces: `.gitignore` does not un-track a file already in
        the index, so a file added before the rule existed stays tracked and stays ignored-
        looking. Only `git ls-files` settles it."""
        tracked = set(_git("ls-files").split())
        self.assertNotIn("backend/studio/plugins/discovery/symoneural-discovery.env", tracked)

    def test_every_tracked_example_has_empty_credential_values(self):
        """Repo-wide, not just this app's template.

        A real token pasted into any tracked `*.example` is a leak whether or not a `.deb` is
        ever built, so the rule belongs on the tracked tree. It runs over `git ls-files` output
        for that reason — `find` would also walk `external/`, `.venv`s and 104 GiB of
        `models/`, none of which is publishable and all of which is out of scope.

        The failure message names the file and the key and **never the value**: a test whose
        output carries the secret it caught has published it into CI logs and commit messages.
        """
        examples = [p for p in _git("ls-files").split()
                    if (p.endswith(".example") or p.endswith(".env.example"))
                    # `archive/vendor-sdks/` is third-party source #103 copied out of
                    # `external/` under a read licence. Upstream's own templates are not
                    # ours to edit, and editing one would be worse than leaving it: the whole
                    # value of a vendored tree is that it matches the upstream commit recorded
                    # in `archive/vendor-sdks/PROVENANCE.md`, and a locally-blanked line makes that
                    # claim false while looking tidier.
                    #
                    # Caught by this test the moment `archive/vendor-sdks` became tracked, which is
                    # exactly when it should have been:
                    # `agent-sdk-workshop/.env.example` carries `ANTHROPIC_API_KEY=sk-ant-...`.
                    # That is a placeholder, and the rule above deliberately cannot tell a
                    # placeholder from a real key -- a rule that tried would eventually wave a
                    # real one through. So the fix is to scope WHOSE templates this polices,
                    # never to soften what it counts as a value.
                    #
                    # Third of three walkers pruned for this tree; `test_credential_header.py`
                    # and `test_references_boundary.py` are the others, each for the same
                    # reason and each recorded at its own prune.
                    and not p.startswith("archive/vendor-sdks/")]
        self.assertTrue(examples, "expected at least one tracked *.example file")
        self.assertTrue(
            any(p.startswith(("backend/", "ops/", "scripts/")) for p in examples),
            "the vendor exclusion swallowed our own templates too; it must narrow whose "
            "files are policed, not stop the rule policing anything")
        offenders = []
        for rel in examples:
            for lineno, line in enumerate((REPO / rel).read_text().splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip().removeprefix("export ").strip()
                if self.CREDENTIAL_SHAPED.search(name) and value.strip():
                    offenders.append(f"{rel}:{lineno} {name}")
        self.assertEqual([], offenders,
                         "credential-shaped names in a tracked template must have no value")

    def test_the_template_carries_every_name_the_tool_reads(self):
        """A key the code looks up and the template omits is a silent misconfiguration.

        The names are scraped out of `discovery.py`'s `os.environ.get(...)` calls rather than
        listed here, so adding a backend without adding its line to the template fails this.
        `SYMONEURAL_DISCOVERY_*` is excluded: those are switches set by a unit file or a shell,
        not credentials pasted into the app's env file.
        """
        source = (PKG / "discovery.py").read_text()
        looked_up = {m for m in re.findall(r'os\.environ\.get\(\s*"([A-Z0-9_]+)"', source)
                     if not m.startswith("SYMONEURAL_")}
        template = envfile.parse(
            (PKG / "symoneural-discovery.env.example").read_text())
        self.assertTrue(looked_up, "expected discovery.py to read some vendor env vars")
        self.assertEqual(set(), looked_up - set(template),
                         "read by discovery.py but missing from the tracked template")


class EnvFileTests(unittest.TestCase):
    def test_parses_the_four_shapes_a_hand_edited_file_has(self):
        parsed = envfile.parse(
            "# comment\n"
            "export A = 1\n"
            'B="two"\n'
            "C=\n"
            "junk-with-no-equals\n"
            " D = 'four' \n"
        )
        self.assertEqual({"A": "1", "B": "two", "C": "", "D": "four"}, parsed)

    def test_an_empty_value_is_kept_not_dropped(self):
        """`build_backend` tests values for truth, so "present but empty" must survive parsing
        as the normal state of an unconfigured install. Dropping it would make
        `"GOOGLE_CSE_API_KEY" in os.environ` false and change which error the user sees."""
        self.assertEqual({"K": ""}, envfile.parse("K="))

    def test_the_shell_wins_over_the_file(self):
        """The reason this is not python-dotenv's default-overwrite behaviour: a systemd unit's
        `EnvironmentFile=/etc/symoneural/api.env` must not be silently replaced by whatever a
        checkout happens to contain."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.env"
            path.write_text("SYMONEURAL_DISCOVERY_TEST_A=from-file\n"
                            "SYMONEURAL_DISCOVERY_TEST_B=from-file\n")
            os.environ["SYMONEURAL_DISCOVERY_TEST_A"] = "from-shell"
            os.environ.pop("SYMONEURAL_DISCOVERY_TEST_B", None)
            try:
                applied = envfile.load(path)
                self.assertEqual("from-shell", os.environ["SYMONEURAL_DISCOVERY_TEST_A"])
                self.assertEqual("from-file", os.environ["SYMONEURAL_DISCOVERY_TEST_B"])
                self.assertEqual(["SYMONEURAL_DISCOVERY_TEST_B"], applied)
            finally:
                for name in ("SYMONEURAL_DISCOVERY_TEST_A", "SYMONEURAL_DISCOVERY_TEST_B"):
                    os.environ.pop(name, None)

    def test_load_returns_names_and_never_values(self):
        """So that `stats`, a log line or a test failure can print the result unexamined."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.env"
            path.write_text("SYMONEURAL_DISCOVERY_TEST_SECRET=hunter2-do-not-print\n")
            os.environ.pop("SYMONEURAL_DISCOVERY_TEST_SECRET", None)
            try:
                applied = envfile.load(path)
                self.assertEqual(["SYMONEURAL_DISCOVERY_TEST_SECRET"], applied)
                self.assertNotIn("hunter2-do-not-print", "".join(applied))
            finally:
                os.environ.pop("SYMONEURAL_DISCOVERY_TEST_SECRET", None)

    def test_a_missing_file_is_not_an_error(self):
        """`stats`, `export` and the duckduckgo backend need no credentials at all."""
        self.assertEqual([], envfile.load(Path("/nonexistent") / "nope.env"))

    def test_the_default_path_is_beside_the_package_and_app_named(self):
        """Garrett's rule: one env file per app, named `symoneural-<extension>.env` after the
        app rather than identified by which directory it sits in."""
        self.assertEqual(PKG, envfile.DEFAULT_PATH.parent)
        self.assertEqual("symoneural-discovery.env", envfile.DEFAULT_PATH.name)


class RackRowTests(unittest.TestCase):
    def test_state_is_a_value_the_Unit_model_accepts(self):
        """Read out of `api.py` rather than copied here.

        `status()` first returned `degraded`, which is the honest word for this box — search
        runs, rendering does not — and which `Unit.state`'s `Literal` rejects with a pydantic
        error at the moment the rack is assembled. This test is why that was found before the
        commit rather than by a 500 on the front page.
        """
        api = (REPO / "backend" / "server.py").read_text()
        match = re.search(r'state:\s*Literal\[([^\]]+)\]', api)
        self.assertIsNotNone(match, "could not find Unit.state's Literal in api.py")
        allowed = set(re.findall(r'"([a-z]+)"', match.group(1)))
        self.assertIn(app.status()["state"], allowed)

    def test_the_row_carries_exactly_the_keys_the_model_requires(self):
        """`sub` is the only optional field on `Unit`, and this surface owns one kind of
        hardware, so the required set is the whole set."""
        api = (REPO / "backend" / "server.py").read_text()
        block = re.search(r'class Unit\(BaseModel\):\n(.*?)\n\n', api, re.S).group(1)
        fields = set(re.findall(r'^\s{4}(\w+):', block, re.M)) - {"sub"}
        self.assertEqual(fields, set(app.status()))

    def test_bus_is_net_because_nothing_here_takes_a_gpu_lease(self):
        self.assertEqual("net", app.status()["bus"])
        source = (PKG / "discovery.py").read_text() + (PKG / "__init__.py").read_text()
        self.assertNotIn("gpu-governor.sh acquire", source)

    def test_the_router_is_not_exported_while_the_page_does_not_exist(self):
        """`apps/voice` is the precedent: a rack row pointing at a 404 is worse than no row.
        `status()['href']` is `/discovery.html`, which is not built yet — so `api.py` must have
        no `include_router` for this app, and this test is what makes the pair move together."""
        self.assertFalse(hasattr(app, "router"))
        api = (REPO / "backend" / "server.py").read_text()
        # Match the import path this app has NOW. The old assertion read
        # `assertNotIn("symoneuraldiscovery", api)`, and after the move to
        # `studio/plugins/discovery` that string could never appear in `api.py` again --
        # so the test would have passed even with the router wired, which is the one
        # thing it exists to catch. A rename can turn a real check into a tautology.
        for wiring in ("plugins.discovery", "plugins import discovery"):
            self.assertNotIn(wiring, api, f"api.py wires {wiring} but /discovery.html "
                                          "is not built -- a rack row pointing at a 404")


class BackendSelectionTests(unittest.TestCase):
    def test_an_empty_value_is_reported_as_unset_not_sent_to_the_vendor(self):
        """The template ships every name present and empty, so a presence check would send an
        empty key to Google and surface a vendor 400 instead of "set this variable"."""
        os.environ["GOOGLE_CSE_API_KEY"] = ""
        os.environ["GOOGLE_CSE_CX"] = ""
        try:
            with self.assertRaises(SystemExit) as caught:
                discovery.build_backend("google")
            self.assertIn("GOOGLE_CSE_API_KEY", str(caught.exception))
        finally:
            for name in ("GOOGLE_CSE_API_KEY", "GOOGLE_CSE_CX"):
                os.environ.pop(name, None)

    def test_the_no_key_backend_needs_no_key(self):
        self.assertEqual("duckduckgo", discovery.build_backend("duckduckgo").name)

    def test_an_unknown_backend_names_the_known_ones(self):
        with self.assertRaises(SystemExit) as caught:
            discovery.build_backend("altavista")
        self.assertIn("duckduckgo", str(caught.exception))

    def test_every_advertised_backend_can_be_constructed_or_names_its_variable(self):
        """No `--backends` choice may raise anything other than a `SystemExit` that says which
        variable is missing. A `KeyError` or an `AttributeError` here would be a typo in a
        branch nobody exercises, which is precisely what an unkeyed box cannot otherwise
        catch."""
        for name in discovery.BACKEND_NAMES:
            with self.subTest(backend=name):
                try:
                    discovery.build_backend(name)
                except SystemExit as exc:
                    self.assertRegex(str(exc), r"[A-Z_]{6,}", "must name the variable")


class ExitCodeTests(unittest.TestCase):
    """`search` distinguishes "nothing matched" from "the backend broke" by exit code.

    Driven with a stub backend rather than a live query, because the network cannot be made to
    return zero results on demand: the obvious test — search for a nonsense string — was tried
    against DuckDuckGo and came back with four hits, so it proved nothing.
    """

    def _run(self, hits):
        class Stub(discovery.SearchBackend):
            name = "duckduckgo"

            def search(self, query, n):
                return hits

        real = discovery.build_backend
        discovery.build_backend = lambda name: Stub()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # A private --db, so a test never writes into run/ beside the real database,
                # and --cache-ttl 0 so a stub's empty result cannot be served from a cache
                # another test populated.
                return discovery.main(["--db", str(Path(tmp) / "t.sqlite3"), "--env",
                                       str(Path(tmp) / "absent.env"), "search", "q",
                                       "--cache-ttl", "0", "--out", str(Path(tmp) / "o.json")])
        finally:
            discovery.build_backend = real

    def test_no_results_is_a_nonzero_exit(self):
        self.assertEqual(1, self._run([]))

    def test_results_are_a_zero_exit(self):
        self.assertEqual(0, self._run(
            [discovery.SearchHit("t", "https://a.example", "s", 1, "duckduckgo")]))

    def test_a_missing_dependency_exits_3_with_the_install_command_and_no_traceback(self):
        """`main` catches `MissingDependency` on purpose: the useful part of that failure is the
        install command, and a traceback buries it under twenty frames."""
        class Stub(discovery.SearchBackend):
            name = "duckduckgo"

            def search(self, query, n):
                raise discovery.MissingDependency("playwright is not installed. pip install x")

        real = discovery.build_backend
        discovery.build_backend = lambda name: Stub()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(3, discovery.main(
                    ["--db", str(Path(tmp) / "t.sqlite3"), "--env",
                     str(Path(tmp) / "absent.env"), "search", "q", "--cache-ttl", "0"]))
        finally:
            discovery.build_backend = real

    def test_retry_does_not_swallow_a_missing_dependency(self):
        """Backoff cannot install a package, so retrying one is pure delay before the same
        failure — and `search_with_retry` returns `[]` for everything it does catch, which
        would have turned "playwright is missing" into "no results".

        Read with `test_the_missing_dependency_handler_stays_ahead_of_the_broad_ones` below,
        which is the mutation-sensitive half. This one pins the contract callers depend on, and
        deleting the `except MissingDependency: raise` clause does NOT break it: the clause is
        redundant today, because MissingDependency is a RuntimeError and every other handler in
        that try is a `requests.exceptions.*`. Measured, not assumed — the clause was deleted
        and this test still passed. Its value is the day someone adds an `except Exception` for
        a flaky backend, and position is what the other test asserts."""
        class Stub(discovery.SearchBackend):
            name = "stub"

            def search(self, query, n):
                raise discovery.MissingDependency("nope")

        with self.assertRaises(discovery.MissingDependency):
            discovery.search_with_retry(Stub(), "q", 1, discovery.RetryConfig(max_attempts=3))

    def test_the_missing_dependency_handler_stays_ahead_of_the_broad_ones(self):
        """The property that clause actually buys, asserted structurally because behaviour
        cannot see it yet.

        `search_with_retry` catches to return `[]`, which is right for a dead key and wrong for
        a missing package — the caller needs the install command, and `[]` reads as "no
        results". Today MissingDependency escapes on its own; the moment a broader handler goes
        in above it the swallow appears, and the behavioural test above would still pass. So
        this asserts position rather than behaviour: MissingDependency is caught first, and it
        re-raises bare. Fails if the clause is deleted, if it is moved down, or if a bare
        `except:` or `except Exception` is inserted ahead of it."""
        fn = next(n for n in ast.walk(ast.parse(Path(discovery.__file__).read_text()))
                  if isinstance(n, ast.FunctionDef) and n.name == "search_with_retry")
        tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
        self.assertEqual(len(tries), 1, "search_with_retry no longer has exactly one try")
        names = ["<bare except>" if h.type is None else ast.unparse(h.type)
                 for h in tries[0].handlers]
        self.assertIn("MissingDependency", names,
                      "the MissingDependency clause is gone; `[]` now hides an install error")
        first = names.index("MissingDependency")
        self.assertEqual(first, 0,
                         f"MissingDependency is caught at position {first}, behind "
                         f"{names[:first]} — anything ahead of it can swallow it into `[]`")
        raised = [n for n in ast.walk(tries[0].handlers[0]) if isinstance(n, ast.Raise)]
        self.assertTrue(raised, "the clause catches MissingDependency and never re-raises it")
        self.assertIsNone(raised[0].exc, "re-raise bare, so the install command survives intact")


class FusionTests(unittest.TestCase):
    def test_agreement_across_sources_beats_a_single_first_place(self):
        """The entire reason RRF is here rather than a concatenation."""
        agreed = discovery.SearchHit("t", "https://b.example", "", 2, "x")
        fused = discovery.reciprocal_rank_fusion([
            [discovery.SearchHit("t", "https://a.example", "", 1, "one"), agreed],
            [discovery.SearchHit("t", "https://b.example", "", 2, "two")],
            [discovery.SearchHit("t", "https://b.example", "", 3, "three")],
        ])
        self.assertEqual("https://b.example", fused[0].url)

    def test_a_trailing_slash_is_not_a_different_page(self):
        fused = discovery.reciprocal_rank_fusion([
            [discovery.SearchHit("t", "https://a.example/", "", 1, "one")],
            [discovery.SearchHit("t", "https://a.example", "", 1, "two")],
        ])
        self.assertEqual(1, len(fused))


class StoreTests(unittest.TestCase):
    def test_ranked_seeds_come_before_pages_found_by_following_a_link(self):
        """`worker()` propagates `query` to depth+1 so `answer` can cite a crawled page, and
        those arrive with `rank = 0`. A plain `ORDER BY rank` would therefore hand the
        synthesiser a page nobody searched for as source `[1]`."""
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                store = discovery.Store(Path(tmp) / "d.sqlite3")
                try:
                    ok = discovery.FetchResult(status="ok", title="t", text="body")
                    await store.save("https://child.example", 1, ok, query="q", rank=0)
                    await store.save("https://seed.example", 0, ok, query="q", rank=2)
                    return [p["url"] for p in store.get_pages_for_query("q")]
                finally:
                    store.close()
        self.assertEqual(["https://seed.example", "https://child.example"], asyncio.run(run()))

    def test_only_successful_pages_are_offered_to_the_synthesiser(self):
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                store = discovery.Store(Path(tmp) / "d.sqlite3")
                try:
                    await store.save("https://ok.example", 0,
                                     discovery.FetchResult(status="ok"), query="q", rank=1)
                    await store.save("https://blocked.example", 0,
                                     discovery.FetchResult(status="skipped", error="robots.txt"),
                                     query="q", rank=2)
                    return [p["url"] for p in store.get_pages_for_query("q")]
                finally:
                    store.close()
        self.assertEqual(["https://ok.example"], asyncio.run(run()))

    def test_the_database_lands_under_run_and_not_the_working_directory(self):
        """`run/` is gitignored and holds the governor's lock; a database written to whatever
        cwd a cron line happened to have would be untracked in a different sense."""
        self.assertEqual(REPO / "run", discovery.DB_PATH.parent)
        self.assertEqual(REPO / "run", discovery.PROFILE_DIR.parent)

    def test_repo_root_is_found_by_signature(self):
        self.assertEqual(REPO, discovery.repo_root())


class SynthesisTests(unittest.TestCase):
    def test_no_pages_is_reported_rather_than_sent_to_the_model(self):
        self.assertIn("nothing to synthesise", discovery.synthesize_answer("q", []))

    def test_a_page_that_failed_to_render_falls_back_to_its_snippet(self):
        """Otherwise source `[1]` is a labelled blank, and a citation to an empty source is
        worse than one fewer source."""
        prompt = discovery.build_answer_prompt(
            "q", [{"url": "https://a.example", "title": "T", "text": "", "snippet": "S"}])
        self.assertIn("S", prompt)
        self.assertIn("[1]", prompt)

    def test_the_prompt_forbids_filling_gaps_from_general_knowledge(self):
        """The one sentence in the system prompt that makes the citations mean anything."""
        self.assertIn("ONLY the source excerpts", discovery.ANSWER_SYSTEM_PROMPT)
        self.assertIn("say so explicitly", discovery.ANSWER_SYSTEM_PROMPT)


class NamingTests(unittest.TestCase):
    """The house naming system, applied to the newest app so it does not need a later sweep."""

    def test_no_bare_three_letter_prefixed_identifiers(self):
        """Only `symon`, `symonsays` and `symoneural`, always with an extension.

        The bare three-letter prefix — as an env-var prefix or as a browser-storage key —
        is what task #25 exists to clean up across the rest of the tree, and nothing in the
        newest app should be added to that backlog.

        The pattern is assembled from fragments rather than written as one literal, and this
        file is inside the scanned set. Both halves of that are deliberate: a naming test that
        excludes itself cannot notice when its own fixtures start violating the rule, and a
        test whose source spells out the forbidden token would flag itself forever. The first
        version of this test did exactly that and failed on its own docstring.
        """
        bare = "SYM" + "_"
        pattern = re.compile(r"\b" + bare + r"|\b" + "sym" + r"[._-](?!oneural|on)")
        offenders = []
        for path in sorted(PKG.glob("*")) + [Path(__file__)]:
            if path.is_dir():
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                for match in pattern.finditer(line):
                    offenders.append(f"{path.name}:{lineno} {match.group(0)!r}")
        self.assertEqual([], offenders)

    def test_that_naming_scan_actually_catches_a_violation(self):
        """A positive control for the test above.

        Its green has to come from the tree being clean, not from the pattern having been
        broken by a careless edit to the fragments it is assembled from — which is a live risk
        precisely because they are fragments. An always-empty `offenders` list would pass
        silently forever, and this is the check that makes that impossible.
        """
        bare = "SYM" + "_"
        pattern = re.compile(r"\b" + bare + r"|\b" + "sym" + r"[._-](?!oneural|on)")
        self.assertTrue(pattern.search(bare + "STUDIO_TOKEN"))
        self.assertTrue(pattern.search("sym" + ".studio.token"))
        self.assertIsNone(pattern.search("SYMONEURAL_DISCOVERY_TOKEN"))
        self.assertIsNone(pattern.search("symoneural-discovery.env"))
        self.assertIsNone(pattern.search("symonsaynews"))

    def test_the_per_app_artefacts_share_one_stem(self):
        """Garrett's rule, 2026-08-20: the env file, the venv and the requirements file are all
        named after the app rather than identified by their directory, so
        `symoneural-discovery.*` finds the whole set."""
        names = {p.name for p in PKG.iterdir()}
        self.assertIn("symoneural-discovery.env.example", names)
        self.assertIn("symoneural-discovery.requirements.txt", names)
        self.assertNotIn("requirements.txt", names)
        self.assertNotIn(".env.example", names)

    def test_the_user_facing_label_reads_as_symon_say_something(self):
        """Every surface's display string derives from "Symon Say <do something>" — hence Symon
        Say News, hence this."""
        self.assertTrue(app.status()["label"].startswith("Symon Say "))


if __name__ == "__main__":
    unittest.main()
