#!/usr/bin/env python3
"""Generate site/studio.html and site/studio.js -- the SyMoNeuRaL Studio surface.

    python3 tools/build_studio.py

## What this page is, and what it deliberately is not

The Studio is the local agent (tool-calling, over llama.cpp) plus the image bench (ComfyUI,
behind the GPU governor), on one page. The bench is **ComfyUI's own node editor**, in an
iframe, served same-origin through `/studio/editor/` by a reverse proxy in
`backend/studio/routes.py`.

That last point is the largest single decision in this app, so it is written down here as well
as in the routes: **no node canvas was written for this page.** An earlier draft had one --
snap-to-grid, SVG wires, port-type checking, about a thousand lines. Then
`comfyui_frontend_package 1.49.6` turned out to be installed in `symoneural-ui/.venv`, which is the
same production editor ComfyUI itself serves, and it computes its API base as
`location.pathname.split('/').slice(0,-1).join('/')` -- meaning sub-path hosting is a supported
configuration upstream, not a hack. A hand-written canvas would have been a permanently worse
copy of a thing already on the disk, and every ComfyUI node update would have been a bug in it.
The canvas was deleted. What this generator ships is the SyMoNeuRaL chrome around it: the
agent transcript, the render form, the status strip and the tool registry.

## The transform

Identical in shape to `tools/build_reinforce.py`, and for the same reason: `page.html` is a
section fragment (`<section id="studio"><div class="wrap">…`) and `build_pages.SHELL` already
opens a `<section>` and a `<div class="wrap">` around `@@BODY@@`. Pasting it in whole would
nest a wrap inside a wrap and double the side padding. So the outer two elements become one
`<div id="studio">` -- **id preserved**, because every selector in the fragment's stylesheet is
written `#studio .st-*` on purpose, as a defence against the four bugs this site has had from
generic class names colliding across components. Lose the id and the panel renders unstyled
rather than broken, which is the failure mode hardest to notice.

Every step is asserted. A fragment whose author changes its outer markup fails this build
loudly instead of shipping a stray `</section>`.

## Running it twice

Both outputs are rewritten in full from their inputs. Nothing here reads the clock, the GPU or
the API, so two runs produce byte-identical files.

## This script destamps the page. Run `tools/build_cachebust.py` after it, every time

`page.html` carries plain `href="/symoneural.css"` and `src="/studio.js"`, and that is what this
writes. The committed `site/studio.html` carries nine `?v=<hash>` stamps instead, added by
`tools/build_cachebust.py`. So a bare run of this generator produces a diff that removes every
stamp and reads like a harmless refresh -- and a commit taken at that moment ships a page whose
CSS and JS are cacheable for a week with no way to invalidate them. `.claude/CLAUDE.md` records
this happening to seven pages at once via `build_pages.py`; this script is not an exception to it.

    python3 tools/build_studio.py && python3 tools/build_cachebust.py

`test_studio.py::PageTests::test_the_built_page_is_this_generators_output_with_stamps_added`
fails on a destamped `site/studio.html`, so the omission is caught by the suite rather than by a
visitor holding a week-old stylesheet.
"""
from __future__ import annotations

import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "site"
APP = ROOT / "backend" / "apps" / "studio"
sys.path.insert(0, str(ROOT / "tools"))

import build_pages  # noqa: E402  -- for NAV and SHELL. Read, never called: `page()` writes the
                    # surface pages this generator does not own, and calling it would
                    # rewrite them.

#: The fragment's markers -- the contract with `page.html`, checked rather than trusted.
BEGIN = "<!-- BEGIN STUDIO -->"
END = "<!-- END STUDIO -->"

OUTER_OPEN = '<section id="studio">\n  <div class="wrap">'
OUTER_CLOSE = "  </div>\n</section>"

#: Moved out of the body into the shell's `@@SCRIPT@@` slot, where every other page on this
#: site puts its script and where `build_cachebust.py` expects to stamp it.
SCRIPT_TAG = '<script src="/studio.js" defer></script>'


def without_comments(html: str) -> str:
    """`html` with CSS and HTML comments removed, for assertions about what the page *does*.

    Copied from `build_reinforce.py`, which learned it the hard way: `page.html` opens its
    stylesheet with a comment in capitals promising there is no `text-overflow: ellipsis` in it
    and there never will be, and a substring search cannot tell a rule from a promise not to
    write one. Verified here the same way -- `grep -c text-overflow page.html` returns 1, the
    comment, and this build passes. Run any new assertion against known-good input, not only
    against known-bad.
    """
    for opener, closer in (("<!--", "-->"), ("/*", "*/")):
        kept, i = [], 0
        while True:
            start = html.find(opener, i)
            if start < 0:
                kept.append(html[i:])
                break
            kept.append(html[i:start])
            end = html.find(closer, start + len(opener))
            if end < 0:                      # unterminated: drop the rest rather than keep it
                break
            i = end + len(closer)
        html = "".join(kept)
    return html


