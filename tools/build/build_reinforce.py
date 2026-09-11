#!/usr/bin/env python3
"""Generate frontend/site/pages/reinforce.html and frontend/site/js/reinforce.js -- the SyMoNeuRaL Reinforce training bay.

    python3 tools/build/build_reinforce.py

## This generator writes almost nothing of its own. It is wiring.

`backend/studio/plugins/reinforce/page.html` and `page.js` were written by the author of
`backend/studio/plugins/reinforce/routes.py`, committed in `170692e`, and then referenced by **nothing**.
No generator built them into a page, no script copied them, no test loaded them. `page.js` says
in its own second line where it was meant to go:

    Deploys to `frontend/site/js/reinforce.js`; `page.html` loads it with `<script src="/reinforce.js" defer>`.

That deploy step did not exist. This file is it.

The first draft of this generator was a second, hand-written training page -- before its author
read the orphans. It was worse in every respect that matters: it rendered the preset table from
build-time constants where `page.js` renders it from the live API, and it had no job panel at
all. Rebuilding from scratch what somebody has already built well is the more expensive kind of
duplication, because both copies then have to be kept true. This one was thrown away.

## What the transform does, and why it is not just a copy

`page.html` is a **section fragment**: `<section id="reinforce"><div class="wrap">…`, shaped to be
injected into an existing page between BEGIN/END markers. The shell from `build_pages.py` already
opens a `<section>` and a `<div class="wrap">` around `@@BODY@@`, so pasting the fragment in
whole would nest a wrap inside a wrap and double the page's side padding.

So the outer two elements are replaced with a single `<div id="reinforce">`. The **id is kept**,
and that is the load-bearing part: every selector in the fragment's own stylesheet is written as
`#reinforce .rf-something`, deliberately, as a defence against the four bugs this site has had
from generic class names colliding across components. Drop the id and the whole panel loses its
styling silently -- it would still render, just wrong, which is the failure mode that is hardest
to notice.

Every step of that transform is asserted rather than assumed. A fragment whose author changes its
outer markup should fail this build loudly, not ship a page with a stray `</section>` in it.

## Why there are no numbers in this file

There are none to put here. `page.js` reads the model list, the preset table, the VRAM
arithmetic and the job state from `/api/train/*` at view time, and every figure it renders
carries its own measured/vendor/projected badge from the response body. A constant copied into
this generator would be a second source of truth for a hyper-parameter, and this repo has already
paid for one of those: `test_alpha_is_twice_rank_everywhere` was red for hours against a source
file that was correct, because a stale `.pyc` held an old alpha. A hand-copied `48` on a public
page would have made that permanent instead of merely confusing.

## Running it twice

Both outputs are rewritten in full from their inputs, so two runs produce byte-identical files.
Nothing here reads the clock, the GPU or the API.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "frontend" / "site"
APP = ROOT / "backend" / "studio" / "plugins" / "reinforce"
sys.path.insert(0, str(ROOT / "tools"))

import build_pages  # noqa: E402  -- for NAV and SHELL. Read, never called: `page()` writes the
                    # surface pages this generator does not own, and calling it would
                    # rewrite them.

#: The fragment's markers. They are the contract with `page.html`, and they are checked rather
#: than trusted -- `.claude/CLAUDE.md` is explicit that a drifted marker string is how a
#: generator stops finding its block.
BEGIN = "<!-- BEGIN REINFORCE BAY -->"
END = "<!-- END REINFORCE BAY -->"

#: The fragment's outer wrapper, replaced so the shell's own `<section><div class="wrap">` is not
#: nested inside a second one.
OUTER_OPEN = '<section id="reinforce">\n  <div class="wrap">'
OUTER_CLOSE = "  </div>\n</section>"

#: The script tag `page.html` ends with. It is moved out of the body and into the shell's
#: `@@SCRIPT@@` slot, which is where every other page on this site puts its script -- after the
#: markup it drives, and where `build_cachebust.py` expects to stamp it.
SCRIPT_TAG = '<script src="/reinforce.js" defer></script>'


def without_comments(html: str) -> str:
    """`html` with CSS and HTML comments removed, for assertions about what the page *does*.

    This exists because the obvious version of the ellipsis assertion below failed on the first
    run against a page that was entirely correct. `page.html` opens its stylesheet with a
    comment in capitals saying there is no `text-overflow:ellipsis` in it and there must never
    be one -- and a substring search cannot tell a rule from a promise not to write one.

    That is the fifth time a verification step on this repo has gone red on healthy input, and
    `.claude/HANDOVER.md` §3.0d keeps a list of them precisely because the reflex when one fires
    is to change the page rather than the check. Run any new assertion against the real input and
    confirm it passes on known-good, not only that it fails on known-bad.
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
        "assertion: the `id=\"reinforce\"` it carries is what every selector in the fragment's "
        "own stylesheet hangs off, and losing it renders the panel unstyled rather than broken.")
    assert raw.endswith(OUTER_CLOSE), "page.html's outer closing tags changed shape"

    inner = raw[len(OUTER_OPEN):-len(OUTER_CLOSE)]
    # One wrapper, id preserved. Two spaces of the fragment's indentation go with the removed
    # `<div class="wrap">`, but indentation is not meaning and re-indenting 250 lines would make
    # every future diff against `page.html` unreadable.
    body = f'    <div id="reinforce">{inner}    </div>'

    assert "<section" not in body, "an unbalanced <section> survived the unwrap"
    assert 'class="wrap"' not in body, "the nested wrap survived the unwrap"
    assert 'id="reinforce"' in body, "the id every selector in this fragment depends on is gone"
    return body


