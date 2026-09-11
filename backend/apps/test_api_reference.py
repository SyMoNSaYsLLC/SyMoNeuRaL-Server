"""The API reference page is ours, and its JavaScript is written inside a Python string.

Task #74 item 6 replaced a third-party documentation UI with a renderer of our own. That is
the right outcome and it introduced a failure mode the vendor bundle did not have: the
renderer lives in `API_REFERENCE_SCRIPT`, a Python triple-quoted string, so **Python's escape
rules run over the JavaScript before a browser ever sees it**.

That is not hypothetical. The first version of this page shipped `\\"` where it needed `\\\\"`,
Python collapsed it to a bare quote, the JS string terminated early, and the whole script
died on `Unexpected identifier 'ar'`. `/docs` answered **200 with 15 KB of correct-looking
HTML** and rendered an empty page, because everything below the fetch was dead. `curl` cannot
see this and neither can `ast.parse`; the page is syntactically perfect Python containing
broken JavaScript.

So the first test here hands the extracted script to `node --check`. It is the cheap version
of the browser assertion in `tests/frontend.mjs`, and it runs in the backend suite on every
commit rather than only when someone starts an API and a browser.

The rest assert the properties the page is *supposed* to have, each of which is a rule this
repo learned the hard way and wrote down:

- every class prefixed `ar-`, because three separate bugs here came from generic class names
  colliding across components -- `.bar` collapsed the site header to 7px sitewide, `.live`
  styled the control board legend, `#console .sub` outranked `.mod .sub`
- no `text-overflow`, because an ellipsis on a reference page is data loss with extra steps
  and every such rule was deleted from the site's CSS after an Apache-2.0 attribution was
  truncated to `...7B-Ins...`
- inline, not a file under `site/`, because `/docs` is assembled at request time and
  `build_cachebust.py` never sees it
- no vendor name, which is item 6's actual acceptance test

Read as source, never imported: importing `api.py` starts a process that owns the GPU lease,
which is why every other suite in this directory reads it the same way.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend" / "api.py"

#: Third-party documentation UIs. Named here rather than in `api.py` because #74's declared
#: check greps that file for the word and a docstring keeping it would hold the check red for
#: prose. A test file is where the name belongs anyway: this is the list of things that must
#: not come back.
RETIRED = ("swagger", "redoc", "rapidoc", "stoplight")

#: FastAPI's own switches for turning its built-in doc UIs OFF. These contain a retired name
#: and are the opposite of the problem -- `redoc_url=None` is what stops ReDoc being served.
#:
#: Written out rather than left to a looser pattern because a name-scanning test that flags
#: the line disabling a thing pressures the next reader into deleting it, which switches the
#: thing back on. That is the same trap as a brand sweep broad enough to strip a licence
#: notice, and it is worth one explicit constant to avoid.
DISABLE_SWITCHES = ("docs_url=None", "redoc_url=None", "openapi_url=None")


def extract(constant: str) -> str:
    """The runtime value of one module-level string constant, without importing `api.py`.

    Parsed rather than regex-matched, and the difference is not stylistic. A regex over the
    file hands back the **source** text, in which `\\\\/` is two characters and `\\\\"` is
    two characters; Python collapses both before the value ever reaches a browser. Checking
    the source form would pass on a string that ships broken and fail on one that ships fine
    -- which it did, on the first version of this file.

    Importing `api.py` would give the true value and also start a process that owns the GPU
    lease, which is why every suite in this directory reads it from disk instead.
    """
    tree = ast.parse(API.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if any(getattr(t, "id", None) == constant for t in node.targets):
                return node.value.value
    raise AssertionError(f"{constant} not found in api.py -- has the page been restructured?")


class RendererIsValidJavaScript(unittest.TestCase):
    """The one that would have caught the bug that shipped."""

    def test_the_script_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        block = extract("API_REFERENCE_SCRIPT")
        # Strip the surrounding <script> tags -- what is between them is what the browser
        # parses, and what `node --check` needs to be handed.
        body = re.sub(r"</?script[^>]*>", "", block)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(body)
            path = handle.name
        try:
            done = subprocess.run([node, "--check", path], capture_output=True, text=True)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(
            done.returncode, 0,
            "the reference renderer is not valid JavaScript. Python's escape rules ran over "
            "it first -- check for \\\" where the JS needs \\\\\" .\n" + done.stderr,
        )

    def test_the_script_still_reads_the_schema_rather_than_carrying_data(self):
        """The page's whole claim is that it cannot drift from the service."""
        body = extract("API_REFERENCE_SCRIPT")
        self.assertIn('fetch("/openapi.json"', body)

    def test_the_reference_handles_a_failed_fetch_visibly(self):
        """An empty list reads as "this API has no endpoints", which is worse than an error."""
        body = extract("API_REFERENCE_SCRIPT")
        self.assertIn(".catch(", body)
        self.assertIn("ar-fail", body)


class StyleRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.style = extract("API_REFERENCE_STYLE")

    def test_no_ellipsis_rule(self):
        self.assertNotIn(
            "text-overflow", self.style,
            "every text-overflow rule was deleted from this site's CSS on purpose; a "
            "reference page that trims a long path is losing the part the reader needed",
        )

    def test_every_selector_is_prefixed(self):
        """Generic class names have collided across components three times in this repo."""
        classes = set(re.findall(r"\.([a-zA-Z][\w-]*)", self.style))
        unprefixed = sorted(c for c in classes if not c.startswith("ar-"))
        self.assertEqual(
            unprefixed, [],
            "this page loads /symoneural.css and /rack-detail.css, so an unprefixed class "
            "here is a sitewide cascade bug waiting to happen",
        )


class NoVendorDocumentationUI(unittest.TestCase):
    """Item 6's acceptance test: no third-party doc UI, by name or by asset."""

    @classmethod
    def setUpClass(cls):
        source = API.read_text(encoding="utf-8").lower()
        # Blank the disable switches before scanning. `redoc_url=None` contains a retired
        # name and is the line that keeps ReDoc from being served; flagging it would invite
        # exactly the wrong repair.
        for switch in DISABLE_SWITCHES:
            source = source.replace(switch.lower(), "")
        cls.source = source

    def test_api_py_names_no_retired_documentation_ui(self):
        found = [name for name in RETIRED if name in self.source]
        self.assertEqual(found, [], "a third-party documentation UI is back in api.py")

    def test_the_builtin_doc_uis_are_still_switched_off(self):
        """The positive half, and the reason the scan above has an exemption list at all.

        FastAPI serves its own two doc UIs by default. `/docs` is ours only because both are
        disabled at the `FastAPI(...)` call and the route is re-registered by hand; delete
        those switches and the vendor UI comes straight back, with this file's negative
        tests still green because nothing would name it in the source.
        """
        raw = API.read_text(encoding="utf-8")
        for switch in ("docs_url=None", "redoc_url=None"):
            self.assertIn(switch, raw, f"{switch} was removed -- a vendor doc UI is back")

    def test_no_retired_asset_is_still_in_the_webroot(self):
        """Deleting the call and leaving 1.6 MB of bundle in `site/` is half a job.

        It also matters to `deploy.sh`, which copies the webroot wholesale -- an orphaned
        asset ships to the public server and is served to anyone who guesses the URL. That is
        how nineteen unreferenced PNGs ended up in the live webroot.
        """
        strays = sorted(
            p.name for p in (ROOT / "site").glob("*")
            if any(name in p.name.lower() for name in RETIRED)
        )
        self.assertEqual(strays, [], "retired documentation-UI assets are still in site/")

    def test_the_page_is_inline_rather_than_a_webroot_asset(self):
        """`/docs` is built at request time, so `build_cachebust.py` never stamps it.

        A `/apiref.css` would ship unstamped against markup that changes whenever a route is
        added -- cacheable for a week with no way to invalidate it.
        """
        source = API.read_text(encoding="utf-8")
        self.assertIn("API_REFERENCE_STYLE", source)
        self.assertNotRegex(
            source, r'href="/(apiref|api-reference|docs)\.css"',
            "the reference stylesheet was moved into site/; it must stay inline",
        )


if __name__ == "__main__":
    unittest.main()
