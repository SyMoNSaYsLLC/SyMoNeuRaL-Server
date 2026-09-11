"""The Coder surface: its two addresses, its prefix, and the route it must never grow.

`backend/coder/test_coder.py` tests the module -- the gates, the denylist, the path
containment. This file tests the **surface**: what `backend/server.py` mounts, what
`ops/Caddyfile` delegates, and what `site/coder.*` is allowed to contain. Those are three
files that have to agree, and every failure this repo has had here came from two of them
agreeing while the third did not.

Nothing here imports `api.py` -- it is the serving module, and importing it builds every rate
limiter, resolves the GPU governor and mounts `site/`. It is read as text, the same way
`test_rack_probes.py`, `test_deploy_routes.py` and `test_caddy_delegation.py` read it.

## The invariant this file exists for

`ops/Caddyfile` hands the whole `/api/*` subtree to the public internet, and the module behind
this page reads arbitrary workspace files and executes subprocesses. So the surface's reads
live at `/local/coder/*`, which matches no `handle` block and falls through to the static file
server, and there is no `/api/coder/...` route at all. `d275153` reached the same conclusion by
a different route -- a separate uvicorn app on :8801 -- and its commit message states the
constraint in one line: *"a /api/coder route is reachable from the internet the moment it
exists, and this module's feature is run a command on the server."* That design is not the one
that shipped; the conclusion it was built on is unchanged, and `test_the_public_api_has_no_coder_route`
is what keeps it true after somebody adds an endpoint in a hurry.

## Why a static read and not a request

A running server proves this instance is configured correctly right now. It cannot prove that
a clean checkout is, and the delegation half cannot be proved by a request at all: against
`127.0.0.1:8800` FastAPI answers every path directly and the whole Caddy config is not
exercised, which is the mistake that let a tuner 404 be reported as fixed. `SMOKE-surface.md`
beside this file carries the readings from a real run; this carries the rules.
"""
from __future__ import annotations

import pathlib
import re
import unittest

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
API = REPO / "backend" / "server.py"
CADDYFILE = REPO / "ops" / "Caddyfile"
SITE = REPO / "site"
PAGE = SITE / "coder.html"
PAGE_JS = SITE / "coder.js"
PAGE_CSS = SITE / "coder.css"
FRONTEND = REPO / "tests" / "frontend.mjs"

# Both spellings. `/live-stack/coder` is what Garrett typed in R-160 and leads;
# `/livestack/coder` is the shape every other application on the rack uses (#81).
PAGE_PATHS = ("/live-stack/coder", "/livestack/coder")


def _api_src() -> str:
    return API.read_text()


def _no_comments(src: str, *, css: bool = False, html: bool = False) -> str:
    """Source with its comments blanked out.

    Every one of the four assertions below was written as a plain substring test first, and
    all four went red on their own subject matter: the page explains *why* the token is not in
    `localStorage`, the stylesheet's header says *"No `text-overflow:ellipsis` anywhere in this
    file, ever"*, and `api.py`'s docstring says there is no `tools/build_coder.py`. Each one
    matched the sentence promising the thing it was checking for.

    That is the identical bug `apps/test_caddy_delegation.py` grew comment-stripping for on the
    same day, arriving from the other direction, and it is worth stating once: a guard that
    reads prose does not check the code, it checks the documentation -- and it fails hardest on
    a well-commented file, which is precisely the file you least want to discourage.
    """
    if html:
        src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    if css or html:
        src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    else:
        src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
        src = "\n".join(re.sub(r"//.*$", "", ln) for ln in src.splitlines())
    return src


def _py_no_comments(src: str) -> str:
    """Python source with full-line comments and triple-quoted blocks blanked."""
    src = re.sub(r'"""(?:.|\n)*?"""', ' ', src)
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in src.splitlines())


def _decorated_paths() -> set[str]:
    """`@app.get("/literal")` paths, with full-line comments dropped.

    The comment stripping matters for the same reason it does in
    `apps/test_caddy_delegation.py`, which grew it on 2026-08-21 after a comment that merely
    NAMED this form was extracted as a served route.
    """
    src = "\n".join("" if ln.lstrip().startswith("#") else ln
                    for ln in _api_src().splitlines())
    return {m.group(1) for m in re.finditer(r'@app\.(?:get|post)\(\s*"(/[^"{]*)"', src)}


