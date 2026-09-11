#!/usr/bin/env python3
"""Produce frontend/site/pages/training.html: the manual, rebranded as SyMoNeuRaL Training.

The source is the already-generated symoneural-manual.html rather than the markdown, and
that is a deliberate choice. That file carries a purpose-built long-form layout, a nested
contents nav, and 749 heading anchors -- including the ones already linked from elsewhere.
Re-converting the markdown without pandoc would mean rebuilding all of that and quietly
breaking every saved deep link. Transforming the rendered document keeps the structure
exactly and changes only what has to change.

Three transformations, in order of how much care each needs:

**Branding.** Purged, but surgically. Most 'MIT' matches in this corpus are substrings of
ordinary words -- limits, limited, submit, emits -- so a blind replace would corrupt the
prose. Only the whole-phrase brand and the local filesystem paths are rewritten.

**Theme.** The document already ships a dark mode keyed on a data-theme attribute, so it
is pinned to dark and its tokens are remapped onto the SyMoNeuRaL palette. Nothing about
its layout is touched.

**Zero data loss.** No table, figure, measurement or provenance marker is altered. The
filesystem paths that change are incidental local paths, never a number.
"""
from __future__ import annotations

import pathlib
import re

# The generators live in tools/, so the repo root is one level up. This exact
# calculation has been wrong twice in this repo's history -- once when demo/ was
# flattened and once here -- and it fails *silently*, because the wrong parent is
# usually a directory that exists. Assert rather than trust it.
ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SRC = ROOT / "docs" / "symoneural-manual.html"
DST = ROOT / "frontend" / "site" / "pages" / "training.html"

