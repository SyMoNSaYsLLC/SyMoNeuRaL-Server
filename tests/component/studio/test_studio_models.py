"""`GET /api/studio/models` -- the route, its validator, and the file behind it.

This file sits at the top of `apps/` rather than inside an app package because the route it
covers is not in one: it is declared inline in `backend/server.py`, next to the section routes.
`pytest apps/` collects it either way.

`api.py` is **read as source, never imported** -- the same discipline as
`apps/sigils/test_sigils.py`. Importing the serving module from a test executes the whole
application: it builds every rate limiter, resolves the GPU governor, and mounts `site/`. The
two facts asserted below are each a single line in that file, and the ordering one has already
been the cause of a dead route elsewhere in this codebase.

The validator is exercised for real, not paraphrased. `_studio_rows` and its field table are
lifted out of the parsed AST and executed on their own, so what runs here is the same source
the server runs -- a reimplementation in the test would pass happily while the route rotted.
"""
from __future__ import annotations

import ast
import json
import pathlib
import subprocess
import sys
import unittest

BACKEND = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
ROOT = BACKEND.parent
API_PY = BACKEND / "backend" / "server.py"
TREE = ast.parse(API_PY.read_text())


def _extract(*names: str) -> dict:
    """Execute just the named top-level definitions from api.py, in an empty namespace.

    Only assignments and function definitions are taken, so nothing with a side effect can
    come along for the ride -- no decorator runs, no app object is constructed, no import at
    the top of api.py is executed.
    """
    wanted = []
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            wanted.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id in names:
            wanted.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    wanted.append(node)
                    break
    missing = set(names) - {
        n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        else (n.target.id if isinstance(n, ast.AnnAssign) else n.targets[0].id)
        for n in wanted}
    assert not missing, f"{API_PY} no longer defines {sorted(missing)}"
    ns: dict = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(API_PY), "exec"), ns)
    return ns


