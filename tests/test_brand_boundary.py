"""The vendor name of the symbolic engine must not appear on a visitor-facing surface.

Task #74 item 7. The rule it enforces, in Garrett's framing: *"Only the vendor's name
goes"* -- the argument the RavenCalc page makes ("exact symbolic computation, not a
language model guessing at algebra") is true of our engine word for word, so the prose
survives the rename and only the third-party name is removed.

**Two of these tests exist because grep cannot see the worst offender.** `ravencalc.py`
returns an `engine` field and a `note` field, and `build_pages.py` renders both straight
into the readout -- so the page printed `eng sympy 1.13.3` after every single calculation
while every static occurrence in `site/` was already clean. A check that greps the HTML
goes green in that state, which is why `test_rendered_response_fields` computes real
expressions and reads the values a browser would actually display.

**`site/credits.html` is asserted the other way round, and that is deliberate.** SymPy is
BSD-3-Clause. The licence does not require the name in the interface, but it does require
the copyright notice in accompanying documentation, and once the pages stop naming it
`credits.html` and `LICENSES.md` become the whole of the disclosure. So this file fails if
that attribution is ever removed. Renaming what we present is ours to do; dropping the
notice is not.

Nothing here objects to `import sympy` in the engine internals. The import is not a
surface, and putting the dependency behind our own module is item 5's separate job.
"""
from __future__ import annotations

import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
SITE = REPO / "site"

#: Matched case-insensitively: the JS comment shipped in `ravencalc.html` spells it
#: lowercase, and a rename that tidied the capitalised ones only would still ship it.
VENDOR = re.compile(r"sympy", re.IGNORECASE)

#: The one page that must keep the name, because it is where the licence is honoured.
ATTRIBUTION_PAGES = {"credits.html"}

#: Every generator, found by glob rather than listed. Editing `site/*.html` by hand would
#: be undone by the next build, so the boundary is asserted on the source as well.
#:
#: Globbed because a hand-written list is what made this task look finished when it was
#: not: the shared "RavenCalc is the exception" sentence is emitted by *eight* generators,
#: not the two that grep of `site/` pointed at, and six pages kept the vendor name through
#: a full rebuild simply because nobody ran the generator that owns them.
GENERATORS = tuple(sorted(str(p.relative_to(REPO)) for p in (REPO / "tools").glob("build_*.py")))

#: The upstream identifiers of the ported design tokens (#91). `dsw` is anchored on a word
#: boundary rather than matched as a bare substring: three letters is short enough to land
#: inside an ordinary word, and this repo has a standing rule against blind substring
#: sweeps because most `MIT` matches here are *limits*, *submit*, *emits*. Measured before
#: the anchor went in -- `\bdsw` has zero matches across `site/` and `tools/`, so the
#: anchor costs nothing today and stops a false positive later.
UPSTREAM = re.compile(r"\bdsw|deepseek", re.IGNORECASE)


class SiteBrandBoundaryTests(unittest.TestCase):
    def test_no_shipped_page_names_the_vendor(self):
        """Every page a visitor can load, except the attribution page."""
        offenders = {}
        for page in sorted(SITE.glob("*.html")):
            if page.name in ATTRIBUTION_PAGES:
                continue
            hits = [
                f"{page.name}:{n}"
                for n, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1)
                if VENDOR.search(line)
            ]
            if hits:
                offenders[page.name] = hits
        self.assertEqual(
            offenders,
            {},
            "the vendor name is still on a visitor-facing page; edit the generator that "
            "emits it, never site/*.html directly",
        )

    def test_the_generators_do_not_emit_it(self):
        """Fixing the HTML without fixing its source lasts until the next build."""
        offenders = {}
        for rel in GENERATORS:
            path = REPO / rel
            hits = [
                f"{rel}:{n}"
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if VENDOR.search(line)
            ]
            if hits:
                offenders[rel] = hits
        self.assertEqual(offenders, {}, "a generator still writes the vendor name into site/")

    def test_credits_still_carries_the_bsd_notice(self):
        """The licence condition. This test failing means we are out of compliance.

        Asserted positively and on purpose: every other test here removes the name, and
        a sweep that was slightly too broad would satisfy all of them while quietly
        stripping the one instance BSD-3-Clause actually requires us to keep.
        """
        credits = (SITE / "credits.html").read_text(encoding="utf-8")
        self.assertIn("SymPy", credits, "the attribution was removed from credits.html")
        self.assertIn("BSD-3-Clause", credits, "the licence name was removed from credits.html")


