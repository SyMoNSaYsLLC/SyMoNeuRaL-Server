"""The dashboard page and its API must agree. Checked against BOTH files, not against a memory.

`.claude/CLAUDE.md` names the failure this guards: #94 shipped a desktop client whose
eighteen checks went green over a chat surface that was dead on arrival, because every check
asked what was written on disk and none could ask whether the thing worked. `exists
site/dashboard.html` would pass over a page whose every element id had been renamed.

So these assert the three joins that actually break:

1. **every id the JS looks up exists in the HTML.** A renamed div does not throw at load --
   `document.getElementById` returns null and the section silently stays empty, which looks
   like "no data" rather than "broken page".
2. **every endpoint the JS fetches is a real route.** Same failure shape one layer out.
3. **the page sends no credential header.** NO API KEYS, 2026-09-11. A header nothing reads
   is not harmful, it is a lie about how the system works, and this page is the reference
   for how to call these routes.

None of this proves the page RENDERS. That needs a browser, and `docs/ops/MEASUREMENTS.md`
records that this host has none -- so the honest position is that these are joins, not a
smoke test, and the page's real verification is still outstanding.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HTML = ROOT / "site" / "dashboard.html"
JS = ROOT / "site" / "dashboard.js"
CSS = ROOT / "site" / "dashboard.css"
ROUTES = ROOT / "backend" / "apps" / "metricsroutes.py"


class TheFilesExist(unittest.TestCase):
    def test_all_three_are_present(self):
        for p in (HTML, JS, CSS):
            self.assertTrue(p.is_file(), f"{p.relative_to(ROOT)} is missing")


class TheJsAndHtmlAgree(unittest.TestCase):
    """`$('foo')` in the JS must find `id="foo"` in the HTML."""

    def test_every_id_the_js_looks_up_exists_in_the_html(self):
        html = HTML.read_text(encoding="utf-8")
        js = JS.read_text(encoding="utf-8")
        ids_in_html = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
        wanted = set(re.findall(r"""\$\(['"]([A-Za-z0-9_-]+)['"]\)""", js))
        wanted |= set(re.findall(r"""getElementById\(['"]([A-Za-z0-9_-]+)['"]\)""", js))
        missing = sorted(wanted - ids_in_html)
        self.assertEqual([], missing,
                         "the JS looks up ids the page does not define; those sections would "
                         "silently render empty rather than error")

    def test_the_page_loads_the_stylesheet_and_the_script(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("/dashboard.css", html)
        self.assertIn("/dashboard.js", html)


class TheJsAndTheApiAgree(unittest.TestCase):
    """Every path the page fetches must be a route the router actually declares."""

    def test_every_fetched_endpoint_is_a_declared_route(self):
        js = JS.read_text(encoding="utf-8")
        src = ROUTES.read_text(encoding="utf-8")
        declared = set(re.findall(r'@router\.get\("([^"]*)"\)', src))
        # `prefix="/api/metrics"` is applied in api.py; the router declares the suffixes.
        full = {"/api/metrics" + d for d in declared}
        fetched = set()
        for raw in re.findall(r"""getJSON\(\s*[`'"]([^`'"]+)[`'"]""", js):
            fetched.add(raw.split("?")[0])
        unknown = sorted(f for f in fetched if f not in full)
        self.assertEqual([], unknown,
                         f"the page fetches routes that do not exist. declared: {sorted(full)}")

    def test_the_router_is_mounted_under_the_prefix_the_page_uses(self):
        api = (ROOT / "backend" / "api.py").read_text(encoding="utf-8")
        self.assertIn('metricsroutes.router, prefix="/api/metrics"', api,
                      "the page fetches /api/metrics/* but api.py does not mount it there")


class ThePageSendsNoCredential(unittest.TestCase):
    """NO API KEYS. This page is the reference for how to call these routes."""

    def test_the_js_sends_no_token_header(self):
        js = JS.read_text(encoding="utf-8")
        for bad in ("X-Symoneural-Token", "X-Sym-Token", "Authorization", "Bearer"):
            self.assertNotIn(bad, js, f"the dashboard sends {bad}; there are no tokens")

    def test_it_does_not_read_a_token_from_storage(self):
        """`sessionStorage.token` is how the other pages used to carry the operator token."""
        js = JS.read_text(encoding="utf-8")
        self.assertNotRegex(js, r"(session|local)Storage\s*\.\s*getItem\(\s*['\"]token")


class ItIsHonestAboutWhatItCannotDo(unittest.TestCase):
    """The page's own claims, pinned. These are the sentences that stop it misleading."""

    def test_it_states_that_a_dash_is_not_a_zero(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("never that it is zero", html,
                      "the contract line is what makes every blank figure readable")

    def test_it_says_overclocking_runs_nothing(self):
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("computed, never run", html)

    def test_it_distinguishes_a_cap_from_a_load(self):
        """'GPU 100%' means the ceiling is lifted, not that the GPU is busy. A page that
        blurred those would be unusable for the testing it exists to support."""
        html = HTML.read_text(encoding="utf-8")
        self.assertIn("ceilings, not load", html)


if __name__ == "__main__":
    unittest.main()
