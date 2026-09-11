"""`scripts/deploy.sh`'s reference check must not report a working route as a missing file.

The check walks every local asset reference in the published tree and asserts the file is on
disk. Routes FastAPI serves through the proxy are not files and never will be, so `is_route()`
exempts them -- and the script's own comment states the stake: *"a check that cries wolf is
worse than no check, because the next real failure gets ignored."*

`studio` and `exp` were missing from that list, and the consequence was not cosmetic. Measured
2026-08-20: a deploy reported `MISSING exp` and `MISSING studio` and **exited non-zero**, while
both answered 200 on the running service. `ops/units/symoneural-deploy.service` deliberately carries
no `SuccessExitStatus`, so once that unit is armed a boot-time deploy goes red every single
boot -- for two pages that are working. That is the state `systemctl --failed` is supposed to
mean something in.

## Why this is a test and not just a longer allowlist

The allowlist is the kind of thing that rots silently: a surface lands, `api.py` grows a route,
nobody touches this shell script, and the next deploy fails for a page that works. So the test
below does not hardcode a blessed list -- it reads the extensionless `@app.get` routes out of
`api.py` and requires the script to know about every one that a page actually links to. A new
surface added the ordinary way makes this go red, which is the cheapest possible place to find
out.

The opposite failure is guarded too, and matters just as much: an allowlist that over-matches
stops catching genuinely absent files. `studio.js` and `studio-64.png` must still be checked
against the disk, and `livestack.html` must still be checked even though `livestack` is a
route. That asymmetry is deliberate and `deploy.sh` documents it.

Nothing here imports `api.py` -- it is the serving module, and importing it builds every rate
limiter, resolves the GPU governor and mounts `site/`. It is read as text, the same way
`test_rack_probes.py` reads it.
"""
from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import unittest

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
DEPLOY = REPO / "scripts" / "deploy.sh"
API = REPO / "backend" / "server.py"
INDEX = REPO / "site" / "index.html"


def _is_route(ref: str) -> bool:
    """Run deploy.sh's own `is_route()` against one reference.

    The function is extracted and sourced rather than reimplemented in Python. A copy of the
    case statement here would be a second thing to keep in step, and it would keep passing
    after somebody edited the shell -- testing the copy, not the script.
    """
    body = re.search(r"^is_route\(\) \{.*?^\}", DEPLOY.read_text(), re.M | re.S)
    assert body, "is_route() not found in deploy.sh -- it was renamed, not deleted; fix this"
    out = subprocess.run(
        ["bash", "-c", f'{body.group(0)}\nif is_route "$1"; then echo route; else echo file; fi',
         "_", ref],
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip() == "route"


def _extensionless_page_routes() -> set[str]:
    r"""`@app.get("/name")` and `@app.get("/name/child")` paths in api.py: no dot, no parameter.

    `[\w/-]*` rather than `[\w-]*`, and that one character is the whole point. This pattern
    matched ONE path segment until 2026-08-21, and `/livestack/live` -- #96's page, and this
    repo's first two-segment page route -- was therefore never parsed out of `api.py` at all.
    So it never entered the intersection below, the assertion that exists to catch exactly
    this passed on an empty contribution, and the deploy it was written to protect exited 1
    with `MISSING livestack/live` for a page answering 200.

    That is this file's own docstring coming true: *"the allowlist is the kind of thing that
    rots silently."* The allowlist did rot, and the test guarding it rotted the same day, for
    the adjacent reason -- the guard encoded an assumption (one segment) that the thing it
    guarded did not share. A vacuity guard on the whole set cannot see a hole in its shape;
    `test_a_multi_segment_route_is_parsed_at_all` below is the narrower guard that can.

    Parameterised routes still fall out on their own: `{` is not in the class. `api/...` paths
    are now parsed too, and harmlessly -- nothing links them, so they never reach the
    intersection, and `is_route()` exempts `api/*` anyway.

    `LIVESTACK_PAGES` is read as well, and a decorator-only scan cannot see it: #81 registers
    every application page in a `for` loop, at both spellings, so a page added the ordinary
    way from 2026-08-22 onward contributes NO decorator to match. That is the shape of hole
    this function has already had once -- one path segment, `/livestack/live`, `MISSING` on a
    deploy of a page answering 200 -- and the second time it would be worse, because the
    allowlist below and this parser would be blind to the same entries in the same way, so
    the intersection stays empty and `test_every_linked_api_route_is_known_to_the_deploy_check`
    reports nothing wrong.
    """
    src = API.read_text()
    routes = {m.group(1) for m in
              re.finditer(r'@app\.get\(\s*"/([A-Za-z][\w/-]*)"', src)
              if "." not in m.group(1)}

    # Whole-line `#` comments dropped before the AST parse for the reason
    # `test_caddy_delegation.py` documents at length: a comment that merely NAMES the
    # declaration form these parsers read once produced a wholly fictional page path.
    tree = ast.parse("\n".join(
        "" if line.lstrip().startswith("#") else line for line in src.splitlines()))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == "LIVESTACK_PAGES" for t in node.targets):
            for key in node.value.keys:
                routes.add(f"livestack/{key.value}")
                routes.add(f"live-stack/{key.value}")

    # A THIRD declaration form, and the one this parser was blind to until 2026-08-29: a page
    # route declared on an APPLICATION'S OWN ROUTER rather than in api.py at all.
    #
    # `/demo/dispatchos` is `@ui_router.get("/demo/dispatchos")` in `apps/dispatchos/routes.py`,
    # mounted with `app.include_router(dispatchos.ui_router)` and no prefix. Nothing above can
    # see it: the regex reads `@app.get` in api.py and the AST walk reads `LIVESTACK_PAGES`.
    # So when `dispatchos` was written into ROSTER.md and the generated rack fallback grew an
    # `<a class="unit" href="/demo/dispatchos">`, this file's intersection stayed empty and
    # `test_every_linked_api_route_is_known_to_the_deploy_check` passed -- while `deploy.sh`
    # would have reported `MISSING demo/dispatchos` and exited 1 on a page answering 200.
    #
    # That is the third time in this file's history the parser and the allowlist have been
    # blind to the same entry in the same way, which is the failure its own docstring warns
    # about: a guard that encodes an assumption the thing it guards does not share. One
    # segment was the assumption in 2026-08-21; "declared in api.py" was the assumption here.
    #
    # Only NO-PREFIX routers are read. A router included with a prefix declares its paths
    # relative to it, and reconstructing the mounted path means matching every
    # `include_router(module.name, prefix=...)` back to the file defining `name` -- a second,
    # weaker copy of the route table, which `apps/route_matrix.py` argues at length against
    # building. Page routes are mounted without a prefix; api routes are not, and `is_route()`
    # exempts `api/*` regardless. The narrow scan answers the narrow question.
    for routes_py in sorted((APPS := API.parent / "apps").rglob("routes.py")):
        text = "\n".join(
            "" if line.lstrip().startswith("#") else line
            for line in routes_py.read_text(encoding="utf-8").splitlines())
        for m in re.finditer(
                r'@(\w+)\.get\(\s*"/([A-Za-z][\w/-]*)"', text):
            router, path = m.group(1), m.group(2)
            if "." in path:
                continue
            # Mounted without a prefix? Only then is the declared literal the served path.
            if re.search(rf"include_router\(\s*\w+\.{re.escape(router)}\s*\)",
                         API.read_text()):
                routes.add(path)
    return routes