# Remap the document's own design tokens onto the SyMoNeuRaL palette, and bolt the site
# header on top so this reads as part of the site rather than an attachment to it.
OVERRIDE = """
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0e100f">
<style>
/* SyMoNeuRaL palette, mapped onto the manual's existing token names. The document is
   pinned to its dark theme below, so only the dark values need to agree with the site. */
:root, :root[data-theme="dark"]{
  --paper:#0e100f; --surface:#161a18; --sunk:#12151300;
  --ink:#f2f6f3; --muted:#a8b3ac; --rule:#28302b; --rule-soft:#1f2622;
  --copper:#ffab3d; --copper-soft:#241c12;
  --teal:#2ee08a;  --teal-soft:#0f1f18;
  --pass:#2ee08a;  --flag:#ffab3d; --waive:#a8b3ac;
  --shadow:0 1px 2px rgba(0,0,0,.5);
  /* The site's seven-size type scale, restated here because this page deliberately
     links no stylesheet -- it is a self-contained document, so it cannot reference
     frontend/site/css/symoneural.css's tokens. Keep these values identical to that file's :root.
     They govern the SyMoNeuRaL bar only; the manual's own body type is a separate
     rem-based scale that belongs to the generated document, not to the site. */
  --t1:40px; --t2:28px; --t3:20px; --t4:14.5px; --t5:12.5px; --t6:11.5px; --t7:10.5px;
}
html{background:#0e100f}
body{background:#0e100f; color:#f2f6f3}

/* ---------- let the manual use the window it is given ----------
   Garrett: this page "does not auto-fit the window". Measured at 1990x970 before this
   block: `.shell` is capped at max-width:1400px, so 295px of the window was dead on
   EACH side, and inside it `main{max-width:74ch}` measured 629px -- leaving a further
   ~770px of empty column to the right of every line of text. Meanwhile the widest table
   on the page holds 5,778px of content and was scrolling sideways inside that 629px box.

   So the shell takes the window, and the column splits in two: prose keeps a reading
   measure, because a 1,400px line of body text is not an improvement, while the things
   that were actually SCROLLING -- tables, code blocks, the folded detail blocks -- get
   the full width. Nothing is hidden and nothing is reflowed away; the same document,
   with the horizontal scrollbars it did not need.

   Below 1301px this does not apply and the document behaves exactly as it did. That is
   the same threshold the site's own no-scroll gate uses, for the same reason: it is
   above the point where this layout restacks. */
@media (min-width:1301px){
  .masthead .in, .shell{max-width:min(1800px, calc(100vw - 96px))}
  .shell{grid-template-columns:320px minmax(0,1fr)}
  main{max-width:none}
  main > :is(p,ul,ol,dl,blockquote,hr,h1,h2,h3,h4,h5,h6){max-width:86ch}
}

/* ---------- and on a phone, keep the sideways scrolling INSIDE the blocks ----------
   Measured at 390x800: the document scrolled 206px sideways as a whole page, which drags
   the header, the nav bar and every paragraph off-centre together.

   It is INLINE code that does it, not the code blocks. `pre` and `.tw` already scroll
   (~line 124 and ~line 129 of the manual's own stylesheet), so a wide capture or a
   5,778px table is contained. What is not contained is a path like
   `$CUDA_SAMPLES/build/cpp/1_Utilities/deviceQuery/deviceQuery` sitting in a sentence:
   one unbroken token, no break opportunity, 500px wide in a 353px column. Sixty such
   elements measured past the right edge, the widest reaching 596px. A handful of fenced
   blocks also converted to inline `<code>` inside a `<p>` rather than into a `<pre>`,
   which is the same problem with newlines in it.

   `overflow-wrap:anywhere` lets those tokens break, which is wrapping, not trimming --
   the whole path is still on the page and still selectable. `pre > code` is excluded
   deliberately: reflowing an `nvidia-smi` capture would change what the machine printed,
   and that block scrolls instead. This is the "let it wrap" rule in .claude/CLAUDE.md
   applied to the one page that had no rule for it.

   Two long paths are written as plain prose rather than as `<code>`, so they need the same
   permission: `main :is(p,li,...)` gets `break-word`, which is the weaker keyword -- it
   breaks a token only when the token alone cannot fit, and unlike `anywhere` it does not
   feed back into intrinsic width, so no table or grid column is re-sized by it.

   Measured after: 0px of page overflow at 390x800, from 206px. */
:not(pre) > code{overflow-wrap:anywhere}
main :is(p,li,dd,dt,blockquote,td,th,h1,h2,h3,h4,h5,h6){overflow-wrap:break-word}

/* A slim bar back to the site, matching the other pages. */
.sn-bar{
  position:sticky; top:0; z-index:60; display:flex; align-items:center; gap:14px;
  padding:11px 22px; background:rgba(14,16,15,.9); backdrop-filter:blur(14px);
  border-bottom:1px solid #28302b;
  font:var(--t4)/1 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;
}
.sn-bar a{color:#a8b3ac; text-decoration:none; font-size:var(--t4)}
.sn-bar a:hover{color:#f2f6f3}
.sn-bar .brand{display:flex; align-items:center; gap:10px; color:#f2f6f3; font-weight:650}
.sn-bar .brand i{font-style:normal; color:#2ee08a}
.sn-bar .sp{margin-left:auto}
/* The site's "Have one built" CTA. Named `.snbuild`, NOT `.cta`: this page carries its own
   self-contained stylesheet and a generic class name here would be the fifth instance of
   the collision that has already cost this project four rounds (`.bar` collapsed the site
   header to 7px, `.live` restyled the control board legend, `.card` restyled eleven cards
   on documentation.html, `#console .sub` outranked `.mod .sub`). Every shared-sounding
   name in this file is scoped under `.sn-bar` for the same reason. */
.sn-bar .snbuild{
  background:#2ee08a; color:#07130d; font-weight:650; font-size:var(--t5);
  padding:7px 16px; border-radius:999px; white-space:nowrap;
}
.sn-bar .snbuild:hover{background:#4af09e; color:#07130d}
.sn-bar .brand b{font-weight:650}
.sn-bar .live{
  display:inline-flex; align-items:center; gap:7px; background:rgba(46,224,138,.13);
  border:1px solid rgba(46,224,138,.4); color:#2ee08a; border-radius:999px;
  padding:5px 12px; font-size:var(--t5); font-weight:600;
}
.sn-bar .live s{width:7px;height:7px;border-radius:50%;background:#2ee08a;
  text-decoration:none; display:block; animation:snpulse 2.2s ease-in-out infinite}
@keyframes snpulse{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.sn-bar .live s{animation:none}}
@media (max-width:760px){ .sn-bar .hide{display:none} }
</style>
"""