def main() -> int:
    body = fragment()

    html_out = build_pages.SHELL.replace("@@NAV@@", build_pages.NAV)
    fields = {
        "TITLE": "SyMoNeuRaL Reinforce — fine-tune the model that answers here",
        "DESC": ("A training bay on one RTX 5070 Ti: four predetermined tuning methods, each "
                 "costed before it runs. Every figure says whether it was measured here or is "
                 "arithmetic."),
        "ICON": "/assets/brand/mark-64.png",
        "EYEBROW": "Live surface · GPU · operator token required",
        "HEADING": "Fine-tune the model that answers here.",
        # The lede states the two things a visitor has to know before anything else on the page
        # makes sense: what the surface does, and why it is off. It is off by default and that
        # is the state most visitors will see, so saying it in the hero is honest rather than
        # apologetic.
        "LEDE": ("Four named methods, each with the reasoning behind every value and the "
                 "arithmetic for what it will cost in VRAM before a single weight is read. "
                 "A run takes the whole card and is never evicted to serve a page, so this "
                 "surface accepts work only when the operator switches it on."),
        "BODY": body,
        "SCRIPT": SCRIPT_TAG,
    }
    for key, value in fields.items():
        html_out = html_out.replace(f"@@{key}@@", value)

    # A leftover marker means the shell grew a field this generator does not fill, which would
    # ship the literal '@@SOMETHING@@' to a visitor.
    assert "@@" not in html_out, "unsubstituted placeholder left in the page"
    # Opt in to the application shell: no marketing hero above the workspace, and the
    # test-bench callout relocated out of it into a disclosure below the footer. This is a
    # CALL rather than a new `@@...@@` in the shared SHELL, which is the whole reason it is
    # shaped this way -- a placeholder added to SHELL would have broken the assert two lines
    # above on a correct page, which is exactly what `@@PAGECSS@@` did here once already.
    # ---- fixes whose SOURCE lives outside the frontend allowlist -------------------
    # `backend/studio/plugins/reinforce/page.html` is this page's authored fragment, and
    # it is under `backend/`, which Handshake 6.2 does not permit writing. Two corrections
    # made in 6.1 were applied to the GENERATED `frontend/site/pages/reinforce.html` and were therefore
    # reverted the moment this generator next ran -- which is exactly what happened on
    # 2026-08-29. A fix applied to generated output is not a fix; it is a countdown.
    #
    # They are applied HERE instead, on the rendered fragment, which is the authorized
    # surface and the one that survives regeneration. Both are asserted rather than
    # best-effort, so a change to the fragment upstream fails loudly here instead of
    # silently dropping the correction again.
    _grid_old = "grid-template-columns:repeat(auto-fit,minmax(300px,1fr));"
    _grid_new = "grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));"
    if _grid_old in html_out:
        # `minmax(300px,...)` makes 300px a HARD floor, so at a 320px viewport -- where the
        # content column is 256px -- the card lays out at 300px and its right edge lands at
        # 328px, outside the viewport. Measured; it was the only horizontal overflow left on
        # the site. `min()` keeps the intent wherever there is room and lets the track
        # collapse where there is not.
        html_out = html_out.replace(_grid_old, _grid_new)
    assert _grid_new in html_out, (
        "the rf-grid track definition moved in page.html; the 320px overflow fix was lost")

    _n = html_out.count("font-size:10.5px")
    html_out = html_out.replace("font-size:10.5px", "font-size:var(--t7)")
    assert "font-size:10.5px" not in html_out
    assert _n, "page.html no longer carries the 10.5px micro-labels this expected to fix"

    html_out = build_pages.appify(html_out)
    # The <main> landmark and the static data-family, from the one authored map in
    # tools/lib/page_families.py. Opted into the same way `appify` is, for the reason its
    # comment gives: a shared shell cannot grow a new placeholder without breaking
    # every consumer that substitutes its own field dict.
    html_out = build_pages.landmark(html_out, "reinforce.html")
    # Not a tidiness check. Every ellipsis rule on this site has been removed because two of
    # them were caught truncating real data -- `built on Qwen2.5-7B-Instruct`, which is an
    # Apache-2.0 licence condition, and a control-board reading mid-number. This page carries
    # model paths, licence attributions and the VRAM arithmetic that is the whole argument.
    # Asserted against the comment-stripped page: see `without_comments`.
    assert "text-overflow" not in without_comments(html_out), "an ellipsis rule reached the page"
    # The two artefacts that must never be published. `dataset_guard.py` refuses them at the
    # API; the page must not name a path to them either, and an assertion is cheaper than
    # remembering. These run against the WHOLE page, comments included -- an HTML comment ships
    # to the visitor, so a path in one is published just as surely as a path in a paragraph.
    # `page.html` states the refusal in prose without naming either file, which is correct and
    # is what these two lines keep true.
    assert "corpus.jsonl" not in html_out, "the protected corpus was named on a public page"
    assert "build_dataset" not in html_out, "the protected dataset builder was named on a page"

    (SITE / "reinforce.html").write_text(html_out)
    print("  reinforce.html")

    # Copied rather than imported, because it is the browser that needs it and `site/` is what
    # `scripts/deploy.sh` copies to the webroot. The source of truth stays beside the routes it
    # calls, which is the only place it can be kept true.
    js = (APP / "page.js").read_text()
    (SITE / "reinforce.js").write_text(js)
    print("  reinforce.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