class RouteIsReachable(unittest.TestCase):
    """The two structural facts. Both are one line, and both have gone wrong before."""

    def test_the_route_is_declared(self):
        paths = [
            d.args[0].value
            for node in ast.walk(TREE)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for d in node.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and d.func.attr == "get" and d.args and isinstance(d.args[0], ast.Constant)
        ]
        self.assertIn("/api/studio/models", paths,
                      "the studio model list is not declared in api.py")

    def test_it_is_declared_above_the_static_mount(self):
        """`app.mount("/", StaticFiles(...))` matches everything at `/`.

        A route declared after it is unreachable -- it does not error, it just quietly never
        matches, which is the failure mode that makes this worth a test rather than a comment.
        api.py says so itself above the section routes; this is that sentence, enforced.
        """
        mounts = [n.lineno for n in ast.walk(TREE)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "mount"]
        self.assertEqual(len(mounts), 1, "api.py should mount StaticFiles exactly once")

        route = [d.lineno
                 for node in ast.walk(TREE)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 for d in node.decorator_list
                 if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                 and d.func.attr == "get" and d.args
                 and getattr(d.args[0], "value", None) == "/api/studio/models"]
        self.assertTrue(route, "no /api/studio/models route to place")
        self.assertLess(route[0], mounts[0],
                        "/api/studio/models is declared BELOW the StaticFiles mount, so it "
                        "can never match")

    def test_the_router_count_is_unchanged(self):
        """Fourteen `include_router` calls, and adding a plain route must not move that.

        The count is the cheap proxy for "no surface was mounted or unmounted by accident".
        It is recorded in `.claude/HANDOVER.md`; if this fails, one of the two is wrong and
        it is worth finding out which before changing the number here.

        Was 8 until `apps/controlboard` was mounted at `/api/rack` -- the per-unit power
        switch. That is a deliberate ninth surface, so this number moved in the same commit
        that mounted it, which is the whole point of the tripwire: it should be impossible
        to add a router without someone typing the new number and meaning it.

        Then 9 -> 11, both in the commit that added the Studio, and both deliberate: one
        router at `/api/studio` and one at `/studio/editor`. The second is the odd one and is
        the reason this docstring says eleven rather than ten -- it serves ComfyUI's own node
        editor as an HTML application, so it does not belong under `/api`, and it is a
        separate `include_router` rather than a sub-prefix because a router's prefix cannot
        put half its routes outside its own tree.

        Then 11 -> 12 for `apps/studio/plugins/exp` at `/api/exp` -- the plugin runtime. One
        router, and the page it serves is a generated file behind a plain `@app.get("/exp")`
        rather than a second router, so this moved by one and not by two.

        Then 12 -> 13 for `apps/news` at `/api/news` -- the live ticker's collector.
        One router carrying one read-only endpoint, and the bar itself is drawn by
        `site/ui.js` rather than by a page of its own, so again this moved by one.

        Then 13 -> 14 for `apps/live` at `/api/live` -- the OBS stream. One router carrying
        all five of its routes including the segment bytes, and the page at `/livestack/live`
        is a plain `@app.get` like `/exp`'s, so this moved by one and not by two. Worth
        knowing why it is one and not two: the video is served BY that router
        (`/api/live/hls/{name}`) rather than by a static mount, because `site/` is a staging
        directory and a file written there 404s for every visitor until `deploy.sh` runs --
        a live stream that only appears after a deploy is not a live stream.

        Then 14 -> 15 for `apps/dispatchos`, which mounts TWO routers -- `router` under
        `/api/dispatchos` and `ui_router` with no prefix for the page at `/demo/dispatchos`.
        This is the first surface to move the count by two, and the reason is the one the
        `/exp` paragraph above rules out for everything before it: its page is not a
        `@app.get` on a generated file, it is a route on the application's own router,
        because the path has no extension and `scripts/deploy.sh` publishes `site/` at
        `-maxdepth 1`. The count was 14 and the tree had 15 for days -- this tripwire was
        red at 2026-08-29 and had been, which is what it is for.

        14 -> 16, and BOTH of those are dispatchos. Verified against the tree rather than
        reasoned from the history above: the sixteen calls are streamer, accounts, gateway,
        streamer.guide, project, rackpower, reinforce, voice, sigils, studio, studio.ui,
        exp, news, live, dispatchos and dispatchos.ui. Nothing was added by the 2026-08-29
        documentation work -- `apps/appdocs` mounts NO router at all. It is a registry and a
        renderer, and the two routes that use it, `/docs/{app_id}` and
        `/demo/dispatchos/docs`, are plain `@app.get` declarations in this file.

        So this tripwire had been red for the same reason `EXPECTED`, `ROSTER.md` and the
        rack-count comment were: dispatchos landed and the descriptions did not follow. Four
        separate hand-maintained counts, one omission, four red tests -- which is precisely
        the argument for keeping them hand-maintained instead of deriving them from
        each other.

        16 -> 17 for `apps/coders` at `/local/coders` -- the multi-coder session surface
        (R-184). One router, and it moves the count by one rather than two even though it has
        a page, because that page is a plain `@app.get("/coders")` on a file
        (`apps/coders/page.html`) -- the `/exp` shape, not the dispatchos shape.

        This is the first router mounted under `/local` rather than `/api`, and the prefix is
        the point rather than a naming preference: `ops/Caddyfile` reverse-proxies the whole
        `/api/*` subtree to the internet, and these routes spawn provider CLIs under the
        operator's own logged-in sessions. It is also the first to carry
        `dependencies=[Depends(_require_local)]` on the `include_router` call itself, so a
        route added to `apps/coders/routes.py` later is local-only by construction rather
        than by the author remembering.
        """
        calls = [n for n in ast.walk(TREE)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "include_router"]
        self.assertEqual(len(calls), 17)


