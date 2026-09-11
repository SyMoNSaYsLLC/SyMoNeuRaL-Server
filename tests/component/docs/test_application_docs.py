"""Per-application documentation: ownership is a partition, and leakage is impossible.

`/docs` is the platform-wide reference. `/docs/<id>` is one scoped page per application. The
property that has to hold is that no scoped page ever shows a route belonging to a different
application -- and the way `apps/appdocs.py` gets that is structural rather than careful: route
ownership is a partition over path prefixes, so the sets are disjoint because a partition's
parts are disjoint.

**This file exists to assert the partition, not the pages.** A test that loaded twenty-two
pages and grepped each for the others' paths would pass for the wrong reason the moment two
applications' paths stopped sharing a substring, and would say nothing at all about a route
that belongs to nobody. So the assertions here are about the structure:

  * every prefix has exactly one owner (`appdocs` raises at import otherwise, and that is
    asserted too, because an exception nobody triggers is not a guarantee anybody has);
  * every `/api/*` route the router actually carries has an owner -- TOTALITY, which is the
    half that omission hides. A new router mounted without a registry entry produces a route
    on no documentation page at all, and a disjointness-only test is happy with that;
  * the longest matching prefix wins, so a nested child does not lose its routes to its
    parent's shorter prefix;
  * the customer view of DispatchOS excludes every operator route, by path and not by label.

The router is read through `api.app.routes`, the structure Starlette matches requests against.
`apps/route_matrix.py` records at length why a route list is READ and never inferred: a
"25 broken endpoints" report that was a bad test rather than a bad site. An OpenAPI-derived
list would additionally be blind to WebSocket routes and to `include_in_schema=False`, and
this site has both.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

BACKEND = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from registry.lib import appdocs  # noqa: E402


def _router():
    """The live route table.

    `api` IS imported here, unlike in `test_status_rack.py` which reads it as source. The
    difference is what is being asserted: that file compares three descriptions of the rack
    with each other and can do it from text, while this one asserts a property of the ROUTES
    THAT EXIST, which text cannot answer -- a router included with a prefix contributes paths
    that appear nowhere in any file as a literal. Importing is the cost of asking the real
    question, and the import is done once at module scope by unittest rather than per test.
    """
    import server as api
    return list(api.app.routes)


ROUTES = None


def setUpModule() -> None:
    global ROUTES
    ROUTES = _router()


#: Both mounted namespaces, not just the public one.
#:
#: This read `/api/` only, and the consequence was measured on 2026-09-08: nine `/local/*`
#: routes had no owner and no documentation page, and the totality test was green the whole
#: time. They did not FAIL the check -- they were never inside it. An operator surface is
#: exactly the kind that ends up undocumented, because nobody browsing the public docs
#: notices its absence.
_AUDITED_NAMESPACES = ("/api/", "/local/")


def _api_paths() -> set[str]:
    return {getattr(r, "path", "") for r in ROUTES
            if getattr(r, "path", "").startswith(_AUDITED_NAMESPACES)}


class RegistryIsAPartition(unittest.TestCase):
    def test_every_prefix_has_exactly_one_owner(self):
        """`OWNERS` is built from the registry, so a duplicate cannot be typed into it -- it
        has to be caught while building. This asserts the built map is the size the registry
        implies, which is the same claim from the other side."""
        declared = [p for a in appdocs.APPLICATIONS for p in a.prefixes]
        self.assertEqual(len(declared), len(set(declared)),
                         "two applications claim the same path prefix")
        self.assertEqual(len(appdocs.OWNERS), len(declared))

    def test_a_duplicate_prefix_raises_rather_than_being_accepted(self):
        """The guarantee above is only worth anything if the guard actually fires. Built by
        hand rather than by mutating the module, so a failure here cannot leave the real
        registry damaged for every test that runs after it."""
        clash = appdocs.Application(
            id="clash", label="Clash", kind="application", parent=None,
            runtime="symoneural-llm", page=None, prefixes=("/api/chat",),
            summary="a deliberate collision", auth="none")
        owners: dict[str, str] = {}
        with self.assertRaises(appdocs.RegistryError):
            for app in (appdocs.BY_ID["chat"], clash):
                for p in app.prefixes:
                    if p in owners:
                        raise appdocs.RegistryError(f"prefix {p!r} claimed twice")
                    owners[p] = app.id

    def test_every_api_route_the_router_carries_has_an_owner(self):
        """TOTALITY -- the half a disjointness test cannot see.

        A router mounted without a registry entry does not collide with anything; it simply
        appears on no documentation page, which looks like nothing at all rather than like a
        mistake. That is the same shape as `dispatchos` being a built rack row that no
        description of the rack mentioned, and it went unnoticed for days.
        """
        orphans = sorted(p for p in _api_paths() if appdocs.owner_of(p) is None)
        self.assertEqual(
            orphans, [],
            "these routes are mounted and belong to no application, so they appear on no "
            "scoped documentation page: add a prefix to apps/appdocs.py::APPLICATIONS")

    def test_the_longest_matching_prefix_wins(self):
        """`/api/streamer/guide/*` is owned by `guide`, not by `streamer`.

        Both prefixes match it. Picking the first or the shortest would hand a child's routes
        to its parent -- silently, and with the parent's page then making a claim to routes it
        does not own, which is a leak in the direction that still passes a disjointness check.
        """
        self.assertEqual(appdocs.owner_of("/api/streamer/guide/filter"), "guide")
        self.assertEqual(appdocs.owner_of("/api/streamer/tune"), "streamer")
        self.assertEqual(appdocs.owner_of("/api/studio/state"), "studio")
        self.assertEqual(appdocs.owner_of("/api/train/start"), "train")
        self.assertEqual(appdocs.owner_of("/api/exp/state"), "exp")


class PagesDoNotLeak(unittest.TestCase):
    def test_no_two_applications_render_the_same_route(self):
        seen: dict[tuple, str] = {}
        for app in appdocs.APPLICATIONS:
            for row in appdocs.routes_for(app.id, ROUTES):
                key = (row["path"], tuple(row["methods"]))
                self.assertNotIn(
                    key, seen,
                    f"{row['path']} appears on both /docs/{seen.get(key)} and "
                    f"/docs/{app.id}")
                seen[key] = app.id

    def test_a_scoped_page_shows_only_paths_it_owns(self):
        for app in appdocs.APPLICATIONS:
            with self.subTest(app=app.id):
                for row in appdocs.routes_for(app.id, ROUTES):
                    self.assertEqual(
                        appdocs.owner_of(row["path"]), app.id,
                        f"/docs/{app.id} renders {row['path']}, which it does not own")

    def test_the_rendered_html_of_one_page_contains_no_other_applications_prefix(self):
        """The structural claim, checked once against the actual bytes.

        Everything above reasons about the data; this reads the page. It is deliberately the
        LAST assertion rather than the only one -- a substring check cannot prove disjointness
        (two applications whose paths share no substring would pass it while being wrong) but
        it does catch a renderer that reaches past the list it was handed, which the structure
        alone cannot rule out.

        `/api/gen` is excluded from the comparison because `image` owns both it and
        `/api/image`, and a page is allowed to show every prefix IT owns.
        """
        for app in appdocs.APPLICATIONS:
            html = appdocs.render(app, appdocs.routes_for(app.id, ROUTES))
            mine = set(app.prefixes)
            for prefix, owner in appdocs.OWNERS.items():
                if owner == app.id or prefix in mine:
                    continue
                # A prefix that is a path-segment ancestor of one of ours is not a leak: a
                # child page naming `/api/streamer/guide/...` necessarily contains the
                # characters of `/api/streamer`.
                if any(m.startswith(prefix + "/") or prefix.startswith(m + "/")
                       for m in mine):
                    continue
                with self.subTest(app=app.id, foreign=prefix):
                    self.assertNotIn(
                        prefix + "<", html,
                        f"/docs/{app.id} renders a route under {prefix}, owned by {owner}")


class DispatchosCustomerBoundary(unittest.TestCase):
    """The case the handshake names: Donnie's page must not instruct him to do operator work."""

    OPERATOR = ("/api/dispatchos/bookings/{bid}/quote",
                "/api/dispatchos/bookings/{bid}/advance",
                "/api/dispatchos/bookings/{bid}/message",
                "/api/dispatchos/rules",
                "/api/dispatchos/drivers")

    def test_the_operator_list_matches_the_routes_that_actually_require_an_operator(self):
        """Read from the ROUTER's own source, so the registry cannot drift from the guard.

        A hand-typed operator list that falls behind the code is worse than none: it would
        keep hiding the routes it knows about while quietly publishing a newly operator-gated
        one to customers. `_operator(request)` is the single gate in that module and this
        finds every route whose handler calls it.
        """
        import ast
        src = (BACKEND / "apps" / "dispatchos" / "routes.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        gated: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls_operator = any(
                isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                and c.func.id == "_operator" for c in ast.walk(node))
            if not calls_operator:
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    gated.add("/api/dispatchos" + dec.args[0].value)
        self.assertEqual(
            gated, set(self.OPERATOR),
            "the routes that call _operator() and the operator_only list in "
            "apps/appdocs.py have drifted apart")
        self.assertEqual(set(appdocs.BY_ID["dispatchos"].operator_only), set(self.OPERATOR))

    def test_the_customer_view_excludes_every_operator_route(self):
        shown = {r["path"] for r in
                 appdocs.visible_routes("dispatchos", ROUTES, audience="customer")}
        for path in self.OPERATOR:
            with self.subTest(path=path):
                self.assertNotIn(path, shown)

    def test_the_customer_view_still_shows_what_a_customer_can_do(self):
        """Excluding operator work must not empty the page. A customer surface that documents
        nothing is the "misleading empty Swagger page" the handshake rules out."""
        shown = {r["path"] for r in
                 appdocs.visible_routes("dispatchos", ROUTES, audience="customer")}
        for path in ("/api/dispatchos/login", "/api/dispatchos/board",
                     "/api/dispatchos/bookings", "/api/dispatchos/me",
                     "/api/dispatchos/status"):
            with self.subTest(path=path):
                self.assertIn(path, shown)

    def test_the_rendered_customer_page_names_no_operator_path(self):
        html = appdocs.render(
            appdocs.BY_ID["dispatchos"],
            appdocs.visible_routes("dispatchos", ROUTES, audience="customer"),
            audience="customer")
        for path in self.OPERATOR:
            with self.subTest(path=path):
                self.assertNotIn(path, html)
        # And it says that a scope exists, rather than silently presenting a partial list as
        # the whole surface.
        self.assertIn("customer surface", html)

    def test_the_operator_view_is_complete(self):
        """The other half: nothing is hidden from the person entitled to it."""
        shown = {r["path"] for r in appdocs.routes_for("dispatchos", ROUTES)}
        for path in self.OPERATOR:
            with self.subTest(path=path):
                self.assertIn(path, shown)