class EngineMessageTests(unittest.TestCase):
    """Strings the engine hands back, read from the source rather than provoked.

    `note` and the `RavenCalcError` text are rendered into the readout, so every one of
    them is visitor-facing. Reaching them all at runtime would mean computing an integral
    with no closed form and an unsolvable quintic -- both are genuinely expensive in
    seconds, and a brand check has no business putting that in a suite that runs on every
    commit. The first draft of this file did exactly that and had to be killed by hand.

    So the strings are read out of the module instead. Docstrings and comments are
    excluded on purpose: the engine's internal prose may name what it imports, and it
    should, because that is what the code actually does. Only literals that can travel to
    a caller are in scope.
    """

    def test_no_user_facing_literal_in_the_engine_names_the_vendor(self):
        import ast

        source = (REPO / "backend/ravencalc/ravencalc.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        docstrings.add(id(first.value))

        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                if VENDOR.search(node.value):
                    offenders.append(f"ravencalc.py:{node.lineno}: {node.value!r}")

        self.assertEqual(
            offenders,
            [],
            "these reach the browser as the `note` or error line of the readout",
        )


class PublicApiTextTests(unittest.TestCase):
    """`api.py` publishes two strings that a visitor reads without opening a page.

    Read as source and never imported -- importing it starts a process that owns the GPU
    lease, which is why every other suite in this directory reads it the same way.

    Its comments and module docstring still name the library, and that is correct: they
    describe what the code imports, to a reader who is looking at the import. Only the
    two strings that leave the box are in scope here.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = (REPO / "backend/server.py").read_text(encoding="utf-8")

    def test_rack_unit_specs_do_not_name_the_vendor(self):
        """`spec=` is rendered into the rack unit by `/api/status` on the front page."""
        specs = re.findall(r'spec="([^"]*)"', self.source)
        self.assertTrue(specs, "no spec= values found -- has the rack been restructured?")
        offenders = [s for s in specs if VENDOR.search(s)]
        self.assertEqual(offenders, [], "a rack unit still shows the vendor name")

    def test_the_openapi_description_does_not_name_the_vendor(self):
        """Served at /docs, which is public.

        The description is assembled from adjacent string literals, so this looks for the
        sentence rather than one literal.
        """
        marker = "**RavenCalc** is"
        self.assertIn(marker, self.source, "the RavenCalc sentence moved; re-point this test")
        start = self.source.index(marker)
        self.assertNotRegex(
            self.source[start : start + 200],
            VENDOR,
            "the OpenAPI description at /docs still names the vendor",
        )


class RenderedResponseFieldTests(unittest.TestCase):
    """What the readout prints, which is not what `site/*.html` contains.

    `build_pages.py` renders `r.note` and `r.engine` into the page, so these strings are
    as visitor-facing as any heading -- they were simply invisible to a grep of the HTML.
    """

    @classmethod
    def setUpClass(cls):
        from ravencalc.apps import ravencalc

        cls.ravencalc = ravencalc

    def _run(self, **doc):
        return self.ravencalc.run_request(doc)

    def test_the_engine_line_does_not_name_the_vendor(self):
        result = self._run(operation="differentiate", expression="x**2", variable="x")
        self.assertNotRegex(
            result["engine"],
            VENDOR,
            "the readout prints this after every calculation -- see the `eng` line",
        )

    def test_the_engine_line_still_reports_a_real_version(self):
        """The name goes; the provenance does not.

        A bare product name here would be a downgrade on a site whose whole argument is
        that its numbers are real, so the symbolic core's actual version is still
        reported -- it is simply no longer labelled with the vendor's name. It must not
        be presented as *RavenCalc's* version, because that would name a release that
        does not exist.
        """
        result = self._run(operation="differentiate", expression="x**2", variable="x")
        self.assertIn("RavenCalc", result["engine"])
        self.assertRegex(
            result["engine"],
            r"\d+\.\d+",
            "the version was dropped along with the name; keep the measurement",
        )

    def test_error_messages_do_not_name_the_vendor(self):
        """Raised text reaches the user as the readout's error line."""
        with self.assertRaises(self.ravencalc.RavenCalcError) as caught:
            self._run(operation="integrate", expression="))(", variable="x")
        self.assertNotRegex(str(caught.exception), VENDOR)


class NoUpstreamIdentifiersTests(unittest.TestCase):
    """#91 ports a competitor's design tokens. Their names must not come with them.

    Task #74 states the reason for putting this here rather than in #91: *"a task that
    renames things should not also be the task that certifies the renaming"*. #91 is free
    to lift every value in that stylesheet -- a colour ladder is not copyrightable
    expression and the look is what Garrett asked for. What it may not do is carry
    `--dsw-static-deepseek-450` across, because a variable name is shipped verbatim: CSS
    and JS are served unminified from this box, so an identifier in an asset is as public
    as a heading.

    **The scope here is deliberately wider than #74's two declared checks, and the gap
    between them was real, not hypothetical.** Those checks are
    `ngrep dsw- -- site/symoneural.css` and `ngrep deepseek -- site/ui.js`: one token per
    file, and each file checked for the token it happened not to contain. Both were green
    while `site/symoneural.css` named the upstream twice. That is the same failure this
    task already recorded once -- `ngrep SymPy -- site/ravencalc.html` covered one page of
    fifteen and fixing that one page flipped it green while thirteen others still said it.
    So this scans **every** served asset for **both** tokens, and the generators too,
    because a page fixed by hand is undone by the next build.

    Comments are in scope on purpose, and that is where the two live hits were. `site/` is
    served as-is; a `/* ... */` block is not private just because it is not rendered.
    """

    #: Everything a visitor can fetch. HTML is included although the task names only CSS
    #: and JS: inline `<style>` and `<script>` is exactly where a ported token lands, and
    #: a scope that stops one file short is the failure mode above.
    SERVED = ("*.css", "*.js", "*.html")

    def _scan(self, paths):
        offenders = {}
        for path in paths:
            hits = [
                f"{path.name}:{n}: {line.strip()[:90]}"
                for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
                if UPSTREAM.search(line)
            ]
            if hits:
                offenders[path.name] = hits
        return offenders

    def test_no_served_asset_carries_an_upstream_identifier(self):
        paths = sorted({p for pattern in self.SERVED for p in SITE.glob(pattern)})
        self.assertTrue(paths, "no served assets found -- has site/ moved?")
        self.assertEqual(
            self._scan(paths),
            {},
            "a served asset names the upstream the design tokens came from. CSS and JS "
            "are served unminified, so this is public text -- rename the identifier, and "
            "inside a quotation use a bracketed substitution rather than deleting a word, "
            "which would silently falsify the quote",
        )

    def test_no_generator_writes_one(self):
        """Editing `site/` by hand lasts exactly until somebody runs the build."""
        self.assertEqual(
            self._scan(sorted((REPO / "tools").glob("build_*.py"))),
            {},
            "a generator emits an upstream identifier into site/",
        )

    def test_the_pattern_would_actually_catch_the_thing_it_is_for(self):
        """A guard matching nothing looks identical to a guard that is satisfied.

        Both of the above assert an empty dict, and an empty dict is what a broken regex
        returns too. This pins the pattern against the real variable name from the
        upstream stylesheet and against the anchor's two edges, so the day someone
        loosens `\\bdsw` to `dsw` -- or tightens it into matching nothing -- a test says
        so instead of the suite staying quietly green.
        """
        self.assertRegex("--dsw-static-deepseek-450: #eee;", UPSTREAM)
        self.assertRegex("/* ported from the DeepSeek harness */", UPSTREAM)
        self.assertRegex("var dswToken = 1;", UPSTREAM)
        self.assertNotRegex(".widsworth{color:red}", UPSTREAM)
        self.assertNotRegex(".rack-unit{--gap:4px}", UPSTREAM)

    def test_openapi_schema_does_not_leak_upstream_cli_names(self):
        """sd-cli survives in internal comments in api.py, which is fine, but it must not leak into the public OpenAPI schema Fields."""
        import ast

        api_source = (REPO / "backend/server.py").read_text(encoding="utf-8")
        tree = ast.parse(api_source)

        offenders = []
        for node in ast.walk(tree):
            # Target Field(..., description="...") assignments
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Field":
                for kw in node.keywords:
                    if kw.arg == "description" and isinstance(kw.value, ast.Constant):
                        if "sd-cli" in str(kw.value.value).lower():
                            offenders.append(kw.value.value)

        self.assertEqual(
            offenders,
            [],
            "An upstream CLI name (sd-cli) leaked into a public OpenAPI Field description in api.py"
        )


if __name__ == "__main__":
    unittest.main()