class ValidatorRejectsJunk(unittest.TestCase):
    """`run/` is world-readable state on a box that also runs a web server.

    The file is re-validated on read even though `tools/build/build_registry.py` wrote it, exactly as
    `apps/studio/plugins/reinforce/jobs.py` re-validates `progress.json`. These cases are what that buys.
    """

    @classmethod
    def setUpClass(cls):
        # staticmethod, or Python binds it as a method and passes `self` as the document.
        cls.rows = staticmethod(_extract("_studio_rows", "_STUDIO_FIELDS")["_studio_rows"])

    def test_a_document_that_is_not_a_list_yields_nothing(self):
        for junk in (None, {}, "models", 7, [], True):
            self.assertEqual(self.rows(junk), [], f"{junk!r} should produce no rows")

    def test_a_row_without_a_string_id_is_not_a_model(self):
        """A row that cannot name itself is dropped rather than reported as an unnamed model."""
        self.assertEqual(self.rows(["nope", 42, None, {}, {"id": 7}, {"no_id": 1}]), [])

    def test_wrong_types_become_null_rather_than_reaching_the_client(self):
        out = self.rows([{
            "id": "ok/model",
            "name": 12,                    # not a string
            "present": "yes",              # not a bool
            "capabilities": "text-generation",   # a string, not a list
            "bytes_on_disk": "big",        # not an int
            "latency_ms": "fast",          # not a number
        }])
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row["id"], "ok/model")
        for field in ("name", "present", "capabilities", "bytes_on_disk", "latency_ms"):
            self.assertIsNone(row[field], f"{field} should have been rejected")

    def test_every_field_is_present_even_when_the_writer_omitted_it(self):
        """One stable shape, so the client's decode path does not branch on absence."""
        ns = _extract("_studio_rows", "_STUDIO_FIELDS")
        row = ns["_studio_rows"]([{"id": "bare"}])[0]
        self.assertEqual(set(row), set(ns["_STUDIO_FIELDS"]))
        self.assertTrue(all(v is None for k, v in row.items() if k != "id"))

    def test_a_bool_is_never_accepted_as_a_number(self):
        """`bool` subclasses `int`, so an unguarded isinstance lets `True` through as bytes."""
        row = self.rows([{"id": "x", "bytes_on_disk": True, "latency_ms": False}])[0]
        self.assertIsNone(row["bytes_on_disk"])
        self.assertIsNone(row["latency_ms"])

    def test_good_rows_survive_intact(self):
        row = self.rows([{
            "id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen/Qwen2.5-7B-Instruct",
            "kind": "hf", "present": True, "trainable": True,
            "capabilities": ["text-generation", "fine-tune:qlora"],
            "bytes_on_disk": 15231271888, "bytes_on_disk_label": "measured",
        }])[0]
        self.assertTrue(row["present"])
        self.assertEqual(row["capabilities"], ["text-generation", "fine-tune:qlora"])
        self.assertEqual(row["bytes_on_disk"], 15231271888)

    def test_the_on_disk_path_never_reaches_the_client(self):
        """`path` is in the file and must stay out of the response.

        The route is public: Caddy delegates all of `/api/*` and there is no surface flag in
        front of this one, unlike `/api/train/models`, which publishes the same field behind
        `_require_surface()`. The value is this repo's directory layout plus an HF snapshot
        hash -- a fact about the box, not about the model -- and the client does not need it,
        so the field is dropped at the validator rather than trusted not to be looked at.
        """
        ns = _extract("_studio_rows", "_STUDIO_FIELDS")
        self.assertNotIn("path", ns["_STUDIO_FIELDS"])
        row = ns["_studio_rows"]([{
            "id": "x",
            "path": "backend/models/hf/hub/models--Qwen--Qwen2.5-7B-Instruct/snapshots/deadbeef",
        }])[0]
        self.assertNotIn("path", row)


class TheRouteIsMeterable(unittest.TestCase):
    """`SYMONEURAL_RATE_STUDIO` must be read by something.

    No limit is set on any surface here today -- that was the operator's call on 2026-08-17 --
    so this asserts the knob exists, not that it is turned. A surface missing from
    `_RATE_SUGGESTED` is not "unlimited by choice", it is unmeterable: `LIMITS` is built by
    iterating that dict and `check_rate` returns True for any name it cannot find, so the
    environment variable would be read by nothing at all.
    """

    def test_the_route_declares_a_throttle(self):
        for node in ast.walk(TREE):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name != "studio_models":
                continue
            deps = [
                kw for dec in node.decorator_list if isinstance(dec, ast.Call)
                for kw in dec.keywords if kw.arg == "dependencies"
            ]
            self.assertTrue(deps, "studio_models declares no dependencies")
            self.assertIn("throttled_for(\"studio\")".replace('"', "'"),
                          ast.unparse(deps[0].value).replace('"', "'"))
            return
        self.fail("studio_models not found")

    def test_the_bucket_name_exists_in_the_suggested_table(self):
        for node in ast.walk(TREE):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "_RATE_SUGGESTED" for t in node.targets):
                names = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
                self.assertIn("studio", names,
                              "studio is absent from _RATE_SUGGESTED, so SYMONEURAL_RATE_STUDIO "
                              "would be read by nothing and the surface is unmeterable")
                return
        self.fail("_RATE_SUGGESTED not found")