# This page is deliberately self-contained -- it links no stylesheet, so it cannot simply
# reuse the site header markup, which would arrive unstyled. Its own bar is kept and
# corrected instead. Three real defects, all visible in the screenshot Garrett sent:
#
# 1. THE SPLIT WORDMARK. `.sn-bar .brand` is `display:flex; gap:10px`, and the wordmark was
#    written bare as `SyMoNeu<i>RaL</i>`. In a flex container each text run becomes its own
#    anonymous flex item, so "SyMoNeu" and "RaL" were TWO items with a 10px gap forced
#    between them -- the site's name rendered with a hole in the middle, on the one page
#    that is the engineering reference. Every other page wraps both in a single `<b>`,
#    which is one flex item and therefore one word. That `<b>` is load-bearing, not markup
#    tidiness; do not remove it.
# 2. A TWO-ITEM NAV where the rest of the site has six. Documentation, API, Account and
#    Contact were unreachable from this page.
# 3. TWO DEAD LINKS. `/#rack` and `/#hardware` were anchors on the old single-page front
#    page. `/` now 302s to `/overview` and the sections have their own URLs, so both tabs
#    landed somewhere with no such anchor and did nothing at all.
BAR = """<div class="sn-bar">
  <a class="brand" href="/"><img src="/mark-32.png" alt="" width="22" height="22"><b>SyMoNeu<i>RaL</i></b></a>
  <a class="hide" href="/documentation.html">Documentation</a>
  <a class="hide" href="/training.html">Manuals</a>
  <a class="hide" href="/livestack">Live stack</a>
  <a class="hide" href="/controlboard">Control board</a>
  <a class="hide" href="/docs">API</a>
  <a class="hide" href="/account.html">Account</a>
  <span class="sp"></span>
  <a class="snbuild" href="/build.html">Have one built</a>
</div>
"""


def main() -> int:
    if not SRC.exists():
        print(f"source missing: {SRC}")
        return 1
    html = SRC.read_text(errors="ignore")
    before = len(html)

    # --- branding -------------------------------------------------------------------
    # Whole phrases and paths only. A bare 'MIT' replace would eat 'limits' and 'submit'.
    subs = [
        (r"MIT AI Training\s*&mdash;\s*Consolidated Manual", "SyMoNeuRaL Training"),
        (r"MIT AI Training\s*—\s*Consolidated Manual", "SyMoNeuRaL Training"),
        (r"\bMIT AI Training\b", "SyMoNeuRaL Training"),
        (r"\bConsolidated manual\b", "Local AI engineering"),
        (r"\bConsolidated Manual\b", "Local AI Engineering"),
        # Scrub whatever absolute path this checkout happens to live at, rather than a
        # hardcoded one -- hardcoding meant the scrub silently stopped working the
        # moment the repo moved, which is exactly when a dev path would leak.
        (re.escape(str(ROOT)), "/opt/symoneural"),
        (r"~/MIT_AI_Training/MIT_AI_Training", "~/symoneural"),
        (r"\bMIT_AI_Training\b", "symoneural"),
    ]
    for pattern, replacement in subs:
        html = re.sub(pattern, replacement, html)

    # Anchors are load-bearing -- people link to them. The only id that carried the old
    # brand gets an invisible alias so existing deep links still land.
    html = html.replace(
        'id="mit-ai-training-consolidated-manual"',
        'id="symoneural-training"><span id="mit-ai-training-consolidated-manual"></span'
        , 1) if 'id="mit-ai-training-consolidated-manual"' in html else html

    # --- broken contents links ------------------------------------------------------
    # Five TOC entries carry a double dash where the heading id has a single one
    # (#part-i--your-machine vs id="part-i-your-machine"), so those links have always
    # silently done nothing. Repair by pointing each href at an id that actually exists
    # rather than by renaming ids, which would break anything already linking to them.
    ids = set(re.findall(r'id="([^"]+)"', html))
    repaired = 0
    for anchor in set(re.findall(r'href="#([^"]+)"', html)):
        if anchor in ids:
            continue
        collapsed = re.sub(r"-{2,}", "-", anchor)
        if collapsed in ids:
            html = html.replace(f'href="#{anchor}"', f'href="#{collapsed}"')
            repaired += 1
    if repaired:
        print(f"  repaired {repaired} broken contents links")

    # --- theme ----------------------------------------------------------------------
    html = re.sub(r"<html([^>]*)>", r'<html\1 data-theme="dark">', html, count=1)
    html = html.replace("</head>", OVERRIDE + "</head>", 1)
    html = re.sub(r"(<body[^>]*>)", r"\1\n" + BAR, html, count=1)

    # The masthead still describes the old artefact; say what this is now.
    html = html.replace(
        "Eleven playbooks and thirty-four CUDA Python sample documents,",
        "The engineering reference behind the SyMoNeuRaL stack &mdash; playbooks and CUDA "
        "sample documents,")

    DST.write_text(html)
    remaining = len(re.findall(r"\bMIT AI Training\b|\bMIT_AI_Training\b", html))
    print(f"training.html written: {before:,} -> {len(html):,} bytes")
    print(f"  brand references remaining: {remaining}")
    print(f"  heading anchors preserved:  {len(re.findall(r'id=\"[^\"]+\"', html))}")
    print(f"  runnability-matrix anchor:  {'yes' if 'id=\"runnability-matrix\"' in html else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