def fragment() -> str:
    """`page.html`, unwrapped, with its script tag removed. Asserted at every step."""
    raw = (APP / "page.html").read_text().strip()

    assert raw.startswith(BEGIN), f"page.html no longer starts with {BEGIN!r}"
    assert raw.endswith(END), f"page.html no longer ends with {END!r}"
    raw = raw[len(BEGIN):-len(END)].strip()

    assert raw.endswith(SCRIPT_TAG), (
        "page.html no longer ends with its script tag; it would be dropped silently")
    raw = raw[:-len(SCRIPT_TAG)].strip()

    assert raw.startswith(OUTER_OPEN), (
        "page.html's outer <section>/<div class=\"wrap\"> changed shape. Do not relax this "
        "assertion: the `id=\"studio\"` it carries is what every selector in the fragment's own "
        "stylesheet hangs off, and losing it renders the page unstyled rather than broken.")
    assert raw.endswith(OUTER_CLOSE), "page.html's outer closing tags changed shape"

    inner = raw[len(OUTER_OPEN):-len(OUTER_CLOSE)]
    body = f'    <div id="studio">{inner}    </div>'

    assert "<section" not in body, "an unbalanced <section> survived the unwrap"
    assert 'class="wrap"' not in body, "the nested wrap survived the unwrap"
    assert 'id="studio"' in body, "the id every selector in this fragment depends on is gone"
    return body


def main() -> int:
    body = fragment()

    html_out = build_pages.SHELL.replace("@@NAV@@", build_pages.NAV)
    fields = {
        "TITLE": "SyMoNeuRaL Studio — a local agent and an image bench on one card",
        "DESC": ("A tool-calling agent running on this machine's own 7B, and ComfyUI's node "
                 "editor behind the same GPU mutex everything else here waits on. No cloud "
                 "inference, no hosted queue."),
        "ICON": "/mark-64.png",
        "EYEBROW": "Live surface · GPU · operator token required",
        "HEADING": "An agent that can touch the machine it runs on.",
        # The lede has to say three things before anything else on the page parses: what the
        # agent is, that the bench is ComfyUI's own editor rather than a lookalike, and why the
        # surface is off. Off is the state most visitors see, so it belongs in the hero rather
        # than in a footnote.
        "LEDE": ("The model that answers on this site, given tools: the filesystem, the "
                 "process table, the GPU governor and the image pipeline. Renders run in "
                 "ComfyUI's own node editor, embedded here and holding the same single-card "
                 "lock as chat and training — so this surface accepts work only when the "
                 "operator switches it on and presents a token."),
        "BODY": body,
        "SCRIPT": SCRIPT_TAG,
    }
    for key, value in fields.items():
        html_out = html_out.replace(f"@@{key}@@", value)

    assert "@@" not in html_out, "unsubstituted placeholder left in the page"
    # Opt in to the application shell: no marketing hero above the workspace, and the
    # test-bench callout relocated out of it into a disclosure below the footer. This is a
    # CALL rather than a new `@@...@@` in the shared SHELL, which is the whole reason it is
    # shaped this way -- a placeholder added to SHELL would have broken the assert two lines
    # above on a correct page, which is exactly what `@@PAGECSS@@` did here once already.
    html_out = build_pages.appify(html_out)
    # The <main> landmark and the static data-family, from the one authored map in
    # tools/page_families.py. Opted into the same way `appify` is, for the reason its
    # comment gives: a shared shell cannot grow a new placeholder without breaking
    # every consumer that substitutes its own field dict.
    html_out = build_pages.landmark(html_out, "studio.html")
    # Not tidiness. Every ellipsis rule on this site has been removed because two were caught
    # truncating real data. This page carries workspace paths, model filenames and tool
    # descriptions, all of which are exactly long enough to get cut. Asserted against the
    # comment-stripped page: see `without_comments`.
    assert "text-overflow" not in without_comments(html_out), "an ellipsis rule reached the page"
    # The two artefacts that must never be published. The Studio's agent can read any file on
    # this box, which makes it the single most likely surface to name one of these on a public
    # page. An assertion is cheaper than remembering. Run against the WHOLE page, comments
    # included -- an HTML comment ships to the visitor.
    assert "corpus.jsonl" not in html_out, "the protected corpus was named on a public page"
    assert "build_dataset" not in html_out, "the protected dataset builder was named on a page"
    # The operator token gates a surface that can run commands as this user. `page.js` reads it
    # from sessionStorage and sends it in a header; nothing is supposed to bake it into the
    # markup. This catches the one way that could happen by accident -- a generator run in a
    # shell that has the secret exported, by an author who added a "convenience" default.
    secret = os.environ.get("SYMONEURAL_STUDIO_TOKEN")
    if secret:
        assert secret not in html_out and secret not in (APP / "page.js").read_text(), (
            "the live operator token was baked into a generated page")

    (SITE / "studio.html").write_text(html_out)
    print("  studio.html")

    # Copied rather than imported, because it is the browser that needs it and `site/` is what
    # `scripts/deploy.sh` copies to the webroot. The source of truth stays beside the routes it
    # calls, which is the only place it can be kept true.
    js = (APP / "page.js").read_text()
    # NOT REWRITTEN HERE, and the attempt is recorded rather than left as a scar.
    #
    # This page builds several of its headings at RUNTIME -- `el('h3', ...)`, `el('h4', ...)`,
    # `el('h5', ...)` in `page.js` -- so the static outline pass in `build_pages._outline`
    # cannot see them and the rendered document still opens with a level jump. Handshake 6.2
    # tried to correct the first of them from this generator and stopped: the literal is
    # assembled inside a ternary rather than written as one call, and matching it by string
    # surgery against source this repository is not authorized to read as an editable file
    # would be guessing at code rather than changing it.
    #
    # The authored source is `backend/.../page.js`, which is outside 6.2's frontend
    # allowlist. The outline defect on this page is therefore RECORDED as out-of-scope rather
    # than papered over. See the 6.2 evidence root.
    (SITE / "studio.js").write_text(js)
    print("  studio.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
