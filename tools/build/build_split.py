#!/usr/bin/env python3
"""One page per section, at its own URL.

    python3 tools/build/build_split.py     # site/{overview,livestack,controlboard,receipts}.html

Runs AFTER every generator that writes into `site/index.html` and BEFORE build_cachebust.

## Why these exist alongside the tabbed front page

`tools/build/build_tabs.py` folds the front page into four panels behind a `matchMedia` gate.
That gate has a cliff: at 741px of window height the page is one screen, and at 739px it is
a 3,313px scroll. Garrett hit it by having a bookmarks bar. Separate pages have no gate to
fall off, plus real shareable URLs, a working back button, and no dependency on JavaScript
to reach a section.

**They do not remove scrolling, and nothing here should imply they do.** A page holding one
section has exactly the same budget as a panel holding one section: the rack is ~750px of
content against 589px at a 745px window. The fold and the density pass in `symoneural.css`
are what buy that back; this file only changes how a section is addressed.

## How, and why it is done by subtraction

Each page is `index.html` with the other sections deleted, rather than a shell reassembled
from parts. The head, the masthead, the header, the footer, the scripts and every cache-bust
stamp are then identical to the front page by construction, instead of by a copy that drifts.
There are exactly three `<section>` elements and no nesting, checked before relying on it, so
a non-greedy match is safe here.

`index.html` is NOT modified. The other generators own it and find their work by BEGIN/END
markers; moving a section out from under them would make the next run append a second copy
rather than replace the first.

## Routing

The clean URLs are served by FastAPI in `backend/server.py`, which is where all routing lives —
`ops/Caddyfile` has no rewrites and must not grow any. The `.html` files stay reachable too;
the routes are an addition, not a redirect.
"""
from __future__ import annotations

import pathlib
import re

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "site"

# The authored page-family map -- see tools/lib/page_families.py for why it is not restated here.
import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import page_families  # noqa: E402

# ------------------------------------------------------------------ entitlement filtering
#
# The Live Stack catalogue must not offer a customer application the viewer is not entitled
# to open. The page is GENERATED, so the filter belongs here and never in site/livestack.html
# -- a hand edit there is overwritten by the next run of this script.
#
# The generated page is static, so this cannot be a build-time decision: entitlement is
# per-viewer and is only known at request time. What the generator emits is therefore the
# HOOK -- a data attribute naming the application slug and a marker class -- and the page's
# own script hides an un-entitled card once it has asked the API who the viewer is. Baking a
# customer's entitlement into a static file would publish one customer's access to every
# other visitor, which is the opposite of what this is for.
#
# Fail closed: a card carrying ENTITLEMENT_ATTR starts hidden and is revealed only on a
# positive answer. A failed or absent entitlement check leaves it hidden.
ENTITLEMENT_ATTR = "data-entitlement-slug"
ENTITLEMENT_CLASS = "needs-entitlement"

#: Customer applications in the catalogue that require an entitlement to open.
#: A slug listed here is filtered; anything not listed is a shared surface and is unaffected.
ENTITLED_APPLICATIONS = ("dispatchos",)


def entitlement_markup(slug: str) -> str:
    """The attributes a catalogue card carries when it needs an entitlement."""
    if slug not in ENTITLED_APPLICATIONS:
        return ""
    return f' {ENTITLEMENT_ATTR}="{slug}" class="{ENTITLEMENT_CLASS}" hidden'


# slug -> (output file, section id kept, nav label, <title>)
PAGES = [
    ("overview",     "overview.html",     "hero",    "Overview",      "SyMoNeuRaL — local AI infrastructure"),
    ("livestack",    "livestack.html",    "rack",    "Live stack",    "Live stack — SyMoNeuRaL"),
    ("controlboard", "controlboard.html", "console", "Control board", "Control board — SyMoNeuRaL"),
    ("receipts",     "receipts.html",     "more",    "Receipts",      "Receipts — SyMoNeuRaL"),
]

SECTIONS = {"rack", "console", "more"}
MASTHEAD = re.compile(r"<!-- ===== MASTHEAD:BEGIN.*?<!-- ===== MASTHEAD:END ===== -->\n?", re.S)
TABS = re.compile(r"<!-- BEGIN tabs \(build_tabs\.py\) -->.*?<!-- END tabs -->\n*", re.S)
TABS_JS = re.compile(r"<!-- BEGIN tabs-js \(build_tabs\.py\) -->.*?<!-- END tabs-js -->\n*", re.S)