class EveryApplicationIsReachable(unittest.TestCase):
    def test_every_registry_entry_names_a_runtime_and_a_resolvable_parent(self):
        for app in appdocs.APPLICATIONS:
            with self.subTest(app=app.id):
                self.assertIn(app.runtime, appdocs.RUNTIMES)
                if app.parent is not None:
                    self.assertIn(app.parent, appdocs.BY_ID)
                self.assertIn(app.kind,
                              ("application", "child", "platform", "compatibility"))

    def test_every_rack_row_has_a_documentation_page(self):
        """The rack is what a visitor clicks from, so a row with no scoped docs is the
        gap this task exists to close. Read from ROSTER.md, the identity authority."""
        from registry.lib import roster
        for row in roster.rows():
            with self.subTest(row=row["id"]):
                self.assertIn(row["id"], appdocs.BY_ID,
                              f"the rack row {row['id']} has no /docs/{row['id']} page")

    def test_every_folded_child_has_a_documentation_page_too(self):
        """Folded is not deleted, and that has to be true of the docs as well: `train`, `exp`,
        `gateway`, `gpuminer` and `asicminer` are no longer rack rows and are still surfaces
        somebody has to be able to read about."""
        from test_status_rack import FOLDED
        for child in FOLDED:
            with self.subTest(child=child):
                self.assertIn(child, appdocs.BY_ID)

    def test_no_page_is_generated_for_an_application_with_no_identity(self):
        for app in appdocs.APPLICATIONS:
            with self.subTest(app=app.id):
                self.assertTrue(app.label.strip())
                self.assertTrue(app.summary.strip())
                self.assertTrue(app.auth.strip())