class TheRouteDoesNoWork(unittest.TestCase):
    """The decoupling rule, asserted against the source of the handler itself.

    The whole reason `tools/build/build_registry.py` exists is that the scan must not happen on the
    live path. Nothing stops someone "fixing" a stale response by calling `registry.catalogue()`
    from the handler, and it would work perfectly in every test that only checks the JSON.
    """

    def _handler(self) -> ast.AsyncFunctionDef:
        for node in ast.walk(TREE):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in node.decorator_list:
                    if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) \
                            and d.func.attr == "get" and d.args \
                            and getattr(d.args[0], "value", None) == "/api/studio/models":
                        return node
        self.fail("no /api/studio/models handler")

    def test_it_neither_scans_nor_forks_nor_takes_the_lock(self):
        called = {n.func.attr for n in ast.walk(self._handler())
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        called |= {n.func.id for n in ast.walk(self._handler())
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        for banned in ("catalogue", "glob", "rglob", "iterdir", "walk", "run", "Popen",
                       "lease", "acquire", "free_vram_bytes"):
            self.assertNotIn(banned, called,
                             f"the studio handler calls {banned}() -- that puts control-plane "
                             f"work on the live request path")

    def test_it_reads_exactly_one_file(self):
        reads = [n for n in ast.walk(self._handler())
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("read_text", "read_bytes", "open")]
        self.assertEqual(len(reads), 1, "the handler should read one pre-computed file")


class TheGenerator(unittest.TestCase):
    """`tools/build/build_registry.py` -- run for real, as a subprocess, writing nothing."""

    @classmethod
    def setUpClass(cls):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "build" / "build_registry.py"),
                              "--print"], capture_output=True, text=True, timeout=180)
        assert out.returncode == 0, out.stderr[-2000:]
        cls.doc = json.loads(out.stdout)

    def test_it_produces_the_document_the_route_expects(self):
        self.assertIsInstance(self.doc["schema"], int)
        self.assertIsInstance(self.doc["generated_at"], int)
        self.assertIsInstance(self.doc["models"], list)

    def test_latency_is_null_on_every_row(self):
        """The honesty assertion, and the reason this test file is worth having.

        Nothing on this machine has measured a per-model latency. The token rate on the site is
        a literal in `tools/build/build_console.py`; the only measurement persisted to disk is peak
        VRAM. If this fails, either a real per-model timing store now exists -- in which case
        the rows carrying a number must also carry `latency_label: "measured"` and the
        timestamp of the run that produced it -- or a constant has been copied in from
        somewhere it was never measured, which is the failure this guards.
        """
        for row in self.doc["models"]:
            self.assertIsNone(row["latency_ms"], f"{row['id']} claims a latency")
            self.assertIsNone(row["latency_label"], f"{row['id']} labels an absent latency")
            self.assertIsNone(row["latency_measured_at"])

    def test_every_stated_figure_carries_a_label(self):
        """`.claude/CLAUDE.md`: measured / vendor / projected, never bare."""
        for row in self.doc["models"]:
            for figure, label in (("bytes_on_disk", "bytes_on_disk_label"),
                                  ("quantisation", "quantisation_label"),
                                  ("parameters", "parameters_label")):
                if row.get(figure) in (None, "", 0):
                    continue
                self.assertIn(row.get(label), ("measured", "vendor", "projected"),
                              f"{row['id']}.{figure} is stated without a label")

    def test_no_absolute_path_leaves_the_box(self):
        """`registry.py` emits repo-relative display paths deliberately; keep it that way."""
        for row in self.doc["models"]:
            self.assertFalse(str(row.get("path", "")).startswith("/"),
                             f"{row['id']} exposes an absolute filesystem path")

    def test_it_never_enumerates_the_training_corpus(self):
        """The trade-secret guard, carried through to this surface.

        `training/corpus.jsonl` and `training/build_dataset.py` are trade secret under
        `.claude/CLAUDE.md`. `registry.catalogue()` refuses to scan datasets for exactly this
        reason; a model list that leaked a corpus path would publish the recipe.
        """
        blob = json.dumps(self.doc)
        for secret in ("corpus.jsonl", "build_dataset", "training/"):
            self.assertNotIn(secret, blob, f"the model list mentions {secret}")


if __name__ == "__main__":
    unittest.main()
