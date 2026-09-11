"""Static page semantics: one `<main>`, one `h1`, and the right `data-family`.

Handshake 6.2 moved three properties out of JavaScript and into the markup, and this file is
what keeps them there. All three are checked by READING `site/*.html` on disk -- no browser, no
running service -- because all three are supposed to be true before anything executes. A check
that needs JavaScript to run cannot prove a property whose whole point is not needing it.

## Why the family map is read and not restated

`tools/page_families.py` is the one authored source. The generators import it, the hand-authored
pages carry what it says, and this file READS it and compares it against what is on disk. Typing
the pairs again here would make four copies of one fact -- the map, the generated markup, the
hand-authored markup and the test -- which is the failure `backend/ROSTER.md` was written
about, arriving in the frontend.

That is a deliberate departure from the roster's own two-hand-maintained-copies pattern, and the
reason is that the roster's copies describe DIFFERENT things (identity versus what the code
builds) while these would be the same list four times.

## The two pages that are expected to fail the outline rule, and why they are not skipped

`studio.html` and `exp.html` build several headings at runtime from `backend/studio/page.js`
and `backend/studio/plugins/exp/page.js`. Their outline still opens with a level jump. That
is recorded as out-of-scope for 6.2 -- the fix belongs in files this task may not write -- and it
is named here explicitly rather than being excluded by a filter, so the day someone fixes it this
test tells them the exemption can go.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "tools"))

import page_families  # noqa: E402

#: The public shell pages. Every one of them carries the site header and footer, which is what
#: makes `<main>` meaningful; `training.html` has its own and is not a shell page.
PAGES = [
    "index.html", "overview.html", "livestack.html", "controlboard.html", "receipts.html",
    "chat.html", "image.html", "ravencalc.html", "remix.html", "miner.html", "gateway.html",
    "streamer.html", "studio.html", "exp.html", "project.html", "reinforce.html",
    "sigils.html", "coder.html", "live.html", "account.html", "credits.html",
    "documentation.html", "build.html",
]

_MAIN = re.compile(r"<main\b", re.I)
_H1 = re.compile(r"<h1\b", re.I)
_FAMILY = re.compile(r'<html[^>]*\bdata-family="([a-z]+)"', re.I)


def read(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


class EveryShellPageHasOneMainLandmark(unittest.TestCase):
    def test_exactly_one_main(self):
        """Measured before 6.2: ZERO of the 23 pages had one. The shared shell supplies no
        landmark, so this was never a one-page defect even though it was first counted as one."""
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(len(_MAIN.findall(read(name))), 1)

    def test_main_wraps_the_content_and_not_the_header_or_footer(self):
        """`<main>` opens after `</header>` and closes before `<footer>`. Asserted by position
        rather than by parsing: a landmark that contained the site header would be worse than
        none, because it would tell a screen reader the navigation is page content."""
        for name in PAGES:
            with self.subTest(page=name):
                html = read(name)
                self.assertLess(html.index("</header>"), html.index("<main"))
                self.assertLess(html.index("</main>"), html.index("<footer"))


class EveryShellPageHasOnePrimaryHeading(unittest.TestCase):
    def test_exactly_one_h1(self):
        """`livestack`, `controlboard` and `receipts` had none: they are built by
        `tools/build_split.py`, which drops the hero that carries index.html's only `h1`. The
        generator now promotes the kept section's `h2`, so the section's title becomes the
        page's title rather than a second heading being invented above it."""
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(len(_H1.findall(read(name))), 1)


class TheFamilyIsInTheMarkup(unittest.TestCase):
    def test_every_page_carries_the_family_its_authored_map_gives_it(self):
        """The 224px defect, asserted statically.

        Before 6.2 the family was set by `site/shell.js`, so with scripting off 14 pages fell
        back to the 1120px prose width -- measured 1120 against 1344 at a 1440px viewport. The
        attribute is now in the markup, and this compares the markup against the one authored
        map rather than against a second copy of it.
        """
        for name in PAGES:
            with self.subTest(page=name):
                want = page_families.family_of(name)
                found = _FAMILY.search(read(name))
                got = found.group(1) if found else None
                self.assertEqual(got, want)

    def test_a_page_in_neither_dict_is_a_failure_not_a_default(self):
        """An unclassified page silently takes the prose width, which looks like a design
        choice. `family_of` raises instead, and that is the behaviour worth pinning."""
        with self.assertRaises(KeyError):
            page_families.family_of("a-page-nobody-classified.html")

    def test_shell_js_no_longer_carries_a_second_copy_of_the_map(self):
        """6.2 moved the authority into markup. If a map reappears here the two can disagree,
        and the JavaScript one wins at runtime while the static one wins for a reader with
        scripting off -- the worst of both."""
        js = (SITE / "shell.js").read_text(encoding="utf-8")
        self.assertNotIn("FAMILY = {", js)
        self.assertNotIn("'workbench'", js)

    def test_shell_js_does_not_write_the_attribute(self):
        """It may warn about a missing family; it must not supply one. A fallback that quietly
        produces the right answer hides the omission it exists to report."""
        js = (SITE / "shell.js").read_text(encoding="utf-8")
        self.assertNotIn("setAttribute('data-family'", js)
        self.assertNotIn('setAttribute("data-family"', js)


class TheDocumentationIndexIsGenerated(unittest.TestCase):
    def test_the_index_covers_exactly_the_registry(self):
        """`tools/build_docs_index.py` emits it from `apps/appdocs.py`. Both directions are
        checked, so an application added to the registry and not regenerated fails here rather
        than going missing from the index quietly."""
        sys.path.insert(0, str(ROOT / "backend"))
        from registry.lib import appdocs
        html = read("documentation.html")
        found = sorted(set(re.findall(r'href="/docs/([a-z]+)"', html)))
        self.assertEqual(found, sorted(a.id for a in appdocs.APPLICATIONS))

    def test_the_index_is_inside_its_generator_markers(self):
        html = read("documentation.html")
        self.assertIn("DOCSINDEX:BEGIN", html)
        self.assertIn("DOCSINDEX:END", html)
        begin = html.index("DOCSINDEX:BEGIN")
        end = html.index("DOCSINDEX:END")
        self.assertLess(begin, html.index('class="dx"'))
        self.assertLess(html.index('class="dx"'), end)


if __name__ == "__main__":
    unittest.main()