if __name__ == "__main__":
    unittest.main()


class TheApiReferencePageIsWellFormed(unittest.TestCase):
    """Rendered, not read. This defect is invisible to source inspection.

    `API_REFERENCE_STYLE` is interpolated into `<head>`, and its `.ar-index` block sat ABOVE
    the constant's own `<style>` line rather than below it. So twenty CSS rules and a comment
    were emitted into `<head>` as bare character data -- which makes the HTML parser
    implicitly close `<head>` and open `<body>`, so a visitor read the stylesheet as the first
    paragraph of the page and none of those rules applied.

    Nothing in the source looks wrong: it reads as an ordinary stylesheet, and the `.ar-wrap`
    block below it is wrapped correctly. `HANDOFF.md` already carries the bite this
    repeats -- a `console.js` fix was "verified" by reading the file and had not been applied.
    So this asks the page.
    """

    @classmethod
    def setUpClass(cls):
        import server as api
        from fastapi.testclient import TestClient
        # No `with`: the lifespan starts background refreshers and an engine. The route is
        # pure string assembly and needs none of it.
        cls.html = TestClient(api.app).get("/docs").text

    def _style_spans(self) -> list[tuple[int, int]]:
        """(start, end) of each style element's CONTENT."""
        spans, at = [], 0
        while (o := self.html.find("<style", at)) != -1:
            gt = self.html.find(">", o)
            c = self.html.find("</style>", gt)
            if c == -1:
                self.fail("a <style> element is never closed")
            spans.append((gt + 1, c))
            at = c + 8
        return spans

    def test_no_css_rule_is_emitted_outside_a_style_element(self):
        """The defect, stated as the property that was false."""
        spans = self._style_spans()
        self.assertTrue(spans, "the page has no <style> element at all")
        for marker in (".ar-index{", ".ar-wrap{", ".ar-rt>p{", ".ar-appkid:hover{"):
            with self.subTest(rule=marker):
                i = self.html.find(marker)
                self.assertNotEqual(i, -1, f"{marker} is no longer on the page")
                inside = any(s <= i < e for s, e in spans)
                self.assertTrue(
                    inside,
                    f"{marker} is emitted outside any <style> element -- a visitor sees it "
                    "as text and the rule does not apply")

    def test_no_character_data_precedes_the_body(self):
        """The mechanism, asserted directly: bare text in <head> opens <body> early."""
        head = self.html[:self.html.find("</head>")]
        for s, e in reversed(self._style_spans()):
            head = head[:s] + head[e:]            # drop stylesheet contents
        # `<title>` is the one element whose character data legitimately lives in <head>.
        # Dropping it is not a loosened assertion: title text cannot open <body>, and
        # leaving it in made this guard fail on a correct page, which is its own defect.
        head = re.sub(r"<title>.*?</title>", "", head, flags=re.S)
        stripped = re.sub(r"<[^>]+>", "", head).strip()
        self.assertEqual(
            stripped, "",
            "non-whitespace character data appears in <head> outside a style element, which "
            f"implicitly opens <body>: {stripped[:120]!r}")

    def test_no_html_escaped_selector_appears_inside_a_style_block(self):
        """`&gt;` is not a child combinator.

        Worth stating what this does NOT claim. The saved copy that reported this showed
        `.ar-rt&gt;p`, and that escaping was the BROWSER re-serialising text nodes it had
        parsed out of `<body>` -- a symptom of the missing element, not a second defect in
        the emitter. The live page's only `&gt;` is inside a JavaScript escape map. This
        guard exists so that if anyone ever routes this CSS through an HTML-escaping helper,
        it fails here instead of shipping selectors that silently match nothing.
        """
        for s, e in self._style_spans():
            block = self.html[s:e]
            for entity in ("&gt;", "&lt;", "&amp;", "&quot;"):
                with self.subTest(entity=entity):
                    self.assertNotIn(
                        entity, block,
                        f"a style block contains {entity}, so those selectors match nothing")