def nav(current: str) -> str:
    """The tab strip, as links.

    A <div role="navigation">, NOT a <nav>: `nav a:not(.cta){display:none}` in
    symoneural.css hides nav links below 820px, which would delete every link here on a
    phone. That rule has already eaten one component's links in this repo.
    """
    links = "\n".join(
        f'      <a class="ns-tab{" on" if slug == current else ""}" href="/{slug}"'
        f'{" aria-current=&quot;page&quot;" if slug == current else ""}>{label}</a>'
        .replace("&quot;", '"')
        for slug, _f, _sec, label, _t in PAGES
    )
    return f"""<div class="ns-tabs" role="navigation" aria-label="Sections">
  <div class="wrap ns-tabwrap">
{links}
    <span class="ns-tabnote">Each section has its own address. Nothing is hidden.</span>
  </div>
</div>"""


def drop_section(html: str, sid: str) -> str:
    # `[^>]*` after the id, because the tags are not uniform -- build_console.py emits
    # `<section id="console" style="padding-top:34px">`. Matching a bare `">` silently
    # dropped nothing for that one section, and every page shipped with a control board
    # welded to it. Assert the removal instead of trusting the pattern.
    out, n = re.subn(rf'<section id="{sid}"[^>]*>.*?</section>\n*', "", html, flags=re.S)
    assert n == 1, f"expected to remove exactly one #{sid}, removed {n}"
    return out


def main() -> int:
    src = (SITE / "index.html").read_text()
    if "<!-- BEGIN tabs" not in src:
        print("  index.html has no tab strip -- run build_tabs.py first")
        return 1

    for slug, fname, keep, _label, title in PAGES:
        html = src

        # the one-screen layout without JavaScript: on a page holding a single section
        # nothing can be hidden, so the class is safe in the markup. On index.html it is
        # added from JS precisely because there it DOES hide things.
        #
        # `data-section` rides along because `ns` alone cannot answer the question the
        # stylesheet actually needs to ask. `ns` means "one-screen density"; it was set here
        # so a standalone section page reads like its panel did. But some rules under it are
        # not density -- they are arithmetic against the 587px TAB PANEL on the front page,
        # and the rack's row compression is the clearest case: it squeezes a unit row to a
        # 17px glyph in 2px of padding to fit twelve of them inside that panel. A standalone
        # page has no panel and no tab chrome, so the same rule there buys nothing and costs
        # readability -- measured at 33px per row at 1440x900, which is the "compressed into
        # unreadable one-line slivers" defect reported against /livestack.
        #
        # This file's own docstring already made the argument and the markup had not caught
        # up: *"Separate pages have no gate to fall off."* The attribute is what lets the
        # stylesheet act on that, per page, without weakening the front page's budget.
        # `data-family` is emitted STATICALLY here, not left to site/shell.js. Measured in
        # 6.1: with scripting off these pages fell back to the 1120px prose width. The value
        # comes from the one authored map in tools/lib/page_families.py rather than being typed
        # here, so the generator and the tests cannot disagree about it.
        html = html.replace(
            '<html lang="en">',
            f'<html lang="en" class="ns" data-section="{slug}"'
            f'{page_families.attribute(fname)}>', 1)
        html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)

        if keep != "hero":
            html = MASTHEAD.sub("", html)
        for sid in SECTIONS - {keep}:
            html = drop_section(html, sid)

        # THE PAGE'S PRIMARY HEADING. Measured across all 23 shell pages: livestack,
        # controlboard and receipts carried NO `h1` at all, because the only `h1` on
        # index.html lives in the hero and these three pages drop the hero. A page whose
        # outline starts at `h2` has no primary heading, which is what the accessibility
        # pass reported.
        #
        # The kept section's own `h2` is promoted rather than a new heading being invented:
        # when a page holds exactly one section, that section's title IS the page title, and
        # adding a second heading above it would be the duplicate-heading fix this is
        # supposed to avoid. `overview` keeps the hero and already has its `h1`, so it is
        # untouched -- promoting there would give it two.
        #
        # Visual styling is preserved by `section h1` being given the same rule as
        # `section h2` in symoneural.css, not by a class added here.
        if keep != "hero":
            promoted, n = re.subn(r"<h2>(.*?)</h2>", r"<h1>\1</h1>", html, count=1, flags=re.S)
            assert n == 1, (
                f"{fname}: expected exactly one h2 to promote to the page heading, found {n}")
            html = promoted

        html = TABS.sub(nav(slug) + "\n\n", html)
        html = TABS_JS.sub("", html)          # buttons became links; the panel switcher goes

        (SITE / fname).write_text(html)
        print(f"  {fname}: keeps {keep}")

    print(f"  {len(PAGES)} pages; index.html untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