def _livestack_names() -> list[str]:
    """The keys of `LIVESTACK_PAGES` in api.py, and nothing else.

    Deliberately separate from `_extensionless_page_routes()` above, which returns every
    page route from every declaration form. The two are NOT interchangeable and treating
    them as such is a real red-on-healthy-code failure this file has already produced: see
    `test_every_livestack_page_is_not_reported_missing_at_either_spelling`.
    """
    src = "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in API.read_text().splitlines()
    )
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(t, ast.Name) and t.id == "LIVESTACK_PAGES" for t in node.targets):
            return [k.value for k in node.value.keys]
    return []


def _linked_extensionless() -> set[str]:
    r"""Extensionless local hrefs on the front page -- what the check would actually look up.

    Multi-segment for the same reason as above: `site/index.html` links `/livestack/live`, and
    with `[\w-]*` this returned `livestack` only, so the link the deploy actually chokes on
    was invisible on both sides of the comparison.
    """
    return {m.group(1) for m in
            re.finditer(r'href="/([A-Za-z][\w/-]*)"', INDEX.read_text())}


class ReferenceCheckTests(unittest.TestCase):

    def test_the_extraction_found_something_to_test(self):
        """The vacuity guard. Every assertion below passes against empty sets, and this repo has
        already retired checks that scored green on an empty file."""
        self.assertTrue(_extensionless_page_routes(), "no @app.get routes parsed out of api.py")
        self.assertTrue(_linked_extensionless(), "no extensionless hrefs parsed out of index.html")

    def test_a_multi_segment_route_is_parsed_at_all(self):
        """The shape guard, and the one that was missing.

        `test_the_extraction_found_something_to_test` above asserts both sets are non-empty,
        which they were -- three routes and four hrefs -- while containing no two-segment path
        on either side. A set can be non-empty and still be blind to a whole shape of input,
        and the assertion below is the cheap way to say so out loud rather than trusting a
        regex to keep matching something it was never written to match."""
        routes = _extensionless_page_routes()
        self.assertIn("livestack/live", routes,
                      "api.py serves /livestack/live but the parser did not find it -- the "
                      "route regex is back to matching a single path segment")
        self.assertIn("livestack/live", _linked_extensionless(),
                      "site/index.html links /livestack/live but the href regex did not "
                      "find it")

    def test_studio_and_exp_are_not_reported_missing(self):
        """The regression itself. Both were `MISSING` on a deploy where both answered 200."""
        self.assertTrue(_is_route("studio"))
        self.assertTrue(_is_route("exp"))

    def test_the_live_page_route_is_not_reported_missing(self):
        """#96's page, and the second time this allowlist has failed a working deploy.

        Measured 2026-08-21: `sudo ./scripts/deploy.sh` printed `MISSING livestack/live` and
        exited 1, while `/livestack/live` answered 200 on the running service, is
        `@app.get("/livestack/live", include_in_schema=False)` in `api.py`, and carries its own
        `@live path /livestack/live` matcher in `ops/Caddyfile`. Checked all three ways before
        the exemption was added, which is the discipline `deploy.sh`'s comment asks for."""
        self.assertTrue(_is_route("livestack/live"))

    def test_both_spellings_of_the_coder_page_are_not_reported_missing(self):
        r"""#87's page, and the first route in this repo whose FIRST segment carries a hyphen.

        `/live-stack/coder` is the address Garrett typed and `/livestack/coder` is the one
        every other application on the rack uses; api.py serves the same page at both and
        redirects neither. Neither is a file, so `is_route()` has to know both or the next
        deploy exits non-zero for a page answering 200 -- which is what this file records
        happening to studio, exp and livestack/live in turn.

        The hyphen is the part worth asserting rather than assuming: `_extensionless_page_routes`
        matches `[A-Za-z][\w/-]*`, and `\w` does not include `-`. It is in the class
        explicitly, and this is the first path that depends on it being there."""
        self.assertTrue(_is_route("live-stack/coder"))
        self.assertTrue(_is_route("livestack/coder"))
        routes = _extensionless_page_routes()
        self.assertIn("live-stack/coder", routes,
                      "api.py serves /live-stack/coder but the parser did not find it -- a "
                      "hyphen in the first path segment is no longer matched")
        self.assertIn("livestack/coder", routes)

    def test_every_livestack_page_is_not_reported_missing_at_either_spelling(self):
        """#81's pages, read off `LIVESTACK_PAGES` so this grows with the dict.

        The third time this allowlist has had to learn a route, and the first where the
        route is not written down as a literal anywhere -- so both halves are asserted: that
        the parser above SEES the dict, and that `deploy.sh` exempts what it sees. Either one
        alone passes while the deploy exits 1 for a page answering 200, which is the exact
        outcome recorded for studio, exp and livestack/live in turn.

        Hardcoding `image` here instead would test the page that happened to be migrated
        first and stop testing the rule the moment a second one lands.

        Read off the DICT, not off the route set by prefix. Filtering
        `_extensionless_page_routes()` for `livestack/` looked equivalent and is not: it
        also catches `livestack/live` and `livestack/coder`, which are literal decorators
        and not dict entries. `/livestack/live` is deliberately served at ONE spelling --
        #96 gave it no hyphenated twin -- so a prefix filter demanded a `/live-stack/live`
        that has never existed and went red on correct code. A test that fails on a healthy
        tree gets switched off, and then it protects nothing."""
        names = _livestack_names()
        self.assertTrue(names, "LIVESTACK_PAGES not parsed out of api.py -- see the "
                               "docstring of _extensionless_page_routes")
        routes = _extensionless_page_routes()
        for name in names:
            with self.subTest(name=name):
                self.assertIn(f"livestack/{name}", routes,
                              "api.py registers both spellings; the parser found neither")
                self.assertIn(f"live-stack/{name}", routes,
                              "api.py registers both spellings; the parser found only one")
                self.assertTrue(_is_route(f"livestack/{name}"),
                                f"deploy.sh reports livestack/{name} as a MISSING file")
                self.assertTrue(_is_route(f"live-stack/{name}"),
                                f"deploy.sh reports live-stack/{name} as a MISSING file")

    def test_every_application_answers_at_both_spellings(self):
        """#81's title, asserted as an invariant over ALL declaration forms.

        *"/livestack/<name> AND /live-stack/<name> for every application"*. The two tests
        above check the dict and the literals separately, and between them they let exactly
        this through: `/livestack/live` shipped at ONE spelling for two days, because it was
        born (#96) before `/live-stack/coder` (#87) established that the hyphenated form is
        served too, and nothing compared the two lists afterwards.

        The failure was invisible in the only way that matters -- `/livestack/live` answered
        200, its Caddy matcher was present, its deploy exemption was present, and every test
        in this file passed. A missing route is not a broken one. Nothing goes red; a
        visitor types the other spelling and gets a 404.

        `/live-stack/coder` leads for Coder and `/livestack/<name>` leads elsewhere, and
        this asserts nothing about which is canonical -- only that neither is missing."""
        routes = _extensionless_page_routes()
        pairs = {r.split("/", 1)[1] for r in routes if r.startswith("livestack/")}
        self.assertTrue(pairs, "no /livestack/<name> routes parsed out of api.py at all")
        missing = sorted(n for n in pairs if f"live-stack/{n}" not in routes)
        self.assertEqual(missing, [], (
            f"api.py serves /livestack/{{{','.join(missing)}}} but not the hyphenated "
            "spelling. #81 requires both for every application, and the half that is "
            "missing 404s silently -- there is no red line anywhere else for this."))
        for name in sorted(pairs):
            with self.subTest(name=name):
                self.assertTrue(_is_route(f"live-stack/{name}"),
                                f"deploy.sh reports live-stack/{name} as a MISSING file")

    def test_nothing_published_carries_the_hyphenated_spelling(self):
        """2026-08-22: one address in front of a person, two answering.

        Garrett: *"we need to get rid of live-stack i believe its only livestack"*. Taken
        as a publishing decision, not a routing one.

        NOT for the bookmark reason, and that correction is his: *"anyone holding that URL
        loses it -- the one failure CLAUDE.md says the site can't afford -- that is not
        true"*. It is not. `/live-stack/coder` landed 2026-08-20 on a surface whose reads
        are `/local/coder/*`, refused off-box by peer address, so there is no public
        audience holding it. `/tuner.html` and `/image.html` are what that argument is
        about; borrowing it here inflated a cheap decision into a principled one.

        The real reason the routes stay is smaller and checkable: this repo's own documents
        still name that spelling -- R-160, `apps/coder/SMOKE-surface.md`, #81's title -- so
        somebody reading them will type it, and answering costs one path in a matcher. If
        those documents are ever rewritten, deleting the routes becomes free and this test
        is the only thing that has to change with them.

        So the routes stay and `test_every_application_answers_at_both_spellings` still
        requires them; what is asserted HERE is that no page, no rack tile and no printed
        instruction shows it.

        This is the assertion that stops the decision rotting. Without it the hyphen comes
        back the first time somebody copies an old href, and nothing anywhere goes red --
        the page would work perfectly at an address the site said it would stop using.

        `site/*.html` is checked as well as the rack, because the rack tile is generated
        from `api.py` while the static pages are not, and only one of those two is covered
        by reading `api.py`."""
        rack_hrefs = re.findall(r'href="(/live-stack/[\w-]+)"', API.read_text())
        self.assertEqual(rack_hrefs, [], (
            f"api.py publishes {rack_hrefs} on the rack. The route may keep answering, but "
            "the tile must link /livestack/<name> -- that is the whole of the 2026-08-22 "
            "decision."))

        site = REPO / "site"
        offenders = sorted(
            f"{p.name}:{m}"
            for p in list(site.glob("*.html")) + list(site.glob("*.js"))
            for m in re.findall(r'["\'](?:https?://[^"\']*)?(/live-stack/[\w-]+)', p.read_text())
        )
        self.assertEqual(offenders, [], (
            f"these published files hand out the hyphenated spelling: {offenders}. It still "
            "answers, so nothing will look broken -- which is exactly why this is a test and "
            "not a convention."))

    def test_every_linked_api_route_is_known_to_the_deploy_check(self):
        """A new surface that api.py serves and a page links must not fail the next deploy."""
        unknown = sorted(r for r in _linked_extensionless() & _extensionless_page_routes()
                         if not _is_route(r))
        self.assertEqual(unknown, [], (
            f"scripts/deploy.sh reports {unknown} as MISSING files, but api.py serves them as "
            "routes and site/index.html links them. The next deploy will exit non-zero for a "
            "page that works. Add them to is_route()."))

    def test_the_allowlist_does_not_swallow_real_files(self):
        """An exemption that over-matches stops the check catching a genuinely absent asset.

        `livestack` is the documented asymmetry: the route is exempt, the file is not."""
        for ref in ("studio.html", "exp.html", "studio.js", "studio-64.png",
                    "livestack.html", "live.html", "live.css", "livestack/live.html",
                    "coder.html", "coder.js", "coder.css", "livestack/coder.html",
                    # #81's split. `livestack/image` is a route; these three are the files
                    # that route serves and references, and a missing one has to be
                    # reported. `image.css` and `image.js` are new as of #81 and are the
                    # first assets in this repo whose STEM matches a route name -- an
                    # exemption written as a prefix rather than an exact case would swallow
                    # all three and the check would stop protecting the page it was widened
                    # for.
                    "image.html", "image.js", "image.css", "livestack/image.html",
                    "nonesuch"):
            with self.subTest(ref=ref):
                self.assertFalse(_is_route(ref), f"{ref} is exempted; a missing one would pass")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    unittest.main()