class CoderSurfaceTests(unittest.TestCase):

    # ---- the extraction actually found something -------------------------------------

    def test_the_files_this_reads_are_all_present(self):
        """The vacuity guard. Every assertion below passes against an empty file, and this
        repo has already retired checks that scored green on one."""
        for f in (API, CADDYFILE, PAGE, PAGE_JS, PAGE_CSS, FRONTEND):
            with self.subTest(f=f.name):
                self.assertTrue(f.is_file(), f"{f} is missing")
                self.assertGreater(len(f.read_text().strip()), 200, f"{f} is a stub")
        self.assertIn("/studio", _decorated_paths(),
                      "the decorator scan found nothing it should have")

    # ---- the addresses ---------------------------------------------------------------

    def test_both_spellings_are_served_as_decorator_literals(self):
        """Not merely reachable -- reachable in the form the other two guards can parse.

        These were registered in a `for` loop over a tuple first. That works perfectly at
        runtime and is invisible to `apps/test_caddy_delegation.py` and
        `apps/test_deploy_routes.py`, both of which read `api.py` as TEXT looking for
        `@app.get("/literal")`. A loop would therefore have shipped a page that answers on
        127.0.0.1:8800 and 404s at the address he types, with both guards green -- the exact
        defect those guards exist for, walking straight past them.

        `SECTION_PAGES` is the precedent and the warning: it is registered in a loop and
        needed bespoke AST support in the delegation test to be seen at all."""
        found = _decorated_paths()
        for p in PAGE_PATHS:
            with self.subTest(path=p):
                self.assertIn(p, found,
                              f"{p} is not an @app.get literal in api.py; the delegation and "
                              "deploy guards cannot see it and will pass while it 404s")

    def test_neither_spelling_redirects_to_the_other(self):
        """One page at two addresses, and neither is canonical.

        A redirect would make the address in the operator's URL bar disagree with the address
        they typed, which is precisely the confusion two spellings already threaten. The
        retired `/tuner.html` pair gets a redirect for the opposite reason -- those names are
        dead and a bookmark is permanent -- and conflating the two cases is easy."""
        src = _api_src()
        for p in PAGE_PATHS:
            with self.subTest(path=p):
                self.assertNotRegex(
                    src, re.escape(p) + r'"[^)]*\)\s*\n\s*async def \w+[^\n]*\n(?:[^\n]*\n){0,12}?'
                                        r'\s*return RedirectResponse',
                    f"{p} answers with a redirect; both spellings serve the page directly")

    def test_the_page_route_is_delegated_by_caddy_at_both_spellings(self):
        """Covered by `apps/test_caddy_delegation.py`'s general invariant, and written out
        here by name anyway.

        That test reads the webroot rule and catches this as one of a set. This one names the
        two paths, so a future refactor of the extraction there cannot silently stop covering
        them -- the way `_extensionless_page_routes` stopped covering two-segment routes in
        `apps/test_deploy_routes.py` and nobody noticed until a deploy exited 1."""
        conf = "\n".join(ln.split("#", 1)[0] for ln in CADDYFILE.read_text().splitlines())
        for p in PAGE_PATHS:
            with self.subTest(path=p):
                self.assertRegex(conf, r"@\w+\s+path\s+[^\n]*" + re.escape(p) + r"(\s|$)",
                                 f"ops/Caddyfile does not delegate {p}; Caddy's final "
                                 "`handle {{ file_server }}` will 404 it WITHOUT asking the "
                                 "API, while 127.0.0.1:8800 answers it perfectly")

    # ---- the prefix, which is the whole safety case ----------------------------------

    def test_the_public_api_has_no_coder_route(self):
        """The invariant the entire design rests on, and the one worth being blunt about.

        `ops/Caddyfile` delegates the whole `/api/*` subtree to the public internet.
        `backend/coder/__init__.py` reads arbitrary workspace files and executes
        subprocesses. An `/api/coder/...` endpoint is remote file read on a public host the
        instant it exists -- not after it is misconfigured, and not only if the token leaks.

        There is no way to add one safely and this test does not care why somebody wanted to.
        If a future task genuinely needs it, this assertion is the conversation."""
        offenders = sorted(p for p in _decorated_paths() if p.startswith("/api/coder"))
        self.assertEqual(offenders, [], (
            f"api.py serves {offenders}. ops/Caddyfile hands all of /api/* to the internet "
            "and this module runs subprocesses. Use /local/coder/*, which Caddy does not "
            "delegate and _require_local refuses off-box."))

    def test_every_coder_read_is_behind_the_local_guard(self):
        """`/local/*` is not delegated, and the API does not trust that config file either.

        `_require_local` checks the socket peer AND refuses any `X-Forwarded-*` header, which
        is what a future `handle /local*` block would produce -- so these routes go dead
        rather than public if somebody adds one. A route that skipped the guard would be
        relying on the Caddyfile alone, which is one lock, not two."""
        src = _api_src()
        routes = re.findall(r'@app\.get\("(/local/coder/[^"]*)"[^)]*\)\s*\n'
                            r'async def (\w+)\(([^)]*)\)[^:]*:\n((?:(?!\n@app)(?!\nasync def).)*)',
                            src, re.S)
        self.assertTrue(routes, "no /local/coder routes parsed out of api.py")
        for path, fn, args, body in routes:
            with self.subTest(path=path):
                self.assertIn("request", args,
                              f"{fn} takes no Request, so it cannot check its peer")
                guarded = "_require_local(request)" in body or "_coder_read(request" in body
                self.assertTrue(guarded,
                                f"{path} does not reach _require_local; it would answer any "
                                "peer that got past Caddy")

    def test_the_page_talks_only_to_the_local_prefix(self):
        """The page half of the same rule. A single `/api/coder/` fetch here would be a
        request the browser makes to a path that must not exist -- harmless today because it
        404s, and a standing invitation to 'fix' it by adding the route."""
        js = _no_comments(PAGE_JS.read_text())
        self.assertNotIn("/api/coder", js,
                         "site/coder.js fetches /api/coder; the reads live at /local/coder")
        fetched = set(re.findall(r"['\"](/[a-z0-9/_-]+)[?'\"]", js))
        remote = sorted(p for p in fetched
                        if p.startswith("/api") or p.startswith("/local"))
        self.assertTrue(remote, "no endpoint literals parsed out of coder.js")
        for p in remote:
            with self.subTest(path=p):
                # `/local/coder` with no trailing slash is the mount's NAME -- the page
                # renders it in the read-only banner -- so the prefix is the test, not the
                # shape of a full endpoint path.
                self.assertTrue(p.startswith("/local/coder"),
                                f"coder.js talks to {p}, which is not the local mount")

    def test_the_token_never_reaches_the_browser(self):
        """R-174: a credential that has been displayed is spent.

        `coder.token_ok()` exists to stop a caller who arrived over a network, and these
        routes are already past a stricter test than that. A page that held the token would
        mean the token in a URL, in localStorage, or committed into this repository's own
        HTML. It is read from the server's environment, used in-process, and never sent.

        The env var name may appear in prose -- the page tells an operator what to set -- so
        this looks for the shapes that would carry a VALUE, not for the name."""
        for f in (PAGE, PAGE_JS):
            with self.subTest(f=f.name):
                raw = f.read_text()
                self.assertNotRegex(
                    _no_comments(raw, html=(f is PAGE)),
                    r"SYMONEURAL_CODER_TOKEN\s*[=:]\s*['\"][^'\"]+['\"]",
                    f"{f.name} appears to carry a token value")

                # The storage APIs are checked against SCRIPT, not against the document.
                #
                # Written as a substring test over the whole file first, and it went red on
                # `coder.html` -- whose visible prose explains that the token is NOT kept in
                # `localStorage`. That is not a comment, so stripping comments does not help;
                # it is the page telling the reader what it does not do. A guard that cannot
                # tell a promise from a breach reports the best-documented page as the
                # offender, which is the surest way to get the guard deleted.
                #
                # For the HTML that means inline script bodies and inline event handlers --
                # the only two places a page can execute anything -- and for the .js file it
                # means the code with its comments dropped.
                if f is PAGE:
                    code = "\n".join(re.findall(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                                                raw, re.S))
                    code += "\n".join(re.findall(r"\son\w+\s*=\s*\"([^\"]*)\"", raw))
                else:
                    code = _no_comments(raw)
                # BOTH spellings of the operator credential header. `X-Sym-Token` is the
                # legacy name and `X-Symoneural-Token` the current one; naming only the
                # legacy one is what `apps/test_credential_header.py`'s tripwire exists to
                # catch, and it caught this file -- the name was carried over from d275153's
                # design, which predates the rename. A page must carry neither.
                for bad in ("localStorage", "sessionStorage",
                            "X-Sym-Token", "X-Symoneural-Token"):
                    self.assertNotIn(bad.lower(), code.lower(),
                                     f"{f.name} executes {bad}; the token must not live in "
                                     "the page")

    # ---- what the page is ------------------------------------------------------------

    def test_the_page_is_static_html_with_its_js_and_css_beside_it(self):
        """#81, in his words: *"Make sure to update the applications to be static with js css
        and html"* -- corrected one minute after he first typed `json`.

        The `<script>` check is for a script with a BODY. `<script src=...></script>` is the
        structure this asks for; an inline block is the thing it asks against."""
        html = PAGE.read_text()
        self.assertIn('href="/coder.css', html, "the page does not load its own stylesheet")
        self.assertIn('src="/coder.js', html, "the page does not load its own script")
        inline = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>", html, re.S)
        bodies = [b for b in inline if b.strip()]
        self.assertEqual(bodies, [], "site/coder.html carries an inline <script> body")

    def test_no_ellipsis_rule_anywhere_in_the_page_or_its_stylesheet(self):
        """Barred sitewide by `.claude/CLAUDE.md`, and this is the page where it would cost
        the most: what it renders IS paths and refusal reasons. A trimmed
        `training/corpus.js…` is a file the operator cannot identify and a trimmed refusal is
        one they cannot act on. `layout changes must not drop data. **This includes CSS.**`"""
        for f in (PAGE, PAGE_CSS, PAGE_JS):
            src = _no_comments(f.read_text(), css=(f is PAGE_CSS), html=(f is PAGE))
            with self.subTest(f=f.name):
                # The declaration, not the word. `coder.css`'s header comment is a paragraph
                # about why there is no ellipsis rule in it, and a substring test fails on
                # exactly the file that documents the rule best.
                self.assertNotRegex(src, r"text-overflow\s*:\s*ellipsis",
                                    f"{f.name} contains an ellipsis rule; let it wrap")

    def test_the_page_declares_no_generator(self):
        """`site/coder.html` is hand-authored and tracked, like `site/live.html`.

        The 404 body in `api.py` sends the next person to `git checkout`, and it must not name
        a `tools/build_coder.py` that does not exist -- pointing at a missing generator is how
        somebody spends an afternoon looking for one."""
        self.assertFalse((REPO / "tools" / "build_coder.py").exists(),
                         "a generator appeared; the 404 text and this test both assume none")
        # `api.py`'s own docstring says, in words, that there is no such generator. Read the
        # code rather than the sentence, or this asserts that nobody explained themselves.
        self.assertNotIn("build_coder", _py_no_comments(_api_src()))

    # ---- the browser assertion this task is measured by ------------------------------

    def test_the_browser_suite_asserts_the_readings_are_on_the_first_screen(self):
        """#87's `coder-instrument-first` check, and the guard that it did not become vacuous.

        A file on disk satisfies `exists` and `grep` and says nothing about whether it has
        ever run -- `tests/live.mjs` sat unrunnable for a fortnight with a SyntaxError on line
        17 and every disk-read check green. So this asserts the assertion is really there AND
        that it measures AREA rather than height: #99's editor was 4% visible at 1440x1000
        while a height assertion passed, because `min(78vh,760px)` of a 1000px viewport really
        is 760px.

        `SMOKE-surface.md` beside this file records the run where it was deliberately broken
        and observed going red, which is the part no static check can stand in for."""
        src = FRONTEND.read_text()
        self.assertIn("coder-instrument-first", src,
                      "tests/frontend.mjs has no coder-instrument-first assertion")
        self.assertIn("cd-grid", src)
        self.assertRegex(src, r"innerWidth", "the check does not read the viewport at all")
        self.assertRegex(src, r"w \* h|width \* .*height",
                         "the check does not multiply out an area; a height assertion would "
                         "have passed throughout #99")
        self.assertIn("corpus.jsonl", src,
                      "nothing asserts the denied corpus is shown rather than hidden")


if __name__ == "__main__":
    unittest.main()
