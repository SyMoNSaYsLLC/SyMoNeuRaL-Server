"""Every page path `api.py` owns must be delegated to it by `ops/Caddyfile`, or Caddy 404s it.

Caddy's last block is `handle { file_server }`. Any path that reaches it is looked up in
`/var/www/symoneural` and answered from disk -- **without ever asking the API**. So a route
that exists in `api.py` and has no matching file in the webroot is dead code on the public
origin, however perfectly it answers on `127.0.0.1:8800`.

That defect has now shipped four separate times, once per surface, and each was found in
production rather than by a test:

  * `/overview /livestack /controlboard /receipts` -- the Caddyfile's own comment records it:
    *"That is exactly what happened when they were first deployed."*
  * `/studio` -- same, and `/studio.js` loaded off the webroot while the page did not.
  * `/exp` -- added with its own block only because @sections had written the lesson down.
  * `/tuner.html` and `/tuner-watch.html` -- **found 2026-08-20, and the interesting one.**
    Its delegation was missing from the day the redirect was written, but the retired files
    were still sitting in the webroot, so `file_server` answered them with stale 200s and
    everything looked healthy. The first unattended `deploy.sh --prune` deleted both, and the
    paths went from stale-200 straight to hard-404. `api.py`'s comment states the stake:
    these two get a redirect precisely because *"a bookmark is permanent"* and, unlike a
    stale cached page, a dead bookmark *"does NOT resolve itself on a reload"*.

The last one is why this test reads the webroot rule rather than a list of known paths: the
bug was latent for as long as a file happened to mask it, and no amount of curling the site
would have shown it.

## Why this cannot be a browser test

`tests/frontend.mjs` is normally run against a spare-port API, where FastAPI answers every one
of these paths directly and **this entire block of Caddy config is not exercised**. The
Caddyfile says so twice, in @sections and again in @studio: *"against localhost the API
answers directly and this block is not exercised at all."* A green browser suite is not
evidence about delegation. Neither is `curl 127.0.0.1:8800`, which was the mistake that let
the tuner 404 be reported as fixed -- the API had always answered it; Caddy had never asked.

So this asserts on the two files against each other, which is checkable without a running
Caddy, without root, and without the site being deployed.

Nothing here imports `api.py` -- it is the serving module, and importing it builds every rate
limiter, resolves the GPU governor and mounts `site/`. It is read as text, the same way
`test_rack_probes.py` and `test_deploy_routes.py` read it.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys
import tempfile
import unittest
import unittest.mock

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
API = REPO / "backend" / "server.py"
CADDYFILE = REPO / "ops" / "Caddyfile"
SITE = REPO / "site"


def _api_page_paths() -> set[str]:
    """Paths `api.py` serves that a visitor types, so `/api/*` and `/local/*` are excluded.

    Three declaration forms, and the second is the reason this is not a one-line regex:
    `SECTION_PAGES` is registered in a `for` loop at the bottom of `api.py`, so a decorator-
    only scan silently misses all four section pages -- the very paths whose delegation block
    is the oldest one in the Caddyfile.

    Full-line `#` comments are dropped before the scan, and that is not a tidiness measure.
    This ran over the raw text until 2026-08-21, when a comment in `api.py` explaining to the
    next person *which* decorator form these parsers read mentioned the pattern by name -- and
    the extractor duly reported a page path called `/literal` that no route serves and no
    Caddy block ever will. A guard that invents work is the *"check that cries wolf"*
    `scripts/deploy.sh` warns about in its own comment, and this file's whole argument is that
    a delegation failure is easy to miss; it stops being easy to miss only while every red
    line here is real.

    Dropping whole-comment lines and not every `#` is deliberate. A `#` inside a string
    literal is not a comment, and stripping from the first one would silently truncate any
    line containing a fragment identifier -- which is the same class of bug in the opposite
    direction, and harder to see.
    """
    src = "\n".join(
        "" if line.lstrip().startswith("#") else line
        for line in API.read_text().splitlines()
    )
    paths = {m.group(1) for m in
             re.finditer(r'@app\.(?:get|post)\(\s*"(/[^"{]*)"', src)}

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "SECTION_PAGES" in names:
            # keys are slugs -- the route is the slug with a leading slash
            paths |= {f"/{k.value}" for k in node.value.keys}
        if "LIVESTACK_PAGES" in names:
            # Keys are application names, and each one is registered at BOTH spellings by
            # the loop in api.py. Emitting only `/livestack/<name>` here would leave the
            # hyphenated half undelegated and unseen -- a page answering perfectly on
            # 127.0.0.1:8800 and 404ing at the address Garrett actually types, which is the
            # exact defect this whole file exists to catch, hiding inside the fix for it.
            paths |= {f"/livestack/{k.value}" for k in node.value.keys}
            paths |= {f"/live-stack/{k.value}" for k in node.value.keys}
        if "_RETIRED_PAGES" in names:
            # keys are already full paths
            paths |= {k.value for k in node.value.keys}

    return {p for p in paths
            if not p.startswith("/api") and not p.startswith("/local")}


def _caddy_matchers() -> tuple[set[str], set[str]]:
    """(exact paths, prefixes) that Caddy hands to the API.

    Two forms are in use and both count: a named matcher (`@exp path /exp`) and an inline
    one (`handle /docs* { ... }`). A trailing `*` makes a prefix.
    """
    exact: set[str] = set()
    prefix: set[str] = set()
    for line in CADDYFILE.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        m = re.match(r"@\w+\s+path\s+(.+)$", line) or re.match(r"handle\s+(/\S*)\s*\{", line)
        if not m:
            continue
        for tok in m.group(1).replace("{", " ").split():
            if not tok.startswith("/"):
                continue
            (prefix if tok.endswith("*") else exact).add(tok.rstrip("*") or "/")
    return exact, prefix


def _is_delegated(path: str) -> bool:
    exact, prefix = _caddy_matchers()
    return path in exact or any(path.startswith(p) for p in prefix)


def _shadowed_by_a_real_file(path: str) -> bool:
    """True when `file_server` would find something at this exact webroot path anyway.

    Tested against `site/`, which is what `deploy.sh` publishes -- the webroot is not readable
    without root and would make this test depend on a deploy having run.

    `/` is deliberately never shadowed. A bare `/` does resolve, to `index.html`, which is the
    whole problem: `api.py` redirects `/` to `/overview` and the Caddyfile's own comment says
    that without an explicit exact match *"the redirect route in api.py is dead code."*
    Serving something is not the same as serving the right thing.
    """
    if path == "/":
        return False
    return (SITE / path.lstrip("/")).is_file()


class CaddyDelegationTests(unittest.TestCase):

    def test_the_extraction_found_the_forms_that_are_easy_to_miss(self):
        """The vacuity guard. Every assertion below passes against an empty set, and this repo
        has already retired checks that scored green on an empty file."""
        paths = _api_page_paths()
        self.assertIn("/studio", paths, "decorator form not parsed out of api.py")
        self.assertIn("/overview", paths, "SECTION_PAGES loop not parsed -- see the docstring")
        self.assertIn("/tuner.html", paths, "_RETIRED_PAGES not parsed out of api.py")
        exact, prefix = _caddy_matchers()
        self.assertTrue(exact and prefix, "no matchers parsed out of ops/Caddyfile")

    def test_both_spellings_of_every_livestack_page_are_extracted(self):
        """#81's registration form, asserted by shape rather than by counting.

        `LIVESTACK_PAGES` is the third declaration form in `api.py` and the first that turns
        ONE dict entry into TWO routes. The assertion above would stay green if this parser
        emitted `/livestack/image` and silently dropped `/live-stack/image` -- the set is
        non-empty either way, and the invariant below would then never ask about the half
        that was missing.

        That is not a hypothetical shape of failure in this repo; it is a recorded one.
        `apps/test_deploy_routes.py` carries the same guard for the same reason, written
        after its vacuity check passed on a set of three routes and four hrefs that
        contained no two-segment path at all, while `/livestack/live` was undeployable.

        Read off the dict rather than hardcoded, so it keeps testing the rule as #81 grows
        to the rest of the rack instead of testing whichever page happened to be first."""
        src = "\n".join(
            "" if line.lstrip().startswith("#") else line
            for line in API.read_text().splitlines()
        )
        names: list[str] = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "LIVESTACK_PAGES"
                    for t in node.targets):
                names = [k.value for k in node.value.keys]
        self.assertTrue(names, "LIVESTACK_PAGES not found in api.py, or it is empty")

        paths = _api_page_paths()
        for name in names:
            with self.subTest(name=name):
                self.assertIn(f"/livestack/{name}", paths)
                self.assertIn(f"/live-stack/{name}", paths,
                              "the hyphenated spelling is registered by api.py's loop but "
                              "this parser did not emit it -- it would go undelegated and "
                              "404 at the address Garrett types, with this suite green")

    def test_a_commented_out_route_is_not_reported_as_a_page(self):
        """The 2026-08-21 false positive, pinned so the comment-stripping cannot be dropped.

        `_api_page_paths` scanned raw text, so a `#` comment in `api.py` that merely *named*
        the decorator form these parsers read produced a page path called `/literal` --
        stranded, undeliverable, and completely fictional. It is the mirror of every other
        bug this file records: those were real routes the guard could not see, this was a
        route that did not exist and the guard could not stop seeing. Both end with somebody
        deciding a red line here does not mean anything.

        Asserted on a synthetic source rather than on `api.py`, so it keeps testing the rule
        after the comment that caused it is reworded away."""
        src = ('# @app.get("/ghost-in-a-comment")\n'
               '@app.get("/genuinely-served")\n'
               'async def real(): ...\n')
        tmp = pathlib.Path(self.enterContext(tempfile.TemporaryDirectory())) / "api.py"
        tmp.write_text(src)
        with unittest.mock.patch.object(sys.modules[__name__], "API", tmp):
            found = _api_page_paths()
        self.assertIn("/genuinely-served", found, "the decorator scan stopped working")
        self.assertNotIn("/ghost-in-a-comment", found,
                         "a path named inside a # comment was reported as a served route")

    def test_every_api_page_path_reaches_the_api(self):
        """The invariant. A path api.py serves, with no file to mask it, must be delegated."""
        stranded = sorted(p for p in _api_page_paths()
                          if not _is_delegated(p) and not _shadowed_by_a_real_file(p))
        self.assertEqual(stranded, [], (
            f"backend/server.py serves {stranded}, ops/Caddyfile does not delegate them, and no "
            "file in site/ answers them. Caddy's final `handle {{ file_server }}` will 404 "
            "every one WITHOUT asking the API -- while 127.0.0.1:8800 answers them perfectly. "
            "Add a matcher block beside @studio/@exp."))

    def test_the_retired_bookmarks_are_delegated(self):
        """The 2026-08-20 regression itself, pinned by name.

        Covered by the invariant above, and written out separately anyway: this pair was
        masked for weeks by two stale files, so it is the case most likely to be re-broken by
        someone reasoning about which paths *look* like they need a block."""
        for path in ("/tuner.html", "/tuner-watch.html"):
            with self.subTest(path=path):
                self.assertFalse(_shadowed_by_a_real_file(path),
                                 f"site/{path.lstrip('/')} is back -- the redirect is shadowed")
                self.assertTrue(_is_delegated(path))

    def test_the_matchers_do_not_swallow_the_static_site(self):
        """Coverage would be vacuous if the extraction over-matched.

        These are ordinary files Caddy must keep serving off disk; if the parser reports them
        delegated, `test_every_api_page_path_reaches_the_api` proves nothing."""
        for path in ("/symoneural.css", "/ui.js", "/streamer.html", "/art-1.png"):
            with self.subTest(path=path):
                self.assertFalse(_is_delegated(path),
                                 f"{path} parsed as delegated to the API; it is a static file")


if __name__ == "__main__":
    unittest.main()


class InstallCaddyCannotEvictTheFirstPartyRuntime(unittest.TestCase):
    """`scripts/install-caddy.sh` predates `symoneural-web` and still enables stock Caddy.

    `symoneural-web.service` declares `Conflicts=caddy.service caddy-api.service` because two
    processes cannot own :80 and :443. `Conflicts=` is BIDIRECTIONAL, so `systemctl restart
    caddy` does not fail against a running symoneural-web -- systemd stops symoneural-web to
    make room. Re-running the installer on this box would take symoneural.com down and replace
    the first-party TLS runtime with stock Caddy, which is the exact opposite of the script's
    own "safe to re-run" claim.

    The fix is a refusal rather than deleting the enable, because a host that genuinely runs
    stock Caddy still needs the installer. These assertions pin the refusal in place.
    """

    SCRIPT = REPO / "scripts" / "install-caddy.sh"
    UNIT = REPO / "ops" / "symoneural-web.service"

    def test_the_conflicts_declaration_that_makes_this_dangerous_still_exists(self):
        """If Conflicts= is ever dropped, the guard below is arguing about nothing and the
        reasoning in both files needs re-deriving rather than silently passing."""
        unit = self.UNIT.read_text()
        self.assertRegex(unit, r"(?m)^Conflicts=.*caddy\.service",
                         "symoneural-web no longer declares Conflicts=caddy.service")

    def test_the_installer_refuses_before_it_enables_caddy(self):
        """Order is the whole assertion. A guard placed AFTER `systemctl enable caddy` would
        read as protection and provide none."""
        src = self.SCRIPT.read_text()
        # The COMMAND, anchored to start-of-line, not the string. The header comment explains
        # why the enable was kept rather than deleted and therefore quotes it verbatim -- a
        # plain `find` matches that prose, which sits above the guard and inverts this test.
        m = re.search(r"(?m)^systemctl enable caddy\s*$", src)
        self.assertIsNotNone(m, "the enable line is gone; re-derive this test")
        enable = m.start()
        guard = src.find("REFUSED: symoneural-web.service is the web server on this host.")
        self.assertNotEqual(guard, -1, "the first-party-runtime refusal is gone")
        self.assertLess(guard, enable,
                        "the refusal must come before Caddy is enabled, not after")

    def test_the_refusal_checks_enabled_or_active_not_just_active(self):
        """Either state means this host was cut over. Enabled-but-stopped is a box mid-reboot;
        active-but-disabled is one started by hand. Checking only `is-active` would let the
        installer evict the runtime on a machine that happened to be rebooting."""
        src = self.SCRIPT.read_text()
        self.assertIn("is-enabled --quiet symoneural-web", src)
        self.assertIn("is-active  --quiet symoneural-web", src)
